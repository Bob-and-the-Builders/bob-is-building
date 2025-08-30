# Data Generator (TechJam ERD)

Generates realistic, FK-safe sample data for the TikTok TechJam schema and can optionally upsert into Supabase.

Outputs JSON snapshots under `data/` and, with `--insert`, writes to your Supabase tables in FK-safe order.

## Quick Start

- Offline JSON only:
  - `python data/generate_fake_data.py --users 60`

- Insert into Supabase (upsert):
  - Set env: `SUPABASE_URL` and `SUPABASE_SECRET` (service role or anon for dev)
  - `python data/generate_fake_data.py --users 60 --insert`

- Seed known emails and guarantee creators:
  - `python data/generate_fake_data.py --users 20 --emails a@ex.com b@ex.com c@ex.com --creator-emails a@ex.com`

Artifacts written to `data/`:
- `users.json`, `user_info.json`, `documents.json`
- `videos.json`, `events.json`, `transactions.json`

## CLI Options

- `--users`: total users (default 750)
- `--creator-ratio`: fraction of users who are creators (default 0.35)
- `--min-videos` / `--max-videos`: per-creator video count (defaults 2..6)
- `--min-events` / `--max-events`: per-video event count (defaults 60..250)
- `--min-tx` / `--max-tx`: per-creator transaction count (defaults 2..8)
- `--emails`: assign these emails to the first N users (FK-safe seeding)
- `--creator-emails`: force these emails to be creators (ensures videos/tx)
- `--insert`: upsert rows into Supabase in FK-safe order

## Environment Variables (for --insert)

- Required: `SUPABASE_URL`, `SUPABASE_SECRET` (or `SUPABASE_KEY`)
- Recommended: use a Service Role key for server-side writes

## Tables + Columns (as generated)

- `users`
  - `id`, `created_at`, `is_creator`, `likely_bot`, `kyc_level`
  - `creator_trust_score` (creators only), `viewer_trust_score`
  - `user_info_id` (backfilled to mirror `user_info.id`), `current_balance` (cents)
- `user_info`
  - `id` (mirrors `users.id`), `first_name`, `last_name`, `date_of_birth`
  - `nationality`, `address`, `phone` (E.164), `email`, `user_id` (FK→users.id)
- `documents` (for KYC docs)
  - `id`, `full_name`, `document_type` (passport/drivers_license/national_id)
  - `document_number`, `issued_date`, `expiry_date`, `issuing_country`
  - `user_id` (FK→users.id), `submit_date`
- `videos`
  - `id`, `created_at`, `creator_id` (FK→users.id), `title`, `duration_s`
- `event`
  - `event_id`, `video_id` (FK→videos.id), `user_id` (FK→users.id)
  - `event_type` (view/like/comment/share/follow/report/pause)
  - `ts` (timestamptz), `device_id` (e.g., ios-xxxx), `ip_hash`
- `transactions`
  - `id`, `created_at`, `recipient` (FK→users.id), `amount_cents`
  - `status` (completed/pending/failed), `payment_type` (bank_transfer/paypal/wallet/card)

## How It’s Done (imports, APIs, flow)

Uses the Faker Import in order to generate fake data.

# Deterministic demos
fake = Faker()
random.seed(42)
Faker.seed(42)
load_dotenv()
```

Dataclasses used to model rows

```python
@dataclass
class User: ...

@dataclass
class UserInfo: ...

@dataclass
class Document: ...  # KYC docs

@dataclass
class Video: ...

@dataclass
class Event: ...

@dataclass
class Transaction: ...
```

Supabase API usage (via supabase-py)

```python
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SECRET") or os.environ.get("SUPABASE_KEY")
client: Client = create_client(url, key)

# Batched upserts preserve idempotency and FK order
client.table("users").upsert(user_chunk).execute()
client.table("user_info").upsert(info_chunk).execute()
client.table("documents").upsert(doc_chunk).execute()
client.table("videos").upsert(video_chunk).execute()
client.table("event").upsert(event_chunk).execute()
client.table("transactions").upsert(tx_chunk).execute()
```

Weighted event sampling

```python
EVENT_TYPES = [
    ("view", 0.55), ("like", 0.18), ("comment", 0.10),
    ("share", 0.07), ("follow", 0.05), ("report", 0.02), ("pause", 0.03)
]

def weighted_choice(weights):
    r = random.random(); upto = 0
    for item, w in weights:
        upto += w
        if r <= upto: return item
    return weights[-1][0]
```

Phone numbers (E.164) and timestamps

- Phones are generated in valid international formats for common countries and normalized away from leading zeros.
- Timestamps are ISO 8601 with a trailing `Z`, using a helper `iso(dt)` to trim microseconds and append `Z`.

## Insert Order and Batching

- Upsert order: `users` → `user_info` → backfill `users.user_info_id` → `documents` → `videos` → `event` → `transactions`
- Batch sizes: 500 (users/user_info/documents/videos/transactions), 1000 (event)

## Example Supabase DDL (documents table)

- Minimal shape to match generator output:
  - `create table if not exists documents (id bigserial primary key, full_name text, document_type text, document_number text, issued_date date, expiry_date date, issuing_country text, user_id bigint references users(id) on delete cascade, submit_date timestamptz default now());`

## Tips

- Use `--emails` to seed test accounts you can log in with; combine with `--creator-emails` to ensure they have videos and transactions.
- If `--insert` fails with a missing client, install: `pip install supabase` and ensure env vars are present.
- JSON snapshots are always written, even with `--insert`, for easy inspection.
