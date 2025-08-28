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
    # Prefer an explicit viewer_trust_score if provided by schema
    if "viewer_trust_score" in u and u["viewer_trust_score"] is not None:
        try:
            return float(max(0, min(100, float(u["viewer_trust_score"]))))
        except Exception:
            pass
    # Otherwise derive from account age and simple risk proxies if present
    created = _parse_ts(u.get("account_created_at") or u.get("created_at")) or datetime.now(timezone.utc)
    age_days = max(0, (datetime.now(timezone.utc) - created).days)
    ip_risk = int(u.get("ip_asn_risk", 0) or 0)
    prior = float(u.get("prior_false_report_rate", 0.0) or 0.0)
    vts = 50 + 0.2 * age_days - 15 * ip_risk - 30 * prior
    return float(max(0, min(100, vts)))

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
    v = [vts_map.get(l.get("user_id"), 50.0) for l in likes]
    return float(sum(v) / len(v))

def report_cleanliness(reports: List[Dict], vts_map: Dict[str, float]) -> float:
    if not reports:
        return 90.0
    # High-VTS reports indicate real issues; reduce cleanliness accordingly
    weight = sum((vts_map.get(r.get("user_id"), 50.0) / 100.0) for r in reports)
    penalty = 25.0 * weight
    return float(max(0.0, 100.0 - penalty))

def authentic_engagement(features: Dict[str, float]) -> float:
    # Diagram schema lacks watch-duration; rely on like/comment rates only
    lpv = float(features.get("likes_per_view", 0.0) or 0.0)
    cpv = float(features.get("comments_per_view", 0.0) or 0.0)
    s_like = min(100.0, 100.0 * lpv / 0.1)   # ~0.1 good
    s_comm = min(100.0, 100.0 * cpv / 0.02)  # ~0.02 good
    return float(0.6 * s_like + 0.4 * s_comm)

def eis_score(ae: float, cq: float, li: float, rc: float) -> float:
    # Weighted blend
    return float(max(0.0, min(100.0, 0.4 * ae + 0.25 * cq + 0.2 * li + 0.15 * rc)))
