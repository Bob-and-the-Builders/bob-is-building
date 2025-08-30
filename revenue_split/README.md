# Revenue Split Module

This package implements a **margin-safe revenue split** for short-form videos with four event-driven refinements, a stored **Creator Trust Score** adjustment, a **hard-exclude** for suspicious creators, and **KYC-based earning caps** (with fair redistribution of over-cap funds).

- `revenue_split.py` — daily units calculator and writer (can also be used for preview/dry usage).
- `revenue_split_monthly.py` — monthly aggregator/runner (CLI) that sums daily units across a month and writes one inflow per creator.

```
revenue_split/
├─ __init__.py
├─ revenue_split.py
└─ revenue_split_monthly.py
```

---

## Data model (Supabase)

Tables & columns used:

### `users`
- `id` (int, PK)
- `current_balance` (int, cents)
- `kyc_level` (int; **0/NULL ⇒ no earnings**, 1 ⇒ $50/run, 2 ⇒ $500/run, 3+ ⇒ unlimited)
- `creator_trust_score` (numeric; expected range **0..100**)
- `likely_bot` (bool)

### `videos`
- `id` (int, PK)
- `creator_id` (int, FK → users.id)
- `created_at` (timestamptz)

### `event`
- `video_id` (int, FK → videos.id)
- `event_type` (text: `view|like|comment|share`)
- `ts` (timestamptz)
- `device_id` (text, nullable)
- `ip_hash` (text, nullable)

### `transactions`
- `id` (int, PK)
- `created_at` (timestamptz, **DEFAULT now()**, NOT NULL)
- `recipient` (int, FK → users.id)
- `amount_cents` (int)
- `payment_type` (text; e.g., `revenue_split`, `revenue_split_monthly`, `bank_transfer`, `wallet`, `paypal`)
- `status` (text; e.g., `pending`, `completed`)
- `direction` (text/enum; `inflow` or `outflow`)

**Recommended one-time SQL hardening:**

```sql
ALTER TABLE transactions ALTER COLUMN created_at SET DEFAULT now();
UPDATE transactions SET created_at=now() WHERE created_at IS NULL;

ALTER TABLE transactions
  ADD CONSTRAINT IF NOT EXISTS transactions_recipient_fkey
  FOREIGN KEY (recipient) REFERENCES users(id);

ALTER TABLE users ALTER COLUMN kyc_level SET DEFAULT 0;
UPDATE users SET kyc_level=0 WHERE kyc_level IS NULL OR kyc_level::text IN ('', 'None');
```

---

## Event weights

Daily raw units per video are computed from events with fixed weights:

```
raw_units = 1*views + 3*likes + 5*comments + 8*shares
```

(Weights are configurable via `EVENT_WEIGHTS`.)

---

## Multipliers (per video / per creator)

All multipliers multiply the raw units; the final **per-creator units** are aggregated before money scaling.

### 1) Quality-Indexed Pool (±2%)

For each video on the **run day**:

- Engagement rate: `ER = (likes + comments + shares) / max(1, views)`  
- Compute z-score on that day’s cohort: `z = (ER - μ) / σ`  
- Apply a small guard-railed bump:  
  `quality_mult = 1 + clip(z * 1%, -2%, +2%)`

### 2) Early-Velocity Kicker (+5%)

Looks at the first **2 hours after `videos.created_at`** (cross-day if needed):

- Require at least **EARLY_MIN_VIEWS** (default 50)
- Diversity gates in the early window:
  - unique devices ≥ 50% of early views
  - unique IPs ≥ 40% of early views

If both pass: `early_mult = 1.05`; else `1.0`.

### 3) Cluster Penalty (up to −30%)

For run-day views of a video:

- Compute the **top share** by `device_id` and `ip_hash`.
- If top share ≤ 20% ⇒ `1.0`. Above that, linearly penalize up to −30% at high clustering:  
  `cluster_mult = max(1 - 30%, 1 - 2.0 * (top_share - 20%))`

### 4) 7-day Integrity (±3%) — per creator

Over the 7-day window ending at the run day:

```
score_0_1 = (
  min(1, 5 * uniq_dev / max(1, views)) +
  min(1, 5 * uniq_ip  / max(1, views)) +
  min(1,10 * (likes + comments) / max(1, views))
) / 3

integrity_mult = (1 - 3%) + 2 * 3% * score_0_1
```

### 5) Creator Trust Score (±10%) — per creator

Reads `users.creator_trust_score` (expected **0..100**, configurable).

```
trust_mult(s) = 0.90 + 0.20 * clip(s, 0, 100) / 100
# s = 0   => 0.90×
# s = 50  => 1.00×
# s = 100 => 1.10×
# missing/invalid => 1.00×
```

### 6) Hard-exclude suspicious creators

If `users.likely_bot = true` ⇒ **multiplier = 0.0** (no payout).  
This overrides the trust score.

---

## From units to money (pool scaling)

Given a **pool** (in cents) for a period (day or month):

1. Sum final per-creator units: `U = Σ u_i`.
2. Proportional allocation (rounded to cents):  
   `a_i = round( (u_i / U) * POOL_CENTS )`

### KYC-based caps (per run) + redistribution

We enforce **per-run caps** using `users.kyc_level`:

- Level **0** or **NULL** ⇒ **$0** cap (no earnings)
- Level **1** ⇒ **$50** cap (5,000 cents)
- Level **2** ⇒ **$500** cap (50,000 cents)
- Level **3+** ⇒ unlimited

If `a_i` exceeds the cap, it’s clamped to the cap and the **excess is redistributed** proportionally among creators who still have capacity (by their units). This iterates until stable. If everyone becomes capped, any leftover is reported as **unallocated**.

> Caps are applied in **both** daily (`RevenueSplitter.run`) and monthly (`revenue_split_monthly.py`) flows.

---

## `revenue_split.py`

### Main class

```python
from revenue_split.revenue_split import RevenueSplitter, make_client

sb = make_client()  # uses SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

# Preview only (no writes):
splitter = RevenueSplitter(sb, dry_run=True)
units_by_creator = splitter.compute_units(run_day=date(2025, 8, 30))

# Commit (writes inflows + updates balances):
splitter = RevenueSplitter(sb, dry_run=False)
breakdown = splitter.run(pool_cents=500_000, run_day=date(2025, 8, 30), payment_type="revenue_split")
```

**Behavior**
- `compute_units(run_day)`: pure computation, **no writes**.
- `run(pool_cents, run_day, payment_type)`: scales to money, **applies KYC caps + redistribution**, writes `transactions` (`direction='inflow'`, `status='pending'`, `created_at=now()`), and increments `users.current_balance`.

**Key knobs**
- `EVENT_WEIGHTS = {"view":1,"like":3,"comment":5,"share":8}`
- `QUALITY_CLAMP_PCT = 0.02` (±2%)
- `EARLY_KICKER_MULT = 1.05`
- `CLUSTER_MAX_PENALTY = 0.30`
- `INTEGRITY_RANGE_PCT = 0.03` (±3%)
- `CREATOR_TRUST_MIN/MAX_MULT = 0.90/1.10`
- `PENALIZE_LIKELY_BOT = True`
- `KYC_CAPS_CENTS = {0:0, 1:5_000, 2:50_000}` (3+ unlimited)

**Performance**
- Uses `fetch_all(...).range()` paging (default page size 10k) for events/videos/users.
- All money math is in **cents**.

---

## `revenue_split_monthly.py` (CLI)

Aggregates daily units across a month, scales by a monthly pool, applies **KYC caps with redistribution**, and writes a single **monthly inflow** per creator.

### Environment variables

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `POOL_CENTS` — monthly pool in **cents** (e.g., `10000000` for $100k)
- `YEAR`, `MONTH` — optional; if omitted, script targets the **previous month** (UTC)
- `DRY_RUN` — `"true"`/`"false"` (default `true` in examples)
- `VERBOSE` — `"1"`/`"0"` for per-day logs

### Run (bash/zsh)

```bash
export SUPABASE_URL="https://YOUR.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="SERVICE_ROLE_KEY"
export POOL_CENTS="10000000"          # $100,000
export YEAR="2025"; export MONTH="8"  # target Aug 2025
export DRY_RUN="true"
python -u -m revenue_split.revenue_split_monthly

# Commit:
export DRY_RUN="false"
python -u -m revenue_split.revenue_split_monthly
```

### Output

- **Dry-run:** prints summary & top creators and writes CSV preview to:
  ```
  revenue_split/preview_YYYY_MM.csv
  ```
- **Commit:** inserts one `transactions` row per creator:
  - `payment_type="revenue_split_monthly"`
  - `direction="inflow"`
  - `status="pending"`
  - `created_at=now()`
  - then bumps `users.current_balance`.

### Idempotency

The runner **skips** if the month already has any `transactions` with `payment_type='revenue_split_monthly'` within the month’s date range.

---

## Example logs (dry-run)

```
[start] revenue_split_monthly
  Target 2025-08 | Pool $100,000.00 | DRY_RUN=True
  Day 01: events=184392
    creators_with_units=153 total_units=54,775.2175
  ...
[aggregate] creators=153  total_units=321,456.9123
[dry-run] 2025-08: creators=153, pool=$100,000.00
  creator 38: $1,905.27
  creator 93: $1,792.16
  ...
[dry-run] Full preview written to revenue_split/preview_2025_08.csv
[dry-run] Unallocated due to KYC caps: 12345 cents
```

---

## Edge cases & notes

- **KYC 0/NULL ⇒ no earnings.** Their would-be share is redistributed; if no capacity remains, some pool may be **unallocated**.
- **likely_bot = true ⇒ 0× multiplier.** No payout regardless of units or score.
- **Missing trust score ⇒ 1.00×** (neutral) by design.
- **No events** on a day/month ⇒ total units = 0 ⇒ no allocation.
- **Rounding:** allocations are rounded to cents; monthly runner ensures sum ≈ pool and redistributes remainders.
- **Time zones:** all computations are **UTC**.
- **Money math:** always in **cents** (ints).

---

## Troubleshooting

- **Monthly job prints nothing** → run unbuffered & verbose:
  ```bash
  VERBOSE=1 python -u -m revenue_split.revenue_split_monthly
  ```
- **Monthly skipped** → existing `payment_type='revenue_split_monthly'` rows in that month.
- **Dates show as `—` in UI** → older rows lacked `created_at`; backfill in DB and clear your Streamlit cache.
- **Creator missing from payouts** → ensure `videos.creator_id = users.id` and events reference valid `video_id`; confirm KYC 0 / likely_bot not excluding them.

---

## Extensibility

- Change event weights or multiplier bounds in `revenue_split.py`.
- Add caps by **cumulative month** (instead of per run) by summing prior month inflows before applying caps.
- Add new event types by extending `EVENT_WEIGHTS` and ingestion.
- Make writes atomic via a Postgres function/transaction if desired.

---

## Security

Use the **service-role** key only in backend CI/cron contexts. Frontend should use anon key + RLS.
