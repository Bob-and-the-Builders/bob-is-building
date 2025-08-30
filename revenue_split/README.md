Revenue Split Module
====================

This package implements a margin-safe shorts revenue split with four refinements:

- Quality-Indexed Pool (±2% within margin guardrail)
- Integrity Streak Bonus (creator ±3% by 7-day avg EIS)
- Early-Velocity Kicker (+5% VU if early natural & diverse)
- Cluster Penalty Escalator (down-weights VU under device/IP clustering)

Files
-----
- `revenue_split/revenue_split.py`: server-side allocation logic (uses service-role key).
- `revenue_split/admin_revenue.py`: Streamlit admin to simulate a window and view allocations.

SQL (run in Supabase SQL editor)
--------------------------------
Idempotent DDL for transparent audit tables and indexes:

```sql
-- summary of a payout window
create table if not exists revenue_windows (
  id bigserial primary key,
  window_start timestamptz not null,
  window_end   timestamptz not null,
  gross_revenue_cents bigint not null default 0,
  taxes_cents bigint not null default 0,
  app_store_fees_cents bigint not null default 0,
  refunds_cents bigint not null default 0,
  pool_pct real not null default 0.45,
  margin_target real not null default 0.60,
  risk_reserve_pct real not null default 0.10,
  platform_fee_pct real not null default 0.10,
  costs_est_cents bigint not null default 0,
  creator_pool_cents bigint not null default 0,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz default now()
);

-- per-video allocation details
create table if not exists video_rev_shares (
  id bigserial primary key,
  revenue_window_id bigint references revenue_windows(id) on delete cascade,
  video_id bigint not null references videos(id) on delete cascade,
  eng_units bigint not null default 0,
  eis_avg real not null default 0,
  vu numeric not null default 0,
  share_pct real not null default 0,
  allocated_cents bigint not null default 0,
  meta jsonb not null default '{}'::jsonb
);

-- performance indexes
create index if not exists idx_event_vid_ts on event (video_id, ts);
create index if not exists idx_video_aggs_vid_we on video_aggregates (video_id, window_end);
create index if not exists idx_vrs_win on video_rev_shares (revenue_window_id);

-- transparency on videos (if not already added)
alter table videos
  add column if not exists eis_current real default 0,
  add column if not exists eis_updated_at timestamptz;
```

Usage
-----
1. Ensure `.env` includes `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` for server-side use.
2. Seed activity and compute EIS so `video_aggregates` has rows.
3. Run: `streamlit run revenue_split/admin_revenue.py`.
4. Verify:
   - Sum of `video_rev_shares.allocated_cents` ≤ `revenue_windows.creator_pool_cents`.
   - Platform margin = `(R_net - costs_est - CreatorPool)/R_gross ≥ margin_target`.
   - Early natural/diverse videos get small +5% VU; clustered device/IP get down-weighted.
   - High 7-day EIS creators receive +3% (renormalized to preserve the pool).
  - `transactions` contains payout and reserve rows using schema: `recipient`, `amount_cents`, `status`, `payment_type`.

Notes
-----
- All times are UTC.
- Streamlit runs server-side; do not expose service keys to browser clients.
- This module writes to `transactions` using your schema: `recipient` (FK to `users.id`), `amount_cents` (int8), `status` (text), `payment_type` (text, e.g., payout/reserve).
- This module does not modify any existing EIS logic and is content-agnostic.
