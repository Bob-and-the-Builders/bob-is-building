# revenue_split.py
from __future__ import annotations

import os
import math
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Optional

from supabase import create_client, Client

# -----------------------------
# Config knobs (easy to tweak)
# -----------------------------
QUALITY_Z_TO_PCT   = 0.01    # z * 0.01  -> ±2% clamp below
QUALITY_CLAMP_PCT  = 0.02    # max +/- 2%

INTEGRITY_RANGE_PCT = 0.03   # ±3% mapped from 0..1 score
EARLY_WINDOW_HRS    = 2
EARLY_KICKER_MULT   = 1.05
EARLY_MIN_VIEWS     = 50
EARLY_DEV_RATIO     = 0.50
EARLY_IP_RATIO      = 0.40

CLUSTER_START_SHARE = 0.20   # penalty starts after this top-cluster share
CLUSTER_MAX_PENALTY = 0.30   # up to -30% (floor multiplier 0.7)
CLUSTER_RAMP        = 2.0    # how fast the penalty ramps

EVENT_WEIGHTS = {"view": 1, "like": 3, "comment": 5, "share": 8}
PAGE_SIZE = 10000            # PostgREST pagination

# -----------------------------
# Helper: Supabase client
# -----------------------------
def make_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]  # needs write perms
    return create_client(url, key)

# -----------------------------
# Utilities
# -----------------------------
def daterange_utc(d: date) -> Tuple[str, str]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end   = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()

def fetch_all(table: str, builder_fn, page_size=PAGE_SIZE) -> List[dict]:
    """Generic pagination helper. builder_fn(client.table(table)) must return a query with filters applied."""
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

# -----------------------------
# Load data
# -----------------------------
def load_events_for_day(sb: Client, run_day: date) -> List[dict]:
    start, end = daterange_utc(run_day)
    def builder():
        return (
            sb.table("event")
              .select("*")
              .gte("ts", start)
              .lt("ts", end)
        )
    return fetch_all("event", lambda: builder())

def load_events_between(sb: Client, start: datetime, end: datetime) -> List[dict]:
    def builder():
        return sb.table("event").select("*").gte("ts", start.isoformat()).lt("ts", end.isoformat())
    return fetch_all("event", lambda: builder())

def load_videos(sb: Client) -> Dict[int, dict]:
    rows = fetch_all("videos", lambda: sb.table("videos").select("*"))
    return {r["id"]: r for r in rows}

def load_users(sb: Client) -> Dict[int, dict]:
    rows = fetch_all("users", lambda: sb.table("users").select("*"))
    return {r["id"]: r for r in rows}

# -----------------------------
# Safety: idempotency per day
# -----------------------------
def already_paid_today(sb: Client, run_day: date) -> bool:
    start, end = daterange_utc(run_day)
    # We tag payment_type = 'revenue_split' and rely on created_at date
    res = (
        sb.table("transactions")
          .select("id")
          .eq("payment_type", "revenue_split")
          .gte("created_at", start)
          .lt("created_at", end)
          .limit(1)
          .execute()
    )
    return bool(res.data)

# -----------------------------
# Core metrics (Python only)
# -----------------------------
def zscore_series(values: List[float]) -> Dict[int, float]:
    if not values:
        return {}
    n = len(values)
    mu = sum(values) / n
    var = sum((x - mu) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    sigma = math.sqrt(var)
    zs: Dict[int, float] = {}
    for i, x in enumerate(values):
        zs[i] = 0.0 if sigma == 0 else (x - mu) / sigma
    return zs

def clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))

def quality_multiplier(engagement_rate: float, mu: float, sigma: float) -> float:
    if sigma == 0:
        return 1.0
    z = (engagement_rate - mu) / sigma
    nudged = z * QUALITY_Z_TO_PCT
    return 1.0 + clamp(nudged, -QUALITY_CLAMP_PCT, QUALITY_CLAMP_PCT)

def integrity_multiplier_7d(views: int, uniq_dev: int, uniq_ip: int, likes: int, comments: int) -> float:
    # components 0..1
    dev_div = min(1.0, 5.0 * (uniq_dev / max(1.0, views)))
    ip_div  = min(1.0, 5.0 * (uniq_ip  / max(1.0, views)))
    eng_h   = min(1.0, 10.0 * ((likes + comments) / max(1.0, views)))
    score_0_1 = (dev_div + ip_div + eng_h) / 3.0
    # map 0..1 -> 1-3% bonus range (0->-3%, 0.5->0, 1->+3%)
    return (1.0 - INTEGRITY_RANGE_PCT) + (score_0_1 * 2 * INTEGRITY_RANGE_PCT)

def early_kicker_mult(video_events: List[dict], video_created_at: datetime) -> float:
    window_end = video_created_at + timedelta(hours=EARLY_WINDOW_HRS)
    early = [e for e in video_events if video_created_at <= iso_to_dt(e["ts"]) < window_end]
    if not early:
        return 1.0
    views = sum(1 for e in early if e["event_type"] == "view")
    if views < EARLY_MIN_VIEWS:
        return 1.0
    uniq_dev = len({e.get("device_id") for e in early})
    uniq_ip  = len({e.get("ip_hash") for e in early})
    if uniq_dev >= EARLY_DEV_RATIO * views and uniq_ip >= EARLY_IP_RATIO * views:
        return EARLY_KICKER_MULT
    return 1.0

def cluster_penalty_mult(day_events_for_video: List[dict]) -> float:
    views = [e for e in day_events_for_video if e["event_type"] == "view"]
    if not views:
        return 1.0
    # top share by device / IP
    dev_counts = Counter([e.get("device_id") for e in views if e.get("device_id") is not None])
    ip_counts  = Counter([e.get("ip_hash")   for e in views if e.get("ip_hash") is not None])

    def top_share(cnt: Counter) -> float:
        total = sum(cnt.values())
        return 0.0 if total == 0 else (max(cnt.values()) / total)

    ts = max(top_share(dev_counts), top_share(ip_counts))
    if ts <= CLUSTER_START_SHARE:
        return 1.0
    # linear ramp after threshold, capped
    penalty = CLUSTER_RAMP * (ts - CLUSTER_START_SHARE)  # 0..∞
    return max(1.0 - CLUSTER_MAX_PENALTY, 1.0 - penalty)

def iso_to_dt(s: str) -> datetime:
    # Supabase returns ISO8601 (with/without Z); ensure timezone-aware UTC
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# -----------------------------
# Main splitter
# -----------------------------
class RevenueSplitter:
    def __init__(self, sb: Client):
        self.sb = sb

    def run(self, pool_cents: int, run_day: Optional[date] = None) -> List[dict]:
        run_day = run_day or datetime.now(timezone.utc).date()

        # Idempotency check (no SQL tables required)
        if already_paid_today(self.sb, run_day):
            raise RuntimeError(f"Payout for {run_day} already exists (transactions.payment_type='revenue_split').")

        # Load core datasets
        videos = load_videos(self.sb)          # id -> row
        users  = load_users(self.sb)           # id -> row

        day_events = load_events_for_day(self.sb, run_day)
        if not day_events:
            raise RuntimeError(f"No events found for {run_day}")

        # Build per-video aggregates for the day
        per_video_events: Dict[int, List[dict]] = defaultdict(list)
        for e in day_events:
            if e.get("video_id") is None:
                continue
            per_video_events[e["video_id"]].append(e)

        # Engagement rate prep (for quality z-score)
        eng_rates: List[float] = []
        video_keys: List[int] = []

        per_video_stats = {}
        for vid, evs in per_video_events.items():
            counts = Counter(e["event_type"] for e in evs)
            views = counts.get("view", 0)
            likes = counts.get("like", 0)
            comments = counts.get("comment", 0)
            shares = counts.get("share", 0)
            er = 0.0 if views == 0 else (likes + comments + shares) / views
            eng_rates.append(er)
            video_keys.append(vid)
            per_video_stats[vid] = {"views": views, "likes": likes, "comments": comments, "shares": shares, "eng_rate": er}

        # Global stats for quality z
        if len(eng_rates) > 1:
            mu = sum(eng_rates) / len(eng_rates)
            var = sum((x - mu) ** 2 for x in eng_rates) / (len(eng_rates) - 1)
            sigma = math.sqrt(var)
        else:
            mu = eng_rates[0] if eng_rates else 0.0
            sigma = 0.0

        # Compute per-video final "view units"
        per_creator_units: Dict[int, float] = defaultdict(float)

        for vid, stats in per_video_stats.items():
            vrow = videos.get(vid)
            if not vrow:
                continue
            creator_id = vrow["creator_id"]
            # raw units
            raw_units = (
                EVENT_WEIGHTS["view"]    * stats["views"] +
                EVENT_WEIGHTS["like"]    * stats["likes"] +
                EVENT_WEIGHTS["comment"] * stats["comments"] +
                EVENT_WEIGHTS["share"]   * stats["shares"]
            )

            q_mult = quality_multiplier(stats["eng_rate"], mu, sigma)
            ev_mult = early_kicker_mult(
                video_events=load_events_between(
                    self.sb,
                    iso_to_dt(vrow["created_at"]),
                    iso_to_dt(vrow["created_at"]) + timedelta(hours=EARLY_WINDOW_HRS)
                ),
                video_created_at=iso_to_dt(vrow["created_at"])
            )
            cl_mult = cluster_penalty_mult(per_video_events[vid])

            view_units = raw_units * q_mult * ev_mult * cl_mult
            per_creator_units[creator_id] += view_units

        total_units = sum(per_creator_units.values())
        if total_units <= 0:
            raise RuntimeError("Total view units is zero; nothing to allocate.")

        # Integrity multiplier at creator level (7-day window ending run_day)
        eis_start = datetime.combine(run_day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=7)
        eis_end   = datetime.combine(run_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        events_7d = load_events_between(self.sb, eis_start, eis_end)

        creator_7d: Dict[int, dict] = defaultdict(lambda: {"views":0,"likes":0,"comments":0,"devs":set(),"ips":set()})
        # need creator per event -> via videos
        for e in events_7d:
            vid = e.get("video_id")
            if vid is None or vid not in videos:
                continue
            cid = videos[vid]["creator_id"]
            et = e["event_type"]
            if et == "view":
                creator_7d[cid]["views"] += 1
            elif et == "like":
                creator_7d[cid]["likes"] += 1
            elif et == "comment":
                creator_7d[cid]["comments"] += 1
            # diversity sets
            if e.get("device_id") is not None:
                creator_7d[cid]["devs"].add(e["device_id"])
            if e.get("ip_hash") is not None:
                creator_7d[cid]["ips"].add(e["ip_hash"])

        creator_integrity_mult: Dict[int, float] = {}
        for cid, s in creator_7d.items():
            creator_integrity_mult[cid] = integrity_multiplier_7d(
                views=s["views"],
                uniq_dev=len(s["devs"]),
                uniq_ip=len(s["ips"]),
                likes=s["likes"],
                comments=s["comments"]
            )

        # Final amounts
        allocations: Dict[int, int] = {}  # cents
        for cid, units in per_creator_units.items():
            base_share = units / total_units
            integ = creator_integrity_mult.get(cid, 1.0)
            amount = int(round(pool_cents * base_share * integ))
            if amount > 0:
                allocations[cid] = amount

        if not allocations:
            raise RuntimeError("No positive allocations computed.")

        # Write transactions + update balances atomically-ish (best-effort, in order)
        # 1) insert transactions
        now_iso = datetime.now(timezone.utc).isoformat()
        tx_rows = [
            {
                "created_at": now_iso,
                "recipient": cid,
                "amount_cents": amt,
                "status": "pending",
                "payment_type": "revenue_split"
            }
            for cid, amt in allocations.items()
        ]
        # Insert in chunks to be safe with payload size
        CHUNK = 1000
        for i in range(0, len(tx_rows), CHUNK):
            self.sb.table("transactions").insert(tx_rows[i:i+CHUNK]).execute()

        # 2) update user balances
        for cid, amt in allocations.items():
            # current_balance might be null
            # Fetch current (cheap) then update
            cur = self.sb.table("users").select("current_balance").eq("id", cid).limit(1).execute().data
            curbal = (cur[0]["current_balance"] if cur else 0) or 0
            newbal = curbal + amt
            self.sb.table("users").update({"current_balance": newbal}).eq("id", cid).execute()

        # Return breakdown (sorted)
        out = [{"creator_id": cid, "amount_cents": amt} for cid, amt in sorted(allocations.items(), key=lambda x: x[1], reverse=True)]
        return out


# -----------------------------
# CLI-style entry point
# -----------------------------
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Distribute daily shorts revenue pool")
    p.add_argument("--pool-cents", type=int, required=True, help="Total pool to distribute in cents")
    p.add_argument("--run-day", type=str, default=None, help="YYYY-MM-DD; defaults to today (UTC)")
    args = p.parse_args()

    run_day = date.fromisoformat(args.run_day) if args.run_day else None
    sb = make_client()
    splitter = RevenueSplitter(sb)
    breakdown = splitter.run(pool_cents=args.pool_cents, run_day=run_day)
    print("Payouts:", breakdown)
