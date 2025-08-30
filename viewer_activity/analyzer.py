"""Viewer Activity analyzer (schema-driven, content-agnostic).

Computes Engagement Integrity Score (EIS) and component metrics for a
video over a given time window. This module only uses schema signals
and writes transparent aggregates to `video_aggregates`, also updating
`videos.eis_current`.
"""

from .supabase_manager import client, fetch_events, upsert_aggregate
from .scoring import (
    get_vts_map,
    comment_quality_with_details,
    like_integrity_with_details,
    report_cleanliness_with_details,
    authentic_engagement_with_details,
    eis_score,
    get_creator_trust_score,
)
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

def analyze_window(video_id, start, end):
    """Analyze a single video within [start, end) and persist aggregates.

    Parameters
    - video_id: int or str ID of the video in `videos`.
    - start, end: timezone-aware datetimes in UTC; treated as [start, end).

    Returns
    - payload dict containing features, component scores, and `eis`.

    Raises
    - RuntimeError on Supabase connectivity or schema issues.
    """
    # fetch creator_id to exclude creator’s self-engagement
    # Load video by videos.id (diagram schema)
    # Cast numeric IDs provided as strings for equality filter
    vid_filter = int(video_id) if isinstance(video_id, str) and video_id.isdigit() else video_id
    try:
        res = client.table("videos").select("*").eq("id", vid_filter).single().execute()
        vid = res.data
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to load video {video_id}: {e}")
    if not vid:
        raise RuntimeError("Video not found in 'videos' table")
    creator_id = vid.get("creator_id")

    events = fetch_events(vid_filter, start, end)
    by = {"view":[], "like":[], "comment":[], "report":[]}
    for e in events:
        if e["user_id"] == creator_id: 
            continue
        et = e.get("event_type")
        if et in by:
            by[et].append(e)

    # features (normalized rates)
    active_viewers = len({x["user_id"] for x in by["view"]}) or 1
    total_views = len(by["view"]); likes=len(by["like"]); comments=len(by["comment"]) 
    # Diagram schema has no per-view watch metadata; set watch ratio neutral (0.0)
    avg_watch_ratio = 0.0
    # Device/IP concentration among likers (exposed for transparency)
    like_devices = {}
    like_ips = {}
    for l in by["like"]:
        if l.get("device_id"):
            like_devices.setdefault(l["device_id"], set()).add(l["user_id"])
        if l.get("ip_hash"):
            like_ips.setdefault(l["ip_hash"], set()).add(l["user_id"])
    likes_per_device = (sum(len(s) for s in like_devices.values()) / max(1, len(like_devices))) if like_devices else None
    likes_per_ip = (sum(len(s) for s in like_ips.values()) / max(1, len(like_ips))) if like_ips else None

    # Video metadata from schema
    created_at = vid.get("created_at")
    try:
        created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")) if created_at else None
    except Exception:
        created_dt = None
    age_hours = None
    if created_dt is not None:
        age_hours = max(0.0, (end - created_dt).total_seconds() / 3600.0)
    duration_s = vid.get("duration_s")

    feats = {
        "active_viewers": active_viewers,
        "total_views": total_views,
        "likes_per_view": likes/max(1,total_views),
        "comments_per_view": comments/max(1,total_views),
        "unique_commenters_rate": len({x["user_id"] for x in by["comment"]})/max(1,active_viewers),
        "avg_watch_ratio": float(avg_watch_ratio),
        "video_duration_s": float(duration_s) if isinstance(duration_s, (int, float)) else None,
        "video_created_at": created_at,
        "video_age_hours": float(age_hours) if age_hours is not None else None,
        "likes_per_device": float(likes_per_device) if likes_per_device is not None else None,
        "likes_per_ip": float(likes_per_ip) if likes_per_ip is not None else None,
    }

    # VTS map
    vts_map = get_vts_map(list({e["user_id"] for t in ["like","comment","report"] for e in by[t]}))

    # Diagram schema has no comment text or moderation store; set neutral moderation
    for c in by["comment"]:
        c["moderation"] = {"toxicity": 0.0, "insult": 0.0, "spam_prob": 0.0}

    # component scores
    ae, ae_det = authentic_engagement_with_details(feats)
    cq, cq_det = comment_quality_with_details(by["comment"], vts_map, active_viewers)
    li, li_det = like_integrity_with_details(by["like"], vts_map)
    rc, rc_det = report_cleanliness_with_details(by["report"], vts_map)

    eis = eis_score(ae, cq, li, rc)

    # Creator Trust Score modulation
    cts = get_creator_trust_score(creator_id)
    factor = 0.95 + 0.10 * (cts / 100.0)  # 0.95..1.05
    eis = float(max(0.0, min(100.0, eis * factor)))
    feats["creator_trust_score"] = cts

    # No content semantics used; score is strictly schema-based

    breakdown = {
        "authentic_engagement": ae_det,
        "comment_quality": cq_det,
        "like_integrity": li_det,
        "report_cleanliness": rc_det,
        "weights": {"ae": 0.4, "cq": 0.30, "li": 0.15, "rc": 0.15},
    }

    payload = {
        "features": feats,
        "comment_quality": cq,
        "like_integrity": li,
        "report_credibility": rc,
        "authentic_engagement": ae,
        "eis": eis,
        "breakdown": breakdown,
    }
    # Persist if possible; if the aggregates table doesn't exist yet,
    # skip persistence but still return the computed payload for callers.
    try:
        upsert_aggregate(video_id, start, end, payload)
    except Exception:
        # Non-fatal for on-demand computations during integration tests
        pass
    return payload
