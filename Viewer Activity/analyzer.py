# analyzer.py (patched core)
from supabase_manager import client, fetch_events, upsert_aggregate
from scoring import (
    get_vts_map,
    comment_quality,
    like_integrity,
    report_cleanliness,
    authentic_engagement,
    eis_score,
)
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

def analyze_window(video_id, start, end, use_semantics=False):
    # fetch creator_id to exclude creator’s self-engagement
    # Load video by videos.id (diagram schema)
    # Cast numeric IDs provided as strings for equality filter
    vid_filter = int(video_id) if isinstance(video_id, str) and video_id.isdigit() else video_id
    res = client.table("videos").select("*").eq("id", vid_filter).single().execute()
    vid = res.data
    if not vid:
        raise RuntimeError("Video not found in 'videos' table")
    creator_id = vid.get("creator_id")

    events = fetch_events(vid_filter, start, end)
    by = {"view":[], "like":[], "comment":[], "report":[]}
    for e in events:
        if e["user_id"] == creator_id: 
            continue
        by[e["event_type"]].append(e)

    # features (normalized rates)
    active_viewers = len({x["user_id"] for x in by["view"]}) or 1
    total_views = len(by["view"]); likes=len(by["like"]); comments=len(by["comment"])
    # Diagram schema has no metadata; set watch ratio neutral (0.0)
    avg_watch_ratio = 0.0
    # Optional video metadata
    duration_s = (
        vid.get("duration_seconds")
        or vid.get("duration_s")
        or None
    )
    fps = vid.get("fps") or None
    width = vid.get("width") or None
    height = vid.get("height") or None
    has_audio = vid.get("has_audio") if vid.get("has_audio") is not None else None
    feats = {
        "active_viewers": active_viewers,
        "total_views": total_views,
        "likes_per_view": likes/max(1,total_views),
        "comments_per_view": comments/max(1,total_views),
        "unique_commenters_rate": len({x["user_id"] for x in by["comment"]})/max(1,active_viewers),
        "avg_watch_ratio": float(avg_watch_ratio),
        "video_duration_s": float(duration_s) if duration_s is not None else None,
        "fps": fps,
        "width": width,
        "height": height,
        "has_audio": has_audio,
    }

    # VTS map
    vts_map = get_vts_map(list({e["user_id"] for t in ["like","comment","report"] for e in by[t]}))

    # Diagram schema has no comment text or moderation store; set neutral moderation
    for c in by["comment"]:
        c["moderation"] = {"toxicity": 0.0, "insult": 0.0, "spam_prob": 0.0}

    # component scores
    cq = comment_quality(by["comment"], vts_map)
    li = like_integrity(by["like"], vts_map)
    rc = report_cleanliness(by["report"], vts_map)
    ae = authentic_engagement(feats)

    eis = eis_score(ae, cq, li, rc)

    # optional semantics-lite (tiny nudge, stays in scope)
    if use_semantics:
        from semantics_lite import semantics_bonus
        title = vid.get("title") or ""
        bonus = semantics_bonus(title, [])
        eis = min(100.0, eis + bonus)

    payload = {
        "features": feats,
        "comment_quality": cq,
        "like_integrity": li,
        "report_credibility": rc,
        "authentic_engagement": ae,
        "eis": eis
    }
    upsert_aggregate(video_id, start, end, payload)
    return payload
