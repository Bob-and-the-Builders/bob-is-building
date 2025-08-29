# bob-is-building
TikTok TechJam 25

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
