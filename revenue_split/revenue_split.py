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


def _sum_int(rows, key):
    return sum(int(r.get(key, 0) or 0) for r in rows)


def _videos_in_window(sb, start: datetime, end: datetime):
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


def _eng_units(sb, vid: int, start: datetime, end: datetime) -> int:
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
    v = sum(1 for e in ev if e["event_type"] == "view")
    l = sum(1 for e in ev if e["event_type"] == "like")
    c = sum(1 for e in ev if e["event_type"] == "comment")
    r = sum(1 for e in ev if e["event_type"] == "report")
    return max(0, v + 2 * l + 5 * c - 10 * r)


def _avg_eis(sb, vid: int, start: datetime, end: datetime) -> float:
    rows = (
        sb.table("video_aggregates")
        .select("eis,window_end")
        .eq("video_id", vid)
        .gte("window_end", start.isoformat())
        .lt("window_end", end.isoformat())
        .execute()
        .data
        or []
    )
    if not rows:
        return 0.0
    vals = [float(r.get("eis") or 0.0) for r in rows]
    return float(sum(vals) / len(vals)) if vals else 0.0


def _eligible_creator(sb, cid: int) -> bool:
    u = (
        sb.table("users").select("kyc_level,creator_trust_score").eq("id", cid).single().execute().data
    )
    if not u:
        return False
    kyc = int(u.get("kyc_level") or 0)
    cts = float(u.get("creator_trust_score") or 0.0)
    return (kyc >= 2) and (cts >= 50.0)


def _likes_in_range(sb, vid: int, start: datetime, end: datetime):
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


def _first_hour_stats(sb, vid: int, start: datetime) -> Dict:
    end = start + timedelta(hours=1)
    likes = _likes_in_range(sb, vid, start, end)
    if len(likes) < 3:
        return {"cv": 0.0, "dev_div": 0.0, "ip_div": 0.0}
    # inter-arrival CV
    ts = [datetime.fromisoformat(str(x["ts"]).replace("Z", "+00:00")) for x in likes]
    intervals = [(ts[i] - ts[i - 1]).total_seconds() for i in range(1, len(ts))]
    if not intervals or sum(intervals) <= 0:
        cv = 0.0
    else:
        mean_i = sum(intervals) / len(intervals)
        cv = float(pstdev(intervals) / mean_i) if mean_i > 0 else 0.0
    devs = [x.get("device_id") for x in likes if x.get("device_id")]
    ips = [x.get("ip_hash") for x in likes if x.get("ip_hash")]
    dev_div = (len(set(devs)) / len(likes)) if devs else 0.5
    ip_div = (len(set(ips)) / len(likes)) if ips else 0.5
    return {"cv": cv, "dev_div": float(dev_div), "ip_div": float(ip_div)}


def _cluster_penalty(sb, vid: int, start: datetime, end: datetime) -> Tuple[float, Dict]:
    likes = _likes_in_range(sb, vid, start, end)
    if not likes:
        return 1.0, {"users_per_device": None, "users_per_ip": None}
    dev_users, ip_users = {}, {}
    for l in likes:
        uid = l.get("user_id")
        d = l.get("device_id")
        ip = l.get("ip_hash")
        if d:
            dev_users.setdefault(d, set()).add(uid)
        if ip:
            ip_users.setdefault(ip, set()).add(uid)
    upd = (
        (sum(len(s) for s in dev_users.values()) / max(1, len(dev_users))) if dev_users else 0.0
    )
    upi = (sum(len(s) for s in ip_users.values()) / max(1, len(ip_users))) if ip_users else 0.0
    excess_device = max(0.0, upd - 1.5)
    excess_ip = max(0.0, upi - 2.0)
    penalty = clip(1.0 - 0.05 * max(excess_device, excess_ip), 0.85, 1.0)
    return float(penalty), {
        "users_per_device": upd or None,
        "users_per_ip": upi or None,
        "excess_device": excess_device,
        "excess_ip": excess_ip,
    }


def _creator_7d_avg_eis(sb, cid: int, asof: datetime) -> float:
    # mean of videos.eis_current for creator’s videos updated within last 7d
    since = asof - timedelta(days=7)
    vids = (
        sb.table("videos")
        .select("eis_current,eis_updated_at,creator_id")
        .eq("creator_id", cid)
        .execute()
        .data
        or []
    )
    vals = []
    for v in vids:
        t = v.get("eis_updated_at")
        if not t:
            continue
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if dt >= since:
            vals.append(float(v.get("eis_current") or 0.0))
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
    sb = get_supabase_client(prefer_service=True)

    R_gross = int(gross_revenue_cents)
    taxes = int(taxes_cents)
    store = int(app_store_fees_cents)
    refunds = int(refunds_cents)
    R_net = max(0, R_gross - taxes - store - refunds)

    # Base pool and margin guardrail
    pool_base = int(pool_pct * R_net)
    pool_max_by_margin = max(0, R_net - costs_est_cents - int(margin_target * R_gross))
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
        eis_avg = _avg_eis(sb, vid, start, end)
        m = (clip(eis_avg, 0.0, 100.0) / 100.0) ** gamma
        vu = eng * m

        # (3) Early-Velocity Kicker in first hour
        fv = _first_hour_stats(sb, vid, start)
        velocity_kicker = 1.05 if (fv["cv"] >= 1.0 and max(fv["dev_div"], fv["ip_div"]) >= 0.8) else 1.00
        vu *= velocity_kicker

        # (4) Cluster Penalty Escalator over full window
        cp_mult, cp_det = _cluster_penalty(sb, vid, start, end)
        vu *= cp_mult

        v_metrics.append(
            {
                "video_id": vid,
                "creator_id": cid,
                "eng_units": eng,
                "eis_avg": eis_avg,
                "vu": vu,
                "meta": {
                    "velocity": fv,
                    "cluster_penalty": cp_det | {"multiplier": cp_mult},
                    "velocity_kicker": velocity_kicker,
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
        sb.table("video_rev_shares").insert(vrs_rows).execute()

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

    # Write creator payouts/reserves to transactions
    payouts = []
    hold_until = (now.replace(microsecond=0) + timedelta(days=hold_days)).isoformat()
    for cid, alloc_c in scaled.items():
        platform_fee = int(platform_fee_pct * alloc_c)
        reserve = int(risk_reserve_pct * alloc_c)
        pay_now = alloc_c - platform_fee - reserve
        if pay_now < min_payout_cents:
            reserve += pay_now
            pay_now = 0
        if pay_now > 0:
            sb.table("transactions").insert(
                {
                    "user_id": cid,
                    "type": "payout",
                    "amount_cents": pay_now,
                    "status": "pending",
                    "hold_until": now.isoformat(),
                }
            ).execute()
        if reserve > 0:
            sb.table("transactions").insert(
                {
                    "user_id": cid,
                    "type": "reserve",
                    "amount_cents": reserve,
                    "status": "on_hold",
                    "hold_until": hold_until,
                }
            ).execute()
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

