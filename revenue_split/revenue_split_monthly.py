# revenue_split/revenue_split_monthly.py
from __future__ import annotations
import os
import sys
import csv
import calendar
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict

# Robust import: module mode OR direct file run
try:
    from revenue_split.revenue_split import RevenueSplitter, make_client
except ModuleNotFoundError:
    sys.path.append(os.path.dirname(__file__))
    from revenue_split import RevenueSplitter, make_client  # type: ignore


def _prefix(token: str | None, keep: int = 6) -> str:
    if not token:
        return "n/a"
    return token[:keep] + "…" if len(token) > keep else token


def resolve_target_month() -> tuple[int, int]:
    """Default to PREVIOUS month (UTC). Override with YEAR/MONTH env to run current month."""
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
    month_start = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
    res = (
        sb.table("transactions")
        .select("id", count="exact")
        .eq("payment_type", "revenue_split_monthly")
        .gte("created_at", month_start)
        .lt("created_at", month_end)
        .execute()
    )
    return getattr(res, "count", 0) > 0


def main():
    # Print config immediately so you see something right away
    print("[start] revenue_split_monthly", flush=True)
    print(f"  SUPABASE_URL prefix:    { _prefix(os.getenv('SUPABASE_URL')) }", flush=True)
    print(f"  SERVICE_ROLE_KEY prefix:{ _prefix(os.getenv('SUPABASE_SERVICE_ROLE_KEY')) }", flush=True)

    pool_cents = int(os.getenv("POOL_CENTS", "10000000"))  # default $100k
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    verbose = os.getenv("VERBOSE", "1").lower() not in ("0", "false", "no")

    year, month = resolve_target_month()
    print(f"  Target month: {year}-{month:02d}", flush=True)
    print(f"  Pool: ${pool_cents/100:,.2f}  |  DRY_RUN={dry_run}  |  VERBOSE={verbose}", flush=True)

    # Connect
    sb = make_client()
    if already_paid_for_month(sb, year, month):
        print(f"[skip] Monthly split already written for {year}-{month:02d}", flush=True)
        return

    splitter = RevenueSplitter(sb, dry_run=False)  # compute units only
    units_by_creator: dict[int, float] = defaultdict(float)

    last_day = calendar.monthrange(year, month)[1]
    for d in range(1, last_day + 1):
        # Quick count to show progress even if there are no events
        start_iso, end_iso = day_bounds_utc(year, month, d)
        cnt_res = (
            sb.table("event")
            .select("event_id", count="exact")
            .gte("ts", start_iso)
            .lt("ts", end_iso)
            .execute()
        )
        day_event_count = getattr(cnt_res, "count", 0) or 0
        if verbose:
            print(f"  Day {d:02d}: events={day_event_count}", flush=True)

        if day_event_count == 0:
            continue

        # Compute per-day units (after all multipliers)
        try:
            day_units = splitter.compute_units(date(year, month, d))
        except Exception as e:
            print(f"    ! compute_units failed for {year}-{month:02d}-{d:02d}: {e}", flush=True)
            continue

        if verbose:
            print(f"    creators_with_units={len(day_units)}  total_units={sum(day_units.values()):,.4f}", flush=True)

        for cid, u in day_units.items():
            units_by_creator[cid] += u

    total_units = sum(units_by_creator.values())
    print(f"[aggregate] creators={len(units_by_creator)}  total_units={total_units:,.4f}", flush=True)

    if total_units <= 0:
        print(f"[skip] No eligible engagement units for {year}-{month:02d}", flush=True)
        return

    allocations = {
        cid: int(round(pool_cents * (u / total_units)))
        for cid, u in units_by_creator.items()
        if u > 0
    }

    if dry_run:
        # Console summary
        print(f"[dry-run] {year}-{month:02d}: creators={len(allocations)}, pool=${pool_cents/100:,.2f}", flush=True)
        top = sorted(allocations.items(), key=lambda kv: kv[1], reverse=True)[:10]
        for cid, amt in top:
            print(f"  creator {cid}: ${amt/100:,.2f}", flush=True)

        # CSV preview next to this script
        out_path = os.path.join(os.path.dirname(__file__), f"preview_{year}_{month:02d}.csv")
        with open(out_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["creator_id", "amount_cents", "amount_usd"])
            for cid, amt in sorted(allocations.items(), key=lambda kv: kv[1], reverse=True):
                w.writerow([cid, amt, f"{amt/100:.2f}"])
        print(f"[dry-run] Full preview written to {out_path}", flush=True)
        return

    # --- Write monthly allocations ---
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
        for cid, amt in allocations.items()
        if amt > 0
    ]
    if rows:
        sb.table("transactions").insert(rows).execute()
        for cid, amt in allocations.items():
            cur = sb.table("users").select("current_balance").eq("id", cid).limit(1).execute().data
            curbal = (cur[0]["current_balance"] if cur else 0) or 0
            sb.table("users").update({"current_balance": curbal + amt}).eq("id", cid).execute()

    print(f"[ok] wrote {len(rows)} monthly allocations for {year}-{month:02d}", flush=True)


if __name__ == "__main__":
    # Unbuffered runs show progress immediately even in some terminals
    main()
