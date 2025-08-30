# Revenue Split Module (Integrated with EIS Engine)

This module is Stage 2 of a two-part system. It consumes the Engagement Integrity Score (EIS) produced by the `viewer_activity` module to weight engagement-driven value fairly and transparently. Payouts are directly tied to the same analytics creators see.

- `revenue_split.py` — integrated daily engine using EIS
- `revenue_split_monthly.py` — monthly runner that sums daily units and allocates a monthly pool
- `README_legacy.md` — legacy documentation for the previous non-integrated engine

Project layout:

```
revenue_split/
├─ __init__.py
├─ revenue_split.py                 # integrated (uses EIS)
├─ revenue_split_monthly.py        # monthly runner (integrated)
├─ revenue_split_legacy.py         # preserved legacy engine
├─ revenue_split_monthly_legacy.py # preserved legacy monthly runner
└─ README_legacy.md                # preserved legacy docs
```

## Core Concept

The revenue split engine converts daily engagement into creator “Value Units,” weighted by the authoritative EIS computed by `viewer_activity`. EIS captures authenticity and integrity signals (e.g., engagement diversity, like integrity, report cleanliness) and is stored in `video_aggregates`. If an aggregate is missing, the engine computes it on-demand.

## New Value Unit Formula

For each video on a given day:

```
EngUnits = 1*Views + 3*Likes + 5*Comments + 8*Shares
ValueUnits = EngUnits * (EIS / 100.0)**gamma * EarlyKicker
FinalUnitsPerCreator = Σ ValueUnits_per_video * CreatorTrust
```

- `gamma`: 2.0 (quadratic weighting of EIS)
- `EarlyKicker`: 1.05 if the early-velocity window passes diversity gates, else 1.0
- `CreatorTrust`: a creator-level multiplier derived from `users.creator_trust_score` (see below)

## Removed Logic (now centralized in EIS)

The previous engine contained its own quality and integrity heuristics. These are deprecated and removed in the integrated version:

- quality multiplier (z-scored engagement rate)
- 7-day integrity multiplier
- cluster penalty multiplier

EIS already encapsulates authenticity and integrity using richer, transparent signals maintained in one place.

## Preserved Logic

- Early-Velocity Kicker: +5% when early engagement is sufficiently diverse (devices/IPs) within 2 hours of upload
- Creator Trust Score modulation: maps `users.creator_trust_score` (0..100) to a multiplier in [0.80, 1.20]
- Likely-bot exclusion: if `users.likely_bot = true`, units are set to 0
- KYC-based earning caps with redistribution: level 0/NULL ⇒ $0; level 1 ⇒ $50/run; level 2 ⇒ $500/run; level 3+ ⇒ unlimited

## How It Works (EIS integration)

For each video and run day, the engine fetches the average EIS from `video_aggregates` over the daily window. If no aggregate exists, it calls `viewer_activity.analyzer.analyze_window(video_id, start, end)` to compute it on-demand, persists the aggregate via the analyzer, and proceeds. This ensures robustness without manual backfills.

## Usage

Environment variables for Supabase access (service role recommended for writes):

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### Daily (integrated engine)

```python
from datetime import date
from revenue_split.revenue_split import RevenueSplitter, make_client

sb = make_client()
splitter = RevenueSplitter(sb, dry_run=True)
units_by_creator = splitter.compute_units(run_day=date(2025, 8, 30))

# Commit to transactions + balances
splitter = RevenueSplitter(sb, dry_run=False)
breakdown = splitter.run(pool_cents=500_000, run_day=date(2025, 8, 30), payment_type="revenue_split")
```

### Monthly (integrated runner)

```bash
export SUPABASE_URL="https://YOUR.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="SERVICE_ROLE_KEY"
export POOL_CENTS="10000000"          # $100,000 monthly pool
export YEAR="2025"; export MONTH="8"  # optional; defaults to previous month (UTC)
export DRY_RUN="true"                  # preview mode (CSV + console)
python -u -m revenue_split.revenue_split_monthly

# Commit monthly allocations:
export DRY_RUN="false"
python -u -m revenue_split.revenue_split_monthly
```

### Data Model Touchpoints

- `users(id, current_balance, kyc_level, creator_trust_score, likely_bot)`
- `videos(id, creator_id, created_at, eis_current, eis_updated_at)`
- `event(video_id, event_type, ts, device_id, ip_hash)`
- `video_aggregates(video_id, window_start, window_end, eis, features, …)`
- `transactions(created_at, recipient, amount_cents, payment_type, status, direction)`

## Notes

- All money math is in cents; caps are applied per run (daily/monthly) with proportional redistribution of excess.
- The legacy engine and docs are preserved under `*_legacy` for reference and rollback safety.

