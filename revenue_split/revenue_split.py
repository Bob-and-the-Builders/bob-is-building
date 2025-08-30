# revenue_split/revenue_split.py
from __future__ import annotations

import os
import math
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict, Counter
from typing import Dict, List, Tuple

from supabase import create_client, Client

# -----------------------------
# Knobs
# -----------------------------
QUALITY_Z_TO_PCT   = 0.01     # z * 1% → clamped below
QUALITY_CLAMP_PCT  = 0.02     # ±2%

INTEGRITY_RANGE_PCT = 0.03    # ±3% mapped 0..1
EARLY_WINDOW_HRS    = 2
EARLY_KICKER_MULT   = 1.05
EARLY_MIN_VIEWS     = 50
EARLY_DEV_RATIO     = 0.50
EARLY_IP_RATIO      = 0.40

CLUSTER_START_SHARE = 0.20
CLUSTER_MAX_PENALTY = 0.30
CLUSTER_RAMP        = 2.0

# Per-event weights
EVENT_WEIGHTS = {"view": 1, "like": 3, "comment": 5, "share": 8}
PAGE_SIZE = 10000

# --- Creator score knobs (layered after 7-day integrity) ---
CREATOR_TRUST_MIN_MULT = 0.80   # payout floor at score = 0
CREATOR_TRUST_MAX_MULT = 1.20   # payout cap at score = 100
CREATOR_TRUST_SCALE_MAX = 100   # expected score range 0..100
PENALIZE_LIKELY_BOT = True      # hard-exclude if users.likely_bot is true

# --- KYC caps (per run: daily or monthly) ---
# level 1 => $50 max; level 2 => $500 max; level 3+ => unlimited
KYC_CAPS_CENTS = {0: 0,1: 5_000, 2: 50_000}  # cents


# -----------------------------
# Supabase helpers
# -----------------------------
def make_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)

def daterange_utc(d: date) -> Tuple[str, str]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end   = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()

def fetch_all(builder_fn, page_size=PAGE_SIZE) -> List[dict]:
    out: List[dict] = []
    from_idx = 0
    while True:
        q = builder_fn().range(from_idx, from_idx + page_size - 1)
        res = q.execute()
        rows = res.data or []
        out.extend(rows)
        if len(rows) < page_size:
            break
        from_idx += page_size
    return out

def iso_to_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# -----------------------------
# Data loads
# -----------------------------
def load_events_for_day(sb: Client, run_day: date) -> List[dict]:
    start, end = daterange_utc(run_day)
    return fetch_all(lambda: sb.table("event").select("*").gte("ts", start).lt("ts", end))

def load_events_between(sb: Client, start: datetime, end: datetime) -> List[dict]:
    return fetch_all(lambda: sb.table("event").select("*").gte("ts", start.isoformat()).lt("ts", end.isoformat()))

def load_videos(sb: Client) -> Dict[int, dict]:
    rows = fetch_all(lambda: sb.table("videos").select("*"))
    return {r["id"]: r for r in rows}

def load_users(sb: Client) -> Dict[int, dict]:
    rows = fetch_all(lambda: sb.table("users").select("*"))
    return {r["id"]: r for r in rows}

# -----------------------------
# Multipliers
# -----------------------------
def clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))

def quality_multiplier(engagement_rate: float, mu: float, sigma: float) -> float:
    if sigma == 0:
        return 1.0
    z = (engagement_rate - mu) / sigma
    nudged = z * QUALITY_Z_TO_PCT
    return 1.0 + clamp(nudged, -QUALITY_CLAMP_PCT, QUALITY_CLAMP_PCT)

def integrity_multiplier_7d(views: int, uniq_dev: int, uniq_ip: int, likes: int, comments: int) -> float:
    dev_div = min(1.0, 5.0 * (uniq_dev / max(1.0, views)))
    ip_div  = min(1.0, 5.0 * (uniq_ip  / max(1.0, views)))
    eng_h   = min(1.0, 10.0 * ((likes + comments) / max(1.0, views)))
    score_0_1 = (dev_div + ip_div + eng_h) / 3.0
    return (1.0 - INTEGRITY_RANGE_PCT) + (score_0_1 * 2 * INTEGRITY_RANGE_PCT)

def early_kicker_mult_for_video(sb: Client, video_row: dict) -> float:
    """
    Compute early velocity in the first 2 hours AFTER creation (global window),
    not just within the run_day (crosses day boundaries if needed).
    """
    created_at = iso_to_dt(video_row["created_at"])
    window_end = created_at + timedelta(hours=EARLY_WINDOW_HRS)
    evs = load_events_between(sb, created_at, window_end)

    early = [e for e in evs if e.get("video_id") == video_row["id"]]
    if not early:
        return 1.0

    views = sum(1 for e in early if e["event_type"] == "view")
    if views < EARLY_MIN_VIEWS:
        return 1.0

    uniq_dev = len({e.get("device_id") for e in early if e.get("device_id") is not None})
    uniq_ip  = len({e.get("ip_hash") for e in early if e.get("ip_hash") is not None})

    if uniq_dev >= EARLY_DEV_RATIO * views and uniq_ip >= EARLY_IP_RATIO * views:
        return EARLY_KICKER_MULT
    return 1.0

def cluster_penalty_mult(day_events_for_video: List[dict]) -> float:
    views = [e for e in day_events_for_video if e["event_type"] == "view"]
    if not views:
        return 1.0
    dev_counts = Counter([e.get("device_id") for e in views if e.get("device_id") is not None])
    ip_counts  = Counter([e.get("ip_hash")   for e in views if e.get("ip_hash") is not None])

    def top_share(cnt: Counter) -> float:
        total = sum(cnt.values())
        return 0.0 if total == 0 else (max(cnt.values()) / total)

    ts = max(top_share(dev_counts), top_share(ip_counts))
    if ts <= CLUSTER_START_SHARE:
        return 1.0
    penalty = CLUSTER_RAMP * (ts - CLUSTER_START_SHARE)
    return max(1.0 - CLUSTER_MAX_PENALTY, 1.0 - penalty)

def trust_to_mult(score: float | int | None) -> float:
    """
    Map a creator_trust_score in [0..CREATOR_TRUST_SCALE_MAX] to a multiplier in
    [CREATOR_TRUST_MIN_MULT .. CREATOR_TRUST_MAX_MULT]. Missing/bad values → 1.0.
    """
    if score is None:
        return 1.0
    try:
        s = float(score)
    except Exception:
        return 1.0
    s = max(0.0, min(s, float(CREATOR_TRUST_SCALE_MAX))) / float(CREATOR_TRUST_SCALE_MAX)
    return CREATOR_TRUST_MIN_MULT + s * (CREATOR_TRUST_MAX_MULT - CREATOR_TRUST_MIN_MULT)

# -----------------------------
# KYC cap application (redistribution)
# -----------------------------
def _fetch_kyc_levels(sb: Client, creator_ids: List[int]) -> Dict[int, int]:
    if not creator_ids:
        return {}
    res = (
        sb.table("users")
        .select("id, kyc_level")
        .in_("id", creator_ids)
        .execute()
    )
    out: Dict[int, int] = {}
    for r in (res.data or []):
        cid = int(r["id"])
        raw = r.get("kyc_level", None)
        # Treat None/empty as 0; coerce everything else to int safely
        if raw in (None, "", "None"):
            lvl = 0
        else:
            try:
                lvl = int(raw)
            except Exception:
                lvl = 0  # fallback to most restrictive
        out[cid] = lvl
    return out

def apply_kyc_caps(sb: Client, allocations: Dict[int, int], units: Dict[int, float]) -> Tuple[Dict[int, int], int]:
    """
    Enforce per-creator KYC earning caps (per run). Returns (adjusted_allocations, unallocated_cents).
    If everyone hits caps, unallocated_cents may be > 0.
    """
    if not allocations:
        return {}, 0
    pool = sum(allocations.values())
    alloc = dict(allocations)  # working copy

    kyc_levels = _fetch_kyc_levels(sb, list(alloc.keys()))
    caps = {cid: KYC_CAPS_CENTS.get(kyc_levels.get(cid, 0)) for cid in alloc.keys()}  # None => unlimited
    locked: set[int] = set()

    # Iteratively clamp & redistribute until stable or no capacity left
    for _ in range(len(alloc) + 2):
        # Clamp any over-cap creators and mark them locked
        changed = False
        for cid, cap in caps.items():
            if cap is not None and alloc[cid] > cap:
                alloc[cid] = cap
                locked.add(cid)
                changed = True

        assigned = sum(alloc.values())
        leftover = pool - assigned
        if leftover <= 0:
            break  # nothing to redistribute (or we already matched pool)

        # Who can still receive?
        recipients = [cid for cid in alloc.keys()
                      if cid not in locked and (caps.get(cid) is None or alloc[cid] < caps[cid])]
        if not recipients:
            # No capacity left; can't place leftover
            return alloc, leftover

        # Proportional redistribution by remaining units
        total_units = sum(max(0.0, units.get(cid, 0.0)) for cid in recipients)
        if total_units <= 0:
            # fallback: equal split
            per = leftover // len(recipients)
            rem = leftover - per * len(recipients)
            for cid in recipients:
                alloc[cid] += per
            for cid in recipients[:rem]:
                alloc[cid] += 1
            # loop again to clamp if we exceeded any caps
            continue

        # First pass: integer share
        add: Dict[int, int] = {}
        taken = 0
        for cid in recipients:
            frac = units.get(cid, 0.0) / total_units
            add_amt = int(leftover * frac)  # floor
            add[cid] = add_amt
            taken += add_amt
        # Distribute remaining pennies to top-unit recipients
        rem = leftover - taken
        order = sorted(recipients, key=lambda c: units.get(c, 0.0), reverse=True)
        for i in range(rem):
            add[order[i % len(order)]] += 1

        # Apply adds, respecting caps
        for cid in recipients:
            cap = caps.get(cid)
            new_amt = alloc[cid] + add[cid]
            if cap is not None and new_amt > cap:
                new_amt = cap
                locked.add(cid)
            if new_amt != alloc[cid]:
                alloc[cid] = new_amt
                changed = True

        if not changed:
            break  # stable

    unallocated = pool - sum(alloc.values())
    return alloc, unallocated

# -----------------------------
# RevenueSplitter
# -----------------------------
class RevenueSplitter:
    """
    Two APIs:

    1) compute_units(run_day) -> Dict[creator_id, float]
       Returns per-creator "units" for that day (after all per-video multipliers
       AND after creator-level integrity multiplier + trust/bot), no writes.

    2) run(pool_cents, run_day, payment_type="revenue_split")
       Scales the day's units to cents, applies KYC caps + redistribution,
       writes transactions (direction='inflow') and bumps users.current_balance.
    """
    def __init__(self, sb: Client, dry_run: bool = False):
        self.sb = sb
        self.dry_run = dry_run

    # ---------- compute units for a day (no DB writes) ----------
    def compute_units(self, run_day: date) -> Dict[int, float]:
        videos = load_videos(self.sb)
        day_events = load_events_for_day(self.sb, run_day)
        if not day_events:
            return {}

        # Aggregate per video for the day
        per_video_events: Dict[int, List[dict]] = defaultdict(list)
        for e in day_events:
            vid = e.get("video_id")
            if vid is not None:
                per_video_events[vid].append(e)

        # Engagement rates for quality z
        eng_rates: List[float] = []
        per_video_stats: Dict[int, dict] = {}
        for vid, evs in per_video_events.items():
            c = Counter(e["event_type"] for e in evs)
            views = c.get("view", 0)
            likes = c.get("like", 0)
            comments = c.get("comment", 0)
            shares = c.get("share", 0)
            er = 0.0 if views == 0 else (likes + comments + shares) / views
            eng_rates.append(er)
            per_video_stats[vid] = {"views": views, "likes": likes, "comments": comments, "shares": shares, "eng_rate": er}

        mu = sum(eng_rates) / len(eng_rates) if eng_rates else 0.0
        sigma = math.sqrt(sum((x - mu) ** 2 for x in eng_rates) / (len(eng_rates) - 1)) if len(eng_rates) > 1 else 0.0

        # Per-creator raw units (after per-video multipliers)
        per_creator_units: Dict[int, float] = defaultdict(float)
        for vid, stats in per_video_stats.items():
            vrow = videos.get(vid)
            if not vrow:
                continue
            cid = vrow["creator_id"]
            raw_units = (
                EVENT_WEIGHTS["view"]    * stats["views"] +
                EVENT_WEIGHTS["like"]    * stats["likes"] +
                EVENT_WEIGHTS["comment"] * stats["comments"] +
                EVENT_WEIGHTS["share"]   * stats["shares"]
            )
            q_mult = quality_multiplier(stats["eng_rate"], mu, sigma)
            ev_mult = early_kicker_mult_for_video(self.sb, vrow)
            cl_mult = cluster_penalty_mult(per_video_events[vid])
            per_creator_units[cid] += raw_units * q_mult * ev_mult * cl_mult

        if not per_creator_units:
            return {}

        # Integrity multiplier (7d window ending run_day)
        eis_start = datetime.combine(run_day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=7)
        eis_end   = datetime.combine(run_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        events_7d = load_events_between(self.sb, eis_start, eis_end)

        # Build creator stats for 7d
        creator_7d: Dict[int, dict] = defaultdict(lambda: {"views":0,"likes":0,"comments":0,"devs":set(),"ips":set()})
        video_to_creator = {vid: v["creator_id"] for vid, v in videos.items()}

        for e in events_7d:
            vid = e.get("video_id")
            if vid not in video_to_creator:
                continue
            cid = video_to_creator[vid]
            et  = e.get("event_type")
            if et == "view":      creator_7d[cid]["views"] += 1
            elif et == "like":    creator_7d[cid]["likes"] += 1
            elif et == "comment": creator_7d[cid]["comments"] += 1
            if e.get("device_id") is not None: creator_7d[cid]["devs"].add(e["device_id"])
            if e.get("ip_hash")   is not None: creator_7d[cid]["ips"].add(e["ip_hash"])

        # Apply integrity multiplier (±3%)
        units_after_integrity: Dict[int, float] = {}
        for cid, units in per_creator_units.items():
            s = creator_7d.get(cid, {"views":0,"likes":0,"comments":0,"devs":set(),"ips":set()})
            integ = integrity_multiplier_7d(
                views=s["views"],
                uniq_dev=len(s["devs"]),
                uniq_ip=len(s["ips"]),
                likes=s["likes"],
                comments=s["comments"]
            )
            units_after_integrity[cid] = units * integ

        # Apply stored creator trust score (±10%) and likely_bot hard-exclude
        users_by_id = load_users(self.sb)
        units_after_creator_score: Dict[int, float] = {}
        for cid, units in units_after_integrity.items():
            urow = users_by_id.get(cid, {}) or {}
            if PENALIZE_LIKELY_BOT and urow.get("likely_bot"):
                mult = 0.0  # hard exclude suspicious creators entirely
            else:
                mult = trust_to_mult(urow.get("creator_trust_score"))
            units_after_creator_score[cid] = units * mult

        return units_after_creator_score

    # ---------- scale units to pool, apply KYC caps, and (optionally) write ----------
    def run(self, pool_cents: int, run_day: date | None = None, payment_type: str = "revenue_split") -> List[dict]:
        run_day = run_day or datetime.now(timezone.utc).date()

        units = self.compute_units(run_day)
        total_units = sum(units.values())
        if total_units <= 0:
            raise RuntimeError(f"No eligible units for {run_day}.")

        # Initial proportional allocations
        allocations: Dict[int, int] = {
            cid: int(round(pool_cents * (u / total_units)))
            for cid, u in units.items()
            if u > 0
        }

        # Enforce KYC caps with redistribution
        allocations, unallocated = apply_kyc_caps(self.sb, allocations, units)

        # Build breakdown for return / preview
        breakdown = [{"creator_id": cid, "amount_cents": amt}
                     for cid, amt in sorted(allocations.items(), key=lambda x: x[1], reverse=True)]

        if self.dry_run:
            if unallocated > 0:
                print(f"[warn] Unallocated due to KYC caps: {unallocated} cents")
            return breakdown

        # Write transactions (+inflow) and update balances
        now_iso = datetime.now(timezone.utc).isoformat()

        rows = [
            {
                "created_at": now_iso,
                "recipient": cid,
                "amount_cents": amt,
                "status": "pending",
                "payment_type": payment_type,  # daily or decided by caller
                "direction": "inflow",
            }
            for cid, amt in allocations.items() if amt > 0
        ]

        CHUNK = 1000
        for i in range(0, len(rows), CHUNK):
            self.sb.table("transactions").insert(rows[i:i+CHUNK]).execute()

        # Update balances
        for cid, amt in allocations.items():
            cur = self.sb.table("users").select("current_balance").eq("id", cid).limit(1).execute().data
            curbal = (cur[0]["current_balance"] if cur else 0) or 0
            self.sb.table("users").update({"current_balance": curbal + amt}).eq("id", cid).execute()

        if unallocated > 0:
            print(f"[info] {unallocated} cents remained unallocated due to KYC caps.", flush=True)

        return breakdown
