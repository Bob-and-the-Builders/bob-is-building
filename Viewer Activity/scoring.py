from supabase_manager import client
from datetime import datetime, timezone
from typing import Dict, List
import math

# --- Helpers ---
def _parse_ts(ts):
    if not ts:
        return None
    try:
        # Handle ISO with or without timezone/Z
        t = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except Exception:
        return None

# --- Viewer Trust Score (VTS) ---
def compute_vts_row(u: Dict) -> float:
    # Base from explicit viewer_trust_score when available
    try:
        if u.get("viewer_trust_score") is not None:
            vts = float(u.get("viewer_trust_score"))
        else:
            # Derive from account age if needed
            created = _parse_ts(u.get("created_at") or u.get("account_created_at")) or datetime.now(timezone.utc)
            age_days = max(0, (datetime.now(timezone.utc) - created).days)
            vts = 40 + 0.25 * age_days  # up to ~100 over long-lived accounts
    except Exception:
        vts = 50.0

    # Penalize known bot flags
    if bool(u.get("likely_bot")):
        vts -= 30.0

    # KYC level (1 low risk .. 4 critical risk)
    lvl = u.get("kyc_level")
    try:
        lvl = int(lvl) if lvl is not None else None
    except Exception:
        lvl = None
    if lvl == 1:  # low risk
        vts += 5.0
    elif lvl == 2:  # medium
        vts += 0.0
    elif lvl == 3:  # high
        vts -= 15.0
    elif lvl == 4:  # critical
        vts -= 40.0

    return float(max(0.0, min(100.0, vts)))

def get_vts_map(user_ids: List[str]) -> Dict[str, float]:
    if not user_ids:
        return {}
    # Try users keyed by user_id; fall back to id
    rows: List[Dict] = []
    try:
        rows = client.table("users").select("*").in_("user_id", user_ids).execute().data or []
    except Exception:
        try:
            rows = client.table("users").select("*").in_("id", user_ids).execute().data or []
        except Exception:
            rows = []
    out: Dict[str, float] = {}
    for r in rows:
        uid = r.get("user_id") or r.get("id")
        if uid is None:
            continue
        out[str(uid)] = compute_vts_row(r)
    return out

# --- Lightweight moderation heuristics ---
TOXIC_WORDS = {
    "idiot", "stupid", "dumb", "trash", "hate", "kill", "die",
}
SPAM_PATTERNS = {"http://", "https://", ".com", "free", "promo", "giveaway"}

def perspective_en(text: str) -> Dict[str, float]:
    if not text:
        return {"toxicity": 0.0, "insult": 0.0}
    t = text.lower()
    tox_hits = sum(1 for w in TOXIC_WORDS if w in t)
    toxicity = 1 - math.exp(-0.8 * tox_hits)
    insult = min(1.0, 0.6 * toxicity)
    return {"toxicity": float(toxicity), "insult": float(insult)}

def spam_prob(text: str) -> float:
    if not text:
        return 0.0
    t = text.lower()
    hits = sum(1 for p in SPAM_PATTERNS if p in t)
    # crude cap at ~0.9
    return float(min(0.9, 0.25 * hits))

# --- Component scores (0..100) ---
def comment_quality(comments: List[Dict], vts_map: Dict[str, float]) -> float:
    if not comments:
        return 50.0
    scores = []
    for c in comments:
        m = (c.get("moderation") or {})
        tox = float(m.get("toxicity", 0.0) or 0.0)
        ins = float(m.get("insult", 0.0) or 0.0)
        spam = float(m.get("spam_prob", 0.0) or 0.0)
        vts = float(vts_map.get(c.get("user_id"), 50.0)) / 100.0
        base = 100.0 * (1.0 - 0.7 * tox - 0.5 * ins - 0.8 * spam)
        scores.append(max(0.0, min(100.0, base)) * (0.5 + 0.5 * vts))
    return float(sum(scores) / max(1, len(scores)))

def like_integrity(likes: List[Dict], vts_map: Dict[str, float]) -> float:
    if not likes:
        return 50.0
    base = sum(vts_map.get(l.get("user_id"), 50.0) for l in likes) / len(likes)

    # Device/IP clustering penalty: many unique users per device/IP is suspicious
    devices = {}
    ips = {}
    for l in likes:
        uid = l.get("user_id")
        d = l.get("device_id")
        ip = l.get("ip_hash")
        if d:
            devices.setdefault(d, set()).add(uid)
        if ip:
            ips.setdefault(ip, set()).add(uid)

    penalty = 0.0
    if devices:
        users_per_device = sum(len(s) for s in devices.values()) / max(1, len(devices))
        # allow up to 1.2 users/device without penalty; scale after
        dev_excess = max(0.0, users_per_device - 1.2)
        penalty += min(25.0, 12.0 * dev_excess)
    if ips:
        users_per_ip = sum(len(s) for s in ips.values()) / max(1, len(ips))
        ip_excess = max(0.0, users_per_ip - 1.5)
        penalty += min(25.0, 10.0 * ip_excess)

    return float(max(0.0, min(100.0, base - penalty)))

def report_cleanliness(reports: List[Dict], vts_map: Dict[str, float]) -> float:
    if not reports:
        return 90.0
    # High-VTS reports indicate real issues; reduce cleanliness accordingly
    weight = sum((vts_map.get(r.get("user_id"), 50.0) / 100.0) for r in reports)
    penalty = 25.0 * weight
    return float(max(0.0, 100.0 - penalty))

def authentic_engagement(features: Dict[str, float]) -> float:
    # Like/comment rates
    lpv = float(features.get("likes_per_view", 0.0) or 0.0)
    cpv = float(features.get("comments_per_view", 0.0) or 0.0)

    # Adaptive targets based on optional metadata
    duration = features.get("video_duration_s")

    # Baselines
    like_target = 0.10
    comment_target = 0.02

    # Duration scaling: shorter videos tend to concentrate engagement
    if isinstance(duration, (int, float)) and duration and duration > 0:
        dur_scale = max(0.7, min(1.3, 15.0 / float(duration)))
        like_target *= dur_scale
        comment_target *= dur_scale


    # Normalize to 0..100 with adaptive targets
    s_like = 100.0 * lpv / max(1e-6, like_target)
    s_comm = 100.0 * cpv / max(1e-6, comment_target)

    # Cap scores
    s_like = min(100.0, s_like)
    s_comm = min(100.0, s_comm)

    base = 0.6 * s_like + 0.4 * s_comm

    return float(max(0.0, min(100.0, base)))

def eis_score(ae: float, cq: float, li: float, rc: float) -> float:
    # Weighted blend
    return float(max(0.0, min(100.0, 0.4 * ae + 0.25 * cq + 0.2 * li + 0.15 * rc)))
