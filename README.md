# bob-is-building

TikTok TechJam 25 - Creator monetization, integrity, and payouts demo.

This project brings together a Streamlit-powered Creator Portal, a transparent Engagement Integrity Score (EIS) pipeline driven by viewer activity, and a revenue split engine that allocates earnings fairly while preserving platform margin and safety reserves. Everything runs against a Supabase (Postgres) backend with example data generators and helper tooling for fast iteration during the hack.

## What It Does (Features & Functionality)

- Creator Portal (Streamlit)
  - Email/password auth via Supabase with email verification
  - Creator Dashboard with KPIs, engagement rate, KYC level, and creator trust score
  - Upload Video flow that extracts basic metadata (duration, codec) and stores a row in `videos`
  - Video Payouts screen that shows balance and transaction history and lets creators request payouts with KYC-based limits
  - Video Analytics page that computes and visualizes EIS with a gauge, metric cards, and anomaly guidance (see `frontend/pages/video_analytics.py`)
- Viewer Activity + EIS (Integrity)
  - Computes a transparent Engagement Integrity Score from schema-only signals: views, likes, comments, reports, device_id and ip_hash diversity, timing naturalness, and viewer trust scores (VTS)
  - Writes historical aggregates to `video_aggregates` and updates `videos.eis_current`
  - Comes with a Streamlit page to compute latest windows and chart trends
- Revenue Split Engine (Shorts-like windows)
  - Turns net revenue for a time window into creator allocations using EngUnits (weighted view/like/comment/report), quality-weighted by EIS, with early-velocity boost and cluster-penalty defenses
  - Enforces a margin guardrail and carves out platform fee and safety reserve with minimum payout thresholds
  - Writes to `revenue_windows`, `video_rev_shares`, and creator `transactions`
- Trust, KYC, and Anti-abuse
  - KYC checker and status/level classifier (mock, deterministic, explainable)
  - Phone trust scoring using a phone validation API to simulate risk-aware viewer trust scores (VTS)
- Data & Tooling
  - Deterministic fake data generator that preserves foreign keys and can optionally insert into Supabase
  - Simple DB helpers for local dev and server-side tasks

## Why It Fits TikTok TechJam

- Transparent integrity: EIS is computed from schema-only signals; no content semantics are used.
- Fair allocation: Quality-indexed pool with clear, explainable mechanics and margin guardrails.
- Safety-first payouts: KYC levels gate payout sizes; reserves reduce fraud and chargeback risk.
- Practical demo: Streamlit UIs for creators and admins, backed by a real Postgres (Supabase) schema.

## Tech Stack & Development Tools

- Python 3.11+
- Streamlit apps for Creator Portal and admin tools
- Supabase (Postgres + Auth) for storage, auth, and server functions
- Local environment via `.env` and `python-dotenv`
- Optional: ffmpeg/ffprobe installed locally to enrich video metadata
- Plotly for Streamlit visualizations (gauge component in analytics)

## APIs & Services

- Supabase
  - Environment: `SUPABASE_URL`, and one of `SUPABASE_ANON_KEY` (client reads) or `SUPABASE_SERVICE_ROLE_KEY`/`SUPABASE_SECRET` (server writes)
  - Client helpers: `supabase_conn.get_supabase_client(prefer_service=...)` and `viewer_activity/supabase_manager.py`
  - Key tables used: `users`, `user_info`, `videos`, `event`, `transactions`, `video_aggregates`, `revenue_windows`, `video_rev_shares`
- AbstractAPI Phone Validation (optional, for trust scoring)
  - Used by `bot_account_detection/trust_score.py`
  - Environment: `ABSTRACT_API_KEY`
- ffprobe (optional)
  - Used in `frontend/pages/upload_video.py` to detect codec if available

## Libraries & Assets

- Core: `streamlit`, `supabase`, `python-dotenv`, `requests`, `moviepy`, `Faker`, `plotly`
- Data/analytics: `pandas`, `numpy` (used in dashboards/pages)
- UI assets: Streamlit material icons; no bundled static assets
- Phone validation: phonenumbers

## Run It (Local)

1) Install dependencies
   - `pip install -r requirements.txt`
   - If needed for dashboards/analytics: `pip install pandas numpy plotly`
2) Set environment in `.env`
   - `SUPABASE_URL=...`
   - `SUPABASE_ANON_KEY=...` (for client reads)
   - `SUPABASE_SERVICE_ROLE_KEY=...` (for server writes)
   - Note: the Creator Portal reads `SUPABASE_SECRET` in `frontend/app.py`. In local dev, set `SUPABASE_SECRET` to your anon key.
   - Optional: `ABSTRACT_API_KEY=...` (for phone trust)
3) Start Streamlit apps
   - Creator Portal: `streamlit run frontend/app.py`
   - EIS Viewer Activity: `streamlit run viewer_activity/app.py`
   - Admin Revenue Window: `streamlit run revenue_split/admin_revenue.py`
   - Video Analytics (standalone page): `streamlit run frontend/pages/video_analytics.py`

## Architecture Map (Folders)

- `frontend/` - Creator Portal (auth, dashboard, uploads, payouts)
- `viewer_activity/` - EIS computation, trend UI, and Supabase manager
- `revenue_split/` - Revenue window allocator and admin app
- `bot_account_detection/` - KYC and phone trust scoring utilities
- `data/` - FK-safe fake data generator and JSON snapshots
- `supabase_conn.py`, `db_client.py` - thin Supabase helpers
 - `core/` - Simplified analytics engine and a cached Supabase client used by analytics page
 - `ui/` - Reusable Streamlit components (EIS gauge, metric and anomaly cards)

## Data Model (ERD Highlights)

- `users(id, created_at, is_creator, likely_bot, kyc_level, creator_trust_score, viewer_trust_score, user_info_id, current_balance)`
- `user_info(id, first_name, last_name, date_of_birth, nationality, address, phone, email, user_id)`
- `videos(id, created_at, creator_id, title, duration_s, eis_current?, eis_updated_at?)`
- `event(event_id, video_id, user_id, event_type, ts, device_id, ip_hash)`
- `transactions(id, created_at, recipient, amount_cents, status, payment_type)`
- `video_aggregates(id, video_id, window_start, window_end, features, ... , eis)`
- `revenue_windows(...), video_rev_shares(...)` (admin allocation outputs)

## Fake Data Generation

Use `data/generate_fake_data.py` to create realistic, FK-safe sample data for the ERD (users, user_info, videos, event, transactions).

- Offline (default) writes JSON under `data/`:
  - `python data/generate_fake_data.py --users 60`

- Optional: insert directly into Supabase (respecting foreign keys). Requires env vars `SUPABASE_URL` and `SUPABASE_ANON_KEY` (or `SUPABASE_SERVICE_ROLE_KEY`).
  - `python data/generate_fake_data.py --insert`

Tunable knobs:
`--creator-ratio`, `--min-videos`, `--max-videos`, `--min-events`, `--max-events`, `--min-tx`, `--max-tx`.

The generator ensures:
- `user_info.user_id` references `users.id` (1:1), and `users.user_info_id` mirrors it.
- `videos.creator_id` references a user marked `is_creator = true`.
- `event.video_id` references an existing video, `event.user_id` references an existing user.
- `transactions.recipient` references an existing creator by default.
