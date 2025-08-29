Viewer Activity — EIS (Transparent & Schema-Based)

Purpose
- Compute an Engagement Integrity Score (EIS) for a short video using recent viewer events (views, likes, comments, reports) and user trust (VTS). No content semantics are used.

Setup
- Env vars: set `SUPABASE_URL` and a write-capable key (`SUPABASE_SERVICE_ROLE_KEY` preferred). Falls back to anon for read-only.
- Install: `pip install -r requirements.txt`

One-time SQL (Supabase SQL editor)
```sql
alter table videos
  add column if not exists eis_current real default 0,
  add column if not exists eis_updated_at timestamptz;

create table if not exists video_aggregates (
  id bigserial primary key,
  video_id bigint references videos(id) on delete cascade,
  window_start timestamptz not null,
  window_end   timestamptz not null,
  features jsonb not null,
  comment_quality real,
  like_integrity real,
  report_credibility real,
  authentic_engagement real,
  eis real,
  created_at timestamptz default now()
);

-- performance: index for window queries
create index if not exists idx_event_vid_ts on event (video_id, ts);
```

Seed + Quick Test
- Seed demo data and compute EIS for `videos.id=10` over the last 5 minutes:
  - `python Viewer Activity/synth.py`
  - Populates `users`, `videos`, and `event`, then runs the analyzer and writes to `video_aggregates` and `videos.eis_current`.
  - Verify schema connectivity: `python Viewer Activity/schema_probe.py`

Run UI
- `streamlit run Viewer Activity/app.py`
- Enter a `Video ID` (default `10`) and a window size, then press the button.
- The page shows:
  - The EIS score and a JSON “Details” payload (features, breakdown, component scores).
  - A line chart of recent EIS values from `video_aggregates`.

Design & Data Flow
- Analyzer (`analyzer.py`)
  - Pulls `videos` to identify `creator_id`, `duration_s`, and `created_at`.
  - Fetches `event` rows for `[start, end)` and groups into view/like/comment/report.
  - Builds transparent `features` such as active viewers, likes/views, comments/views, device/IP concentrations, duration and recency.
  - Computes VTS map from `users` and strictly uses schema signals (no text semantics).
  - Component scores:
    - Authentic Engagement: likes/views + comments/views with duration/recency scaling, plus a small audience factor (active viewers) at 20% weight.
    - Comment Quality: who comments (unique commenters rate, commenters’ VTS), not what they say.
    - Like Integrity: commenters’ VTS, timing naturalness (CV of inter-arrival intervals), and device/IP clustering penalties.
    - Report Cleanliness: higher-weighted reports reduce integrity.
  - EIS blend: `0.4*AE + 0.25*CQ + 0.2*LI + 0.15*RC`, with a tiny creator trust modulation (±5%) if `users.creator_trust_score` exists.
  - Persists each window into `video_aggregates` and updates `videos.eis_current` + `videos.eis_updated_at`.
- Scoring (`scoring.py`)
  - `comment_quality_with_details(comments, vts_map, active_viewers)` → score, details (`unique_commenters_rate`, `avg_commenter_vts`).
  - `like_integrity_with_details(likes, vts_map)` → score, details (`nat_cv`, `users_per_device`, `users_per_ip`, penalties).
  - `authentic_engagement_with_details(features)` → score, details (targets, duration/recency scales, audience component).
  - `eis_score(ae,cq,li,rc)` → weighted blend.
- App (`app.py`)
  - Server-side Supabase client (dotenv). Computes the window, calls `analyze_window`, shows Details JSON, and renders an EIS trend from `video_aggregates`.
- Supabase Manager (`supabase_manager.py`)
  - `_make_client()` reads env; uses service-role key for server writes.
  - `upsert_aggregate(...)` inserts into `video_aggregates` and updates `videos.eis_current`.

Key Handling
- Keep keys in `.env` (server-only). The Streamlit app uses Python to create the Supabase client; no keys are exposed to the browser.

Success Criteria
- Clicking “Compute” updates `videos.eis_current` and inserts a row into `video_aggregates`.
- The JSON “Details” shows features, breakdown, and component scores.
- The chart shows EIS change over time for the chosen video.
- No semantics are referenced anywhere in the Viewer Activity path.
