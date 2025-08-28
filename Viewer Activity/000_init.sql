-- USERS: one table for everyone
create table if not exists users (
  user_id text primary key,
  roles text[] not null default '{viewer}',     -- e.g. '{viewer,creator}'
  account_created_at timestamptz,
  kyc_level int default 0,                      -- 0 none, 1 basic, 2 full (future use)
  ip_asn_risk int default 0,                    -- 0 low,1 med,2 high
  prior_false_report_rate real default 0,       -- 0..1
  vts real default 50,                          -- viewer trust score 0..100
  cts real default 50,                          -- creator trust score 0..100 (future)
  updated_at timestamptz default now()
);

-- Optional creator-only fields (payout later); same user_id key
create table if not exists creator_profile (
  user_id text primary key references users(user_id) on delete cascade,
  payout_country text,
  payout_method text,
  compliance_status text default 'pending'
);

-- SHORTS
create table if not exists videos (
  video_id text primary key,
  creator_id text references users(user_id),
  title text,
  caption text,
  hashtags text[],                  -- for semantics-lite only
  duration_s int not null default 15,
  upload_ts timestamptz not null default now(),
  eis_current real default 0,
  eis_updated_at timestamptz
);

-- raw events
do $$ begin
  create type event_kind as enum('view','like','comment','report');
exception when duplicate_object then null; end $$;

create table if not exists viewer_events (
  event_id text primary key,
  video_id text references videos(video_id) on delete cascade,
  user_id text references users(user_id),       -- actor (viewer)
  event_type event_kind not null,
  ts timestamptz not null,
  device_id text,
  ip_hash text,
  metadata jsonb default '{}'::jsonb
);

-- moderation cache for comment events
create table if not exists comment_moderation (
  event_id text primary key references viewer_events(event_id) on delete cascade,
  toxicity real, insult real, spam_prob real, sentiment real
);

-- per-window aggregates
create table if not exists video_aggregates (
  id bigserial primary key,
  video_id text references videos(video_id) on delete cascade,
  window_start timestamptz not null,
  window_end timestamptz not null,
  features jsonb not null,
  comment_quality real,
  like_integrity real,
  report_credibility real,
  authentic_engagement real,
  eis real,
  created_at timestamptz default now()
);

-- indexes
create index if not exists idx_events_video_ts on viewer_events(video_id, ts);
create index if not exists idx_agg_video_window on video_aggregates(video_id, window_start);

-- RLS (demo-safe): public read, writes via service role
alter table users enable row level security;
alter table videos enable row level security;
alter table viewer_events enable row level security;
alter table video_aggregates enable row level security;
create policy "public read users" on users for select using (true);
create policy "public read videos" on videos for select using (true);
create policy "public read aggs"  on video_aggregates for select using (true);
create policy "public read events" on viewer_events for select using (true);
