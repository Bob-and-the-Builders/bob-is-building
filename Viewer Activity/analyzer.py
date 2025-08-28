# analyzer.py (patched core)
from supabase_manager import client, fetch_events, upsert_aggregate
from scoring import get_vts_map, comment_quality, like_integrity, report_cleanliness, authentic_engagement, eis_score, perspective_en, spam_prob
from datetime import datetime, timedelta, timezone
import numpy as np

UTC = timezone.utc

def analyze_window(video_id, start, end, use_semantics=False):
    # fetch creator_id to exclude creator’s self-engagement
    vid = client.table("videos").select("creator_id, caption, hashtags").eq("video_id", video_id).single().execute().data
    creator_id = vid["creator_id"]

    events = fetch_events(video_id, start, end)
    by = {"view":[], "like":[], "comment":[], "report":[]}
    for e in events:
        if e["user_id"] == creator_id: 
            continue
        by[e["event_type"]].append(e)

    # features (normalized rates)
    active_viewers = len({x["user_id"] for x in by["view"]}) or 1
    total_views = len(by["view"]); likes=len(by["like"]); comments=len(by["comment"])
    avg_watch_ratio = np.mean([
        min((x.get("metadata",{}).get("watch_duration",0.0)) / max(1e-6, x.get("metadata",{}).get("video_duration",15)),1.0)
        for x in by["view"]
    ]) if total_views else 0.0
    feats = {
        "active_viewers": active_viewers,
        "total_views": total_views,
        "likes_per_view": likes/max(1,total_views),
        "comments_per_view": comments/max(1,total_views),
        "unique_commenters_rate": len({x["user_id"] for x in by["comment"]})/max(1,active_viewers),
        "avg_watch_ratio": float(avg_watch_ratio)
    }

    # VTS map
    vts_map = get_vts_map(list({e["user_id"] for t in ["like","comment","report"] for e in by[t]}))

    # moderate comments (EN) – cache results
    from supabase_manager import client as sbc
    existing = sbc.table("comment_moderation").select("event_id").in_("event_id",[c["event_id"] for c in by["comment"]]).execute().data or []
    have = {x["event_id"] for x in existing}
    rows=[]
    for c in by["comment"]:
        if c["event_id"] in have: continue
        text=(c.get("metadata") or {}).get("text","")
        mod = perspective_en(text) if text else {"toxicity":0.0,"insult":0.0}
        rows.append({"event_id": c["event_id"], **mod, "spam_prob": spam_prob(text), "sentiment": 0.0})
    if rows: sbc.table("comment_moderation").insert(rows).execute()
    mods = sbc.table("comment_moderation").select("*").in_("event_id",[c["event_id"] for c in by["comment"]]).execute().data or []
    mod_map = {m["event_id"]: m for m in mods}
    for c in by["comment"]: c["moderation"]=mod_map.get(c["event_id"],{})

    # component scores
    cq = comment_quality(by["comment"], vts_map)
    li = like_integrity(by["like"], vts_map)
    rc = report_cleanliness(by["report"], vts_map)
    ae = authentic_engagement(feats)

    eis = eis_score(ae, cq, li, rc)

    # optional semantics-lite (tiny nudge, stays in scope)
    if use_semantics:
        from semantics_lite import semantics_bonus
        bonus = semantics_bonus(vid.get("caption",""), vid.get("hashtags") or [])
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
