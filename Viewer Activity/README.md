Viewer Activity — EIS Demo

Purpose
- Compute an Engagement Integrity Score (EIS) for a short video using recent viewer events (views, likes, comments, reports) and user trust (VTS), with an optional tiny semantics-lite bonus.

Setup
- Env vars: set `SUPABASE_URL` and a write-capable key (`SUPABASE_SERVICE_ROLE_KEY` preferred; falls back to `SUPABASE_ANON_KEY` for read-only).
- Install: `pip install -r requirements.txt`

Seed + Quick Test
- Seed demo data and compute EIS for `videos.id=10` over the last 5 minutes:
  - `python Viewer Activity/synth.py`
  - This populates `users`, `videos`, and `event`, then runs the analyzer.
  - Verify schema connectivity: `python Viewer Activity/schema_probe.py`

Run UI
- `streamlit run Viewer Activity/app.py`
- Enter a `Video ID` (default `10`) and a window size, then press the button.

Notes
- Schema standardized to diagram: `users(id)`, `videos(id, creator_id, title, duration_s)`, `event(event_id, video_id, user_id, event_type, ts, device_id, ip_hash)`.
- No aggregates or moderation tables are written; EIS is computed on-demand.
- Writes require a service-role key due to RLS; anon key is often read-only.
- EIS uses only schema-derived engagement rates (no external video metadata). Duration is not required.
- Uses schema fields from `videos`:
  - `duration_s` adjusts expected engagement density (shorter videos → higher targets).
  - `created_at` contributes a recency adjustment (very new videos get target leniency; >24h slightly stricter).
  - Also fetches creator’s `creator_trust_score` for a mild multiplier (±5%).
- Bot/abuse checks integrated:
  - `users.likely_bot` and `users.kyc_level` reduce viewer trust (VTS) which flows into like/report integrity and comment quality.
  - Device/IP clustering on likes lowers like integrity when many distinct users share the same `device_id` or `ip_hash` within the window.
