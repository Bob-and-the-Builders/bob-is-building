# revenue_split/revenue_split_monthly.py
from __future__ import annotations
import os
import sys
import csv
import calendar
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict

# Robust import (module or script)
try:
    from revenue_split.revenue_split import RevenueSplitter, make_client, apply_kyc_caps
except ModuleNotFoundError:
    sys.path.append(os.path.dirname(__file__))
    from revenue_split import RevenueSplitter, make_client, apply_kyc_caps  # type: ignore


def _parse_bool(x): return str(x).strip().lower() in ("1","true","yes","y","on")


def resolve_target_month() -> tuple[int, int]:
    y = os.getenv("YEAR")
    m = os.getenv("MONTH")
    if y and m:
        return int(y), int(m)
    today = datetime.now(timezone.utc).date()
    year = today.year
    month = today.month - 1 if today.month > 1 else 12
    if today.month == 1:
        year -= 1
    return year, month


def day_bounds_utc(y: int, m: int, d: int) -> tuple[str, str]:
    start = datetime(y, m, d, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def already_paid_for_month(sb, year: int, month: int) -> bool:
    start = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()
    last = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last, 23, 59, 59, tzinfo=timezone.utc).isoformat()
    res = (
        sb.table("transactions")
        .select("id", count="exact")
        .eq("payment_type", "revenue_split_monthly")
        .gte("created_at", start).lt("created_at", end)
        .execute()
    )
    return getattr(res, "count", 0) > 0


def main():
    print("[start] revenue_split_monthly", flush=True)
    pool_cents = int(os.getenv("POOL_CENTS", "10000000"))
    dry_run = _parse_bool(os.getenv("DRY_RUN", "true"))
    verbose = _parse_bool(os.getenv("VERBOSE", "1"))
    year, month = resolve_target_month()
    print(f"  Target {year}-{month:02d} | Pool ${pool_cents/100:,.2f} | DRY_RUN={dry_run}", flush=True)

    sb = make_client()
    if already_paid_for_month(sb, year, month):
        print(f"[skip] Already paid for {year}-{month:02d}", flush=True)
        return

    splitter = RevenueSplitter(sb, dry_run=True)  # compute units only; no writes here
    units_by_creator: dict[int, float] = defaultdict(float)

    last_day = calendar.monthrange(year, month)[1]
    for d in range(1, last_day + 1):
        start_iso, end_iso = day_bounds_utc(year, month, d)
        cnt = (
            sb.table("event").select("id", count="exact")
            .gte("ts", start_iso).lt("ts", end_iso).execute()
        ).count or 0
        if verbose:
            print(f"  Day {d:02d}: events={cnt}", flush=True)
        if cnt == 0:
            continue
        try:
            day_units = splitter.compute_units(date(year, month, d))
        except Exception as e:
            print(f"    ! compute_units failed for {year}-{month:02d}-{d:02d}: {e}", flush=True)
            continue
        if verbose:
            print(f"    creators_with_units={len(day_units)} total_units={sum(day_units.values()):,.4f}", flush=True)
        for cid, u in day_units.items():
            units_by_creator[cid] += u

    total_units = sum(units_by_creator.values())
    print(f"[aggregate] creators={len(units_by_creator)}  total_units={total_units:,.4f}", flush=True)
    if total_units <= 0:
        print(f"[skip] No eligible units", flush=True)
        return

    # Initial proportional allocations
    allocations = {
        cid: int(round(pool_cents * (u / total_units)))
        for cid, u in units_by_creator.items() if u > 0
    }

    # Apply KYC caps with redistribution
    allocations, unallocated = apply_kyc_caps(sb, allocations, units_by_creator)

    if dry_run:
        print(f"[dry-run] {year}-{month:02d}: creators={len(allocations)}, pool=${pool_cents/100:,.2f}", flush=True)
        top = sorted(allocations.items(), key=lambda kv: kv[1], reverse=True)[:10]
        for cid, amt in top:
            print(f"  creator {cid}: ${amt/100:,.2f}", flush=True)
        out_path = os.path.join(os.path.dirname(__file__), f"preview_{year}_{month:02d}.csv")
        with open(out_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["creator_id", "amount_cents", "amount_usd"])
            for cid, amt in sorted(allocations.items(), key=lambda kv: kv[1], reverse=True):
                w.writerow([cid, amt, f"{amt/100:.2f}"])
        if unallocated > 0:
            print(f"[dry-run] Unallocated due to KYC caps: {unallocated} cents", flush=True)
        print(f"[dry-run] Full preview written to {out_path}", flush=True)
        return

    # Commit: write inflows + bump balances
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "created_at": now_iso,
            "recipient": cid,
            "amount_cents": amt,
            "status": "pending",
            "payment_type": "revenue_split_monthly",
            "direction": "inflow",
        }
        for cid, amt in allocations.items() if amt > 0
    ]
    if rows:
        sb.table("transactions").insert(rows).execute()
        for cid, amt in allocations.items():
            cur = sb.table("users").select("current_balance").eq("id", cid).limit(1).execute().data
            curbal = (cur[0]["current_balance"] if cur else 0) or 0
            sb.table("users").update({"current_balance": curbal + amt}).eq("id", cid).execute()

    if unallocated > 0:
        print(f"[ok] wrote {len(rows)} rows; {unallocated} cents remained unallocated due to KYC caps", flush=True)
    else:
        print(f"[ok] wrote {len(rows)} monthly allocations for {year}-{month:02d}", flush=True)


if __name__ == "__main__":
    main()
