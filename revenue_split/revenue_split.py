# revenue_split/revenue_split.py
from __future__ import annotations

import os
import math
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Optional

from supabase import create_client, Client

# -----------------------------
# Knobs
# -----------------------------
QUALITY_Z_TO_PCT   = 0.01     # z * 1% → clamped below
QUALITY_CLAMP_PCT  = 0.02     # ±2%

INTEGRITY_RANGE_PCT = 0.03    # ±3% mapped from 0..1
EARLY_WINDOW_HRS    = 2
EARLY_KICKER_MULT   = 1.05
EARLY_MIN_VIEWS     = 50
EARLY_DEV_RATIO     = 0.50
EARLY_IP_RATIO      = 0.40

CLUSTER_START_SHARE = 0.20
CLUSTER_MAX_PENALTY = 0.30
CLUSTER_RAMP        = 2.0

EVENT_WEIGHTS = {"view": 1, "like": 3, "comment": 5, "share": 8}
PAGE_SIZE = 10000

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
    # Map 0..1 → 1±3%
    return (1.0 - INTEGRITY_RANGE_PCT) + (score_0_1 * 2 * INTEGRITY_RANGE_PCT)

def early_kicker_mult_for_video(sb: Client, video_row: dict) -> float:
    """
    Compute early velocity in the first 2 hours AFTER creation (global time window),
    not just within the run_day. This crosses day boundaries if needed.
    """
    created_at = iso_to_dt(video_row["created_at"])
    window_end = created_at + timedelta(hours=EARLY_WINDOW_HRS)
    evs = load_events_between(sb, created_at, window_end)

    # Filter to this video
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

# -----------------------------
# RevenueSplitter
# -----------------------------
class RevenueSplitter:
    """
    Two APIs:

    1) compute_units(run_day) -> Dict[creator_id, float]
       Returns per-creator "units" for that day (after all per-video multipliers
       AND after creator-level integrity multiplier), without rounding/writing.

    2) run(pool_cents, run_day, payment_type="revenue_split", dry_run=False)
       Scales the day's units to cents, optionally writes transactions with
       direction='inflow' and bumps users.current_balance.
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
            if et == "view":    creator_7d[cid]["views"] += 1
            elif et == "like":  creator_7d[cid]["likes"] += 1
            elif et == "comment": creator_7d[cid]["comments"] += 1
            if e.get("device_id") is not None: creator_7d[cid]["devs"].add(e["device_id"])
            if e.get("ip_hash") is not None:   creator_7d[cid]["ips"].add(e["ip_hash"])

        # Apply integrity multiplier
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

        return units_after_integrity

    # ---------- scale units to pool and (optionally) write ----------
    def run(self, pool_cents: int, run_day: Optional[date] = None, payment_type: str = "revenue_split") -> List[dict]:
        run_day = run_day or datetime.now(timezone.utc).date()

        units = self.compute_units(run_day)
        total_units = sum(units.values())
        if total_units <= 0:
            raise RuntimeError(f"No eligible units for {run_day}.")

        # Scale once; round to cents
        allocations: Dict[int, int] = {
            cid: int(round(pool_cents * (u / total_units)))
            for cid, u in units.items()
            if u > 0
        }
        breakdown = [{"creator_id": cid, "amount_cents": amt} for cid, amt in sorted(allocations.items(), key=lambda x: x[1], reverse=True)]

        if self.dry_run:
            return breakdown

        # Write transactions (+inflow) and update balances
        now_iso = datetime.now(timezone.utc).isoformat()

        # Insert in chunks
        rows = [
            {
                "created_at": now_iso,
                "recipient": cid,
                "amount_cents": amt,
                "status": "pending",
                "payment_type": payment_type,  # daily or monthly caller decides
                "direction": "inflow",         # <-- NEW: enum
            }
            for cid, amt in allocations.items()
            if amt > 0
        ]

        CHUNK = 1000
        for i in range(0, len(rows), CHUNK):
            self.sb.table("transactions").insert(rows[i:i+CHUNK]).execute()

        # Update balances
        for cid, amt in allocations.items():
            cur = self.sb.table("users").select("current_balance").eq("id", cid).limit(1).execute().data
            curbal = (cur[0]["current_balance"] if cur else 0) or 0
            self.sb.table("users").update({"current_balance": curbal + amt}).eq("id", cid).execute()

        return breakdown


