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

Run UI
- `streamlit run Viewer Activity/app.py`
- Enter a `Video ID` (default `v1`) and a window size, then press the button.

Notes
- Schema standardized to diagram: `users(id)`, `videos(id)`, `event` with `event_type` text.
- No aggregates or moderation tables are written; EIS is computed on-demand.
- Writes require a service-role key due to RLS; anon key is often read-only.
- If present on `videos`, the analyzer reads optional metadata like `duration_seconds`, `fps`, `width`, `height`, `has_audio` and echoes them in features (they don’t affect EIS unless watch metrics are added later).
