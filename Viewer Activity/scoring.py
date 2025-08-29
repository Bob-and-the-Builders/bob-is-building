from supabase_manager import client
from datetime import datetime, timezone
from typing import Dict, List, Tuple
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
def _vts_lookup(vts_map: Dict[str, float], user_id) -> float:
    """Lookup helper that normalizes event user_id (int/str) to vts_map keys (str)."""
    if user_id is None:
        return 50.0
    try:
        return float(vts_map.get(str(user_id), 50.0))
    except Exception:
        return 50.0


def comment_quality_with_details(comments: List[Dict], vts_map: Dict[str, float]) -> Tuple[float, Dict]:
    if not comments:
        return 50.0, {"avg_vts": None, "moderation_avg": {"toxicity": 0.0, "insult": 0.0, "spam_prob": 0.0}}
    scores = []
    tox_acc = 0.0; ins_acc = 0.0; spam_acc = 0.0; n=0
    for c in comments:
        m = (c.get("moderation") or {})
        tox = float(m.get("toxicity", 0.0) or 0.0)
        ins = float(m.get("insult", 0.0) or 0.0)
        spam = float(m.get("spam_prob", 0.0) or 0.0)
        vts = _vts_lookup(vts_map, c.get("user_id")) / 100.0
        base = 100.0 * (1.0 - 0.7 * tox - 0.5 * ins - 0.8 * spam)
        scores.append(max(0.0, min(100.0, base)) * (0.5 + 0.5 * vts))
        tox_acc += tox; ins_acc += ins; spam_acc += spam; n+=1
    score = float(sum(scores) / max(1, len(scores)))
    details = {
        "avg_vts": float(sum(_vts_lookup(vts_map, c.get("user_id")) for c in comments)/len(comments)),
        "moderation_avg": {
            "toxicity": tox_acc/max(1,n),
            "insult": ins_acc/max(1,n),
            "spam_prob": spam_acc/max(1,n),
        }
    }
    return score, details

def comment_quality(comments: List[Dict], vts_map: Dict[str, float]) -> float:
    return comment_quality_with_details(comments, vts_map)[0]

def like_integrity_with_details(likes: List[Dict], vts_map: Dict[str, float]) -> Tuple[float, Dict]:
    if not likes:
        return 50.0, {"avg_vts": None, "users_per_device": None, "users_per_ip": None, "penalty_device": 0.0, "penalty_ip": 0.0}
    base = sum(_vts_lookup(vts_map, l.get("user_id")) for l in likes) / len(likes)

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

    users_per_device = (sum(len(s) for s in devices.values()) / max(1, len(devices))) if devices else 0.0
    users_per_ip = (sum(len(s) for s in ips.values()) / max(1, len(ips))) if ips else 0.0

    penalty_device = 0.0
    penalty_ip = 0.0
    if devices:
        dev_excess = max(0.0, users_per_device - 1.2)
        penalty_device = min(25.0, 12.0 * dev_excess)
    if ips:
        ip_excess = max(0.0, users_per_ip - 1.5)
        penalty_ip = min(25.0, 10.0 * ip_excess)

    penalty = penalty_device + penalty_ip
    score = float(max(0.0, min(100.0, base - penalty)))
    details = {
        "avg_vts": base,
        "users_per_device": users_per_device or None,
        "users_per_ip": users_per_ip or None,
        "penalty_device": penalty_device,
        "penalty_ip": penalty_ip,
        "penalty_total": penalty,
    }
    return score, details

def like_integrity(likes: List[Dict], vts_map: Dict[str, float]) -> float:
    return like_integrity_with_details(likes, vts_map)[0]

def report_cleanliness_with_details(reports: List[Dict], vts_map: Dict[str, float]) -> Tuple[float, Dict]:
    if not reports:
        return 90.0, {"weighted_vts": 0.0, "penalty": 0.0}
    weight = sum((_vts_lookup(vts_map, r.get("user_id")) / 100.0) for r in reports)
    penalty = 25.0 * weight
    score = float(max(0.0, 100.0 - penalty))
    return score, {"weighted_vts": weight, "penalty": penalty}

def report_cleanliness(reports: List[Dict], vts_map: Dict[str, float]) -> float:
    return report_cleanliness_with_details(reports, vts_map)[0]

def authentic_engagement_with_details(features: Dict[str, float]) -> Tuple[float, Dict]:
    # Schema-driven scoring with optional duration and recency adjustments
    lpv = float(features.get("likes_per_view", 0.0) or 0.0)
    cpv = float(features.get("comments_per_view", 0.0) or 0.0)

    like_target = 0.10   # 10% likes per view considered strong
    comment_target = 0.02  # 2% comments per view considered strong

    # Adjust targets by video duration if provided
    duration = features.get("video_duration_s")
    duration_scale = 1.0
    if isinstance(duration, (int, float)) and duration and duration > 0:
        duration_scale = max(0.7, min(1.3, 15.0 / float(duration)))
        like_target *= duration_scale
        comment_target *= duration_scale

    # Adjust by recency (hours since created_at): newer videos get leniency; older, slightly stricter
    age_h = features.get("video_age_hours")
    recency_scale = 1.0
    if isinstance(age_h, (int, float)) and age_h >= 0:
        recency_scale = max(0.8, min(1.2, 0.8 + 0.4 * min(1.0, float(age_h) / 24.0)))
        like_target *= recency_scale
        comment_target *= recency_scale

    s_like = min(100.0, 100.0 * lpv / max(1e-6, like_target))
    s_comm = min(100.0, 100.0 * cpv / max(1e-6, comment_target))
    score = float(max(0.0, min(100.0, 0.6 * s_like + 0.4 * s_comm)))
    details = {
        "lpv": lpv,
        "cpv": cpv,
        "like_target": like_target,
        "comment_target": comment_target,
        "duration_scale": duration_scale,
        "recency_scale": recency_scale,
        "s_like": s_like,
        "s_comm": s_comm,
    }
    return score, details

def authentic_engagement(features: Dict[str, float]) -> float:
    return authentic_engagement_with_details(features)[0]

def eis_score(ae: float, cq: float, li: float, rc: float) -> float:
    # Weighted blend
    return float(max(0.0, min(100.0, 0.4 * ae + 0.25 * cq + 0.2 * li + 0.15 * rc)))
