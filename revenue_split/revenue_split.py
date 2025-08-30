"""
Revenue split allocation logic for short-form videos.

This module computes an allocation for a given revenue window with the
following key properties:

- Pool sizing respects margin guardrails.
- Video-level weights are computed from observed engagement volume and the
  Viewer Activity (VA) metrics (EIS and component scores) produced by
  `viewer_activity`.
- Creator-level integrity streaks are rewarded modestly, then re-normalized
  to preserve the pool size.

Integration with viewer_activity
--------------------------------
We rely on the viewer_activity pipeline to compute and persist per-window
metrics into `video_aggregates` and to maintain `videos.eis_current`.
For each video in the window, we read:

- `eis` (Engagement Integrity Score, 0..100)
- `like_integrity` (0..100)
- `report_credibility` (0..100)
- `authentic_engagement` (0..100)

If aggregates are missing for the window, we invoke
`viewer_activity.analyzer.analyze_window(video_id, start, end)` to compute and
persist them before proceeding.

Error handling
--------------
External calls to Supabase are wrapped in small helpers and exceptions are
raised with contextual messages to ease troubleshooting. All numeric inputs
are validated and clamped to safe ranges where applicable.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from math import isfinite
from statistics import pstdev

# Prefer importing a provided helper, but fall back to local client creation
try:
    from supabase_conn import get_supabase_client  # type: ignore
except Exception:
    # Back-compat shim if repo doesn't expose get_supabase_client(prefer_service=True)
    # Uses service role key if available; falls back to anon (not recommended for writes).
    import os
    from supabase import create_client

    def get_supabase_client(prefer_service: bool = True):  # type: ignore
        url = os.environ.get("SUPABASE_URL")
        key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            if prefer_service
            else os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SECRET")
        )
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL or service key in environment")
        return create_client(url, key)


UTC = timezone.utc
clip = lambda x, lo, hi: float(max(lo, min(hi, x)))

# Import viewer_activity analyzer to compute aggregates on-demand when missing.
# Try as package import; on failure, add repo paths and retry to support
# non-installed, local usage.
va_analyze_window = None  # type: ignore
try:
    from viewer_activity.analyzer import analyze_window as va_analyze_window  # type: ignore
except Exception:  # pragma: no cover - soft dependency
    try:
        import os, sys
        this_dir = os.path.dirname(__file__)
        repo_root = os.path.abspath(os.path.join(this_dir, os.pardir))
        va_dir = os.path.join(repo_root, "viewer_activity")
        for p in (repo_root, va_dir):
            if p not in sys.path:
                sys.path.insert(0, p)
        from viewer_activity.analyzer import analyze_window as va_analyze_window  # type: ignore
    except Exception:
        va_analyze_window = None  # type: ignore


def _sum_int(rows, key):
    return sum(int(r.get(key, 0) or 0) for r in rows)


def _videos_in_window(sb, start: datetime, end: datetime) -> List[Dict]:
    """Return distinct videos that have any events in [start, end).

    Returns a list of dicts with keys: `id`, `creator_id`.
    Raises RuntimeError with context on Supabase failures.
    """
    try:
        ev = (
            sb.table("event")
            .select("video_id")
            .gte("ts", start.isoformat())
            .lt("ts", end.isoformat())
            .execute()
            .data
            or []
        )
        ids = sorted({int(r["video_id"]) for r in ev})
        if not ids:
            return []
        return (
            sb.table("videos").select("id,creator_id").in_("id", ids).execute().data or []
        )
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to fetch videos for window {start}..{end}: {e}")


def _eng_units(sb, vid: int, start: datetime, end: datetime) -> int:
    """Compute a simple engagement volume proxy from raw events.

    EngUnits = 1*views + 2*likes + 5*comments - 10*reports (clamped ≥ 0)
    """
    try:
        ev = (
            sb.table("event")
            .select("event_type")
            .eq("video_id", vid)
            .gte("ts", start.isoformat())
            .lt("ts", end.isoformat())
            .execute()
            .data
            or []
        )
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to fetch events for video {vid}: {e}")
    v = sum(1 for e in ev if e.get("event_type") == "view")
    l = sum(1 for e in ev if e.get("event_type") == "like")
    c = sum(1 for e in ev if e.get("event_type") == "comment")
    r = sum(1 for e in ev if e.get("event_type") == "report")
    return max(0, v + 2 * l + 5 * c - 10 * r)


def _va_avg_metrics(sb, vid: int, start: datetime, end: datetime) -> Dict[str, float]:
    """Average viewer_activity metrics for a video over [start, end).

    Returns a dict with keys: `eis_avg`, `like_integrity_avg`,
    `report_credibility_avg`, `authentic_engagement_avg`.

    If aggregates are missing and `viewer_activity.analyzer` is available,
    computes them on-demand.
    """
    def _fetch() -> List[Dict]:
        return (
            sb.table("video_aggregates")
            .select("eis,like_integrity,report_credibility,authentic_engagement,window_start,window_end")
            .eq("video_id", vid)
            .gte("window_start", start.isoformat())
            .lt("window_end", end.isoformat())
            .execute()
            .data
            or []
        )

    try:
        rows = _fetch()
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to fetch video_aggregates for video {vid}: {e}")

    if not rows and va_analyze_window is not None:
        try:  # compute on-demand once, then refetch
            va_analyze_window(vid, start, end)
            rows = _fetch()
        except Exception:
            rows = []

    if not rows:
        return {
            "eis_avg": 0.0,
            "like_integrity_avg": 50.0,
            "report_credibility_avg": 90.0,
            "authentic_engagement_avg": 50.0,
        }

    def _avg(key: str) -> float:
        vals = [float(r.get(key) or 0.0) for r in rows]
        return float(sum(vals) / len(vals)) if vals else 0.0

    return {
        "eis_avg": _avg("eis"),
        "like_integrity_avg": _avg("like_integrity"),
        "report_credibility_avg": _avg("report_credibility"),
        "authentic_engagement_avg": _avg("authentic_engagement"),
    }


def _eligible_creator(sb, cid: int) -> bool:
    """Eligibility gate for payouts: KYC level and creator trust baseline."""
    try:
        u = (
            sb.table("users").select("kyc_level,creator_trust_score").eq("id", cid).single().execute().data
        )
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to load user {cid} for eligibility: {e}")
    if not u:
        return False
    kyc = int(u.get("kyc_level") or 0)
    cts = float(u.get("creator_trust_score") or 0.0)
    return (kyc >= 2) and (cts >= 50.0)


def _likes_in_range(sb, vid: int, start: datetime, end: datetime) -> List[Dict]:
    """Fetch likes for diagnostics; not used in weighting anymore.

    Kept for potential future audits; current allocation relies on
    viewer_activity's integrity components instead.
    """
    try:
        return (
            sb.table("event")
            .select("ts,device_id,ip_hash,user_id")
            .eq("video_id", vid)
            .eq("event_type", "like")
            .gte("ts", start.isoformat())
            .lt("ts", end.isoformat())
            .order("ts")
            .execute()
            .data
            or []
        )
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to fetch likes for video {vid}: {e}")


def _creator_7d_avg_eis(sb, cid: int, asof: datetime) -> float:
    """Average of `videos.eis_current` for creator in the last 7 days."""
    since = asof - timedelta(days=7)
    try:
        vids = (
            sb.table("videos")
            .select("eis_current,eis_updated_at,creator_id")
            .eq("creator_id", cid)
            .execute()
            .data
            or []
        )
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to load creator videos for {cid}: {e}")
    vals: List[float] = []
    for v in vids:
        t = v.get("eis_updated_at")
        if not t:
            continue
        try:
            dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt >= since:
            try:
                vals.append(float(v.get("eis_current") or 0.0))
            except Exception:
                pass
    return float(sum(vals) / len(vals)) if vals else 0.0


def finalize_revenue_window(
    start: datetime,
    end: datetime,
    *,
    gross_revenue_cents: int,
    taxes_cents: int,
    app_store_fees_cents: int,
    refunds_cents: int,
    pool_pct: float = 0.45,
    margin_target: float = 0.60,
    risk_reserve_pct: float = 0.10,
    platform_fee_pct: float = 0.10,
    costs_est_cents: int = 0,
    gamma: float = 2.0,
    min_payout_cents: int = 1000,
    hold_days: int = 14,
) -> Dict:
    """Finalize a revenue window and persist allocations.

    Inputs use UTC datetimes for the window and accounting figures in cents.
    The creator pool is sized from net revenue subject to a margin target.

    Video weights combine a volume proxy (EngUnits) and the VA EIS: `VU =
    EngUnits * (EIS/100)^gamma * integrity_mod`, where `integrity_mod` is a
    small multiplier derived from viewer_activity component scores
    (like_integrity and report_credibility) to reward clean engagement.

    Returns a dict with `revenue_window`, `video_rev_shares`, and
    `creator_payouts` as echoed from inserts.
    """
    sb = get_supabase_client(prefer_service=True)

    if start.tzinfo is None or end.tzinfo is None:
        # Attach UTC if naive to avoid window leakage
        start = start.replace(tzinfo=UTC)
        end = end.replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must be before end")

    R_gross = max(0, int(gross_revenue_cents))
    taxes = max(0, int(taxes_cents))
    store = max(0, int(app_store_fees_cents))
    refunds = max(0, int(refunds_cents))
    R_net = max(0, R_gross - taxes - store - refunds)

    # Base pool and margin guardrail
    pool_base = int(float(pool_pct) * R_net)
    pool_max_by_margin = max(0, R_net - int(costs_est_cents) - int(float(margin_target) * R_gross))
    CreatorPool = min(pool_base, pool_max_by_margin)

    # Collect eligible videos with EngUnits, EIS, and VU (apply 2 refinements at video level)
    vids = _videos_in_window(sb, start, end)
    v_metrics = []
    for v in vids:
        vid = int(v["id"])
        cid = int(v["creator_id"])
        if not _eligible_creator(sb, cid):
            continue
        eng = _eng_units(sb, vid, start, end)
        if eng == 0:
            continue
        va = _va_avg_metrics(sb, vid, start, end)
        eis_avg = va["eis_avg"]
        m = (clip(eis_avg, 0.0, 100.0) / 100.0) ** float(gamma)
        # Integrity modifier uses viewer_activity component scores
        li = clip(va.get("like_integrity_avg", 50.0), 0.0, 100.0) / 100.0
        rc = clip(va.get("report_credibility_avg", 90.0), 0.0, 100.0) / 100.0
        integrity_mod = clip(0.85 + 0.15 * (li * rc), 0.85, 1.0)
        vu = eng * m * integrity_mod

        v_metrics.append(
            {
                "video_id": vid,
                "creator_id": cid,
                "eng_units": eng,
                "eis_avg": eis_avg,
                "vu": float(vu),
                "meta": {
                    "viewer_activity": {
                        "eis_avg": eis_avg,
                        "like_integrity_avg": va.get("like_integrity_avg"),
                        "report_credibility_avg": va.get("report_credibility_avg"),
                        "authentic_engagement_avg": va.get("authentic_engagement_avg"),
                        "integrity_mod": integrity_mod,
                        "gamma": float(gamma),
                    }
                },
            }
        )

    # If nothing eligible, record an empty window and exit
    if not v_metrics:
        win = (
            sb.table("revenue_windows")
            .insert(
                {
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "gross_revenue_cents": R_gross,
                    "taxes_cents": taxes,
                    "app_store_fees_cents": store,
                    "refunds_cents": refunds,
                    "pool_pct": pool_pct,
                    "margin_target": margin_target,
                    "risk_reserve_pct": risk_reserve_pct,
                    "platform_fee_pct": platform_fee_pct,
                    "costs_est_cents": costs_est_cents,
                    "creator_pool_cents": 0,
                    "meta": {"note": "no eligible videos"},
                }
            )
            .execute()
            .data
            or [None]
        )[0]
        return {"revenue_window": win, "video_rev_shares": [], "creator_payouts": []}

    # (1) Quality-Indexed Pool: ±2% by window avg EIS, bounded by margin guardrail
    # weight EIS by EngUnits to reflect volume+quality
    total_eng = sum(vm["eng_units"] for vm in v_metrics) or 1
    avg_eis_platform = sum(vm["eis_avg"] * (vm["eng_units"] / total_eng) for vm in v_metrics)
    q_adj = clip((avg_eis_platform - 60.0) / 400.0, -0.02, +0.02)  # ±2%
    CreatorPool = min(pool_max_by_margin, int(CreatorPool * (1.0 + q_adj)))

    # Insert revenue_window
    try:
        win = (
            sb.table("revenue_windows")
            .insert(
                {
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "gross_revenue_cents": R_gross,
                    "taxes_cents": taxes,
                    "app_store_fees_cents": store,
                    "refunds_cents": refunds,
                    "pool_pct": pool_pct,
                    "margin_target": margin_target,
                    "risk_reserve_pct": risk_reserve_pct,
                    "platform_fee_pct": platform_fee_pct,
                    "costs_est_cents": costs_est_cents,
                    "creator_pool_cents": CreatorPool,
                    "meta": {"avg_eis_platform": avg_eis_platform, "q_adj": q_adj},
                }
            )
            .execute()
            .data
            or [None]
        )[0]
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to insert revenue_window: {e}")
    win_id = int(win["id"])

    # Normalize VU -> shares within CreatorPool
    vu_total = sum(vm["vu"] for vm in v_metrics) or 1.0
    vrs_rows = []
    alloc_by_creator: Dict[int, int] = {}
    for vm in v_metrics:
        share = float(vm["vu"] / vu_total)
        alloc = int(share * CreatorPool)
        vrs_rows.append(
            {
                "revenue_window_id": win_id,
                "video_id": vm["video_id"],
                "eng_units": vm["eng_units"],
                "eis_avg": vm["eis_avg"],
                "vu": vm["vu"],
                "share_pct": share,
                "allocated_cents": alloc,
                "meta": vm["meta"],
            }
        )
        alloc_by_creator[vm["creator_id"]] = alloc_by_creator.get(vm["creator_id"], 0) + alloc

    if vrs_rows:
        try:
            sb.table("video_rev_shares").insert(vrs_rows).execute()
        except Exception as e:  # pragma: no cover - external I/O
            raise RuntimeError(f"Failed to insert video_rev_shares: {e}")

    # (2) Integrity Streak Bonus at creator level (±3%), then re-normalize to pool
    now = datetime.now(UTC)
    bonuses: Dict[int, float] = {}
    pre_sum = sum(alloc_by_creator.values()) or 1
    # apply ±3% by 7-day avg EIS
    for cid, alloc in alloc_by_creator.items():
        e7 = _creator_7d_avg_eis(sb, cid, now)
        mult = 1.03 if e7 >= 70.0 else (0.97 if e7 <= 40.0 else 1.00)
        bonuses[cid] = mult
    # scale creator allocations by multiplier
    scaled = {cid: int(alloc_by_creator[cid] * bonuses[cid]) for cid in alloc_by_creator}
    scaled_sum = sum(scaled.values()) or 1
    # re-normalize to CreatorPool to preserve margin
    factor = CreatorPool / scaled_sum
    for cid in scaled:
        scaled[cid] = int(scaled[cid] * factor)

    # Write creator payouts/reserves to transactions (schema: recipient, amount_cents, status, payment_type)
    payouts = []
    for cid, alloc_c in scaled.items():
        platform_fee = int(float(platform_fee_pct) * alloc_c)
        reserve = int(float(risk_reserve_pct) * alloc_c)
        pay_now = alloc_c - platform_fee - reserve
        if pay_now < min_payout_cents:
            reserve += pay_now
            pay_now = 0
        try:
            if pay_now > 0:
                sb.table("transactions").insert(
                    {
                        "recipient": cid,
                        "payment_type": "payout",
                        "amount_cents": pay_now,
                        "status": "pending",
                    }
                ).execute()
            if reserve > 0:
                sb.table("transactions").insert(
                    {
                        "recipient": cid,
                        "payment_type": "reserve",
                        "amount_cents": reserve,
                        "status": "on_hold",
                    }
                ).execute()
        except Exception as e:  # pragma: no cover - external I/O
            raise RuntimeError(f"Failed to insert transactions for creator {cid}: {e}")
        payouts.append(
            {
                "creator_id": cid,
                "alloc_cents": alloc_c,
                "pay_now_cents": pay_now,
                "platform_fee_cents": platform_fee,
                "reserve_cents": reserve,
                "bonus_mult": bonuses[cid],
            }
        )

    return {"revenue_window": win, "video_rev_shares": vrs_rows, "creator_payouts": payouts}
