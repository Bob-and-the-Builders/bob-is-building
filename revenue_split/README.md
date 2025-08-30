Revenue Split Module
====================

This package implements a margin-safe revenue split for short-form videos that
is directly driven by Viewer Activity (VA) metrics. There is no admin UI; all
results are written transparently to database tables and can be viewed “as is”.

How Allocation Works
--------------------
- Pool sizing: A portion of net revenue forms the creator pool, capped to meet a
  margin target.
- Video weighting: For each eligible video in the window, we compute a utility
  score VU = EngUnits × (EIS/100)^γ × integrity_mod, where:
  - EngUnits is a simple event volume proxy from `event` rows
    (views + 2×likes + 5×comments − 10×reports, clamped ≥ 0).
  - EIS is produced by `viewer_activity` and averaged over the window.
  - integrity_mod is a small multiplier (0.85..1.0) derived from
    `viewer_activity` component scores (`like_integrity`, `report_credibility`).
- Creator streak bonus: A modest ±3% multiplier at the creator level based on
  7‑day average `videos.eis_current`, then re-normalized to preserve the pool.

Viewer Activity Integration
---------------------------
The `viewer_activity` pipeline computes and persists per-window metrics into
`video_aggregates` and keeps `videos.eis_current` updated. The revenue_split
logic reads these metrics; if a window aggregate is missing, it will call
`viewer_activity.analyzer.analyze_window(video_id, start, end)` to compute it on
the fly.

Tables Written
--------------
- `revenue_windows`: One row per finalized window with accounting and metadata.
- `video_rev_shares`: Per-video allocation details and the share within a window.
- `transactions`: Creator payouts and safety reserves (`payment_type`: payout/reserve).

SQL (run once in Supabase SQL editor)
------------------------------------
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
1. Ensure `.env` includes `SUPABASE_URL` and a server key (service-role) for writes.
2. Run your Viewer Activity pipeline (see `viewer_activity/README.md`) to populate
   `video_aggregates`. Missing windows are computed on-demand.
3. Call `finalize_revenue_window(start, end, ...)` from a server task or job.
4. Inspect results directly in tables: `revenue_windows`, `video_rev_shares`, and `transactions`.

Notes
-----
- All times are UTC; start/end are treated as inclusive/exclusive [start, end).
- Keys must remain server-side; never expose service-role keys to clients.
- This module is content-agnostic and relies solely on schema-driven activity.

