-- Migration 003: API status page (which keys / models are working).
-- Run once in Supabase -> SQL Editor. Safe to run again.
-- The worker writes these tables (service role); the website only reads them. API keys are never stored:
-- only the last 4 characters and the .env variable name.

create table if not exists public.api_models (
  provider        text not null,
  model           text not null,
  input_per_m     numeric,          -- USD per 1M tokens
  audio_per_m     numeric,
  output_per_m    numeric,
  free_available  boolean,          -- null = not known
  free_rpd        int,              -- free-tier requests per day (null = not known)
  free_rpm        int,
  free_tpm        int,
  note            text,
  in_chain        boolean not null default false,   -- used by the worker's failover list
  updated_at      timestamptz not null default now(),
  primary key (provider, model)
);

create table if not exists public.api_key_status (
  provider        text not null,
  slot            int  not null,    -- 1, 2, 3 ... = api1, api2, api3 ...
  model           text not null,
  env_name        text,             -- e.g. GEMINI_API_KEY_3
  key_tail        text,             -- last 4 characters only
  status          text not null default 'unknown',  -- unknown | ok | busy | quota | key_rejected | unavailable | error
  detail          text,
  last_ok_at      timestamptz,
  last_fail_at    timestamptz,
  last_seen_at    timestamptz,
  day             text,             -- quota day (Pacific time) the counters below belong to
  requests_today  int not null default 0,
  tokens_today    bigint not null default 0,
  updated_at      timestamptz not null default now(),
  primary key (provider, slot, model)
);

alter table public.api_models     enable row level security;
alter table public.api_key_status enable row level security;

do $$
begin
  create policy api_models_read on public.api_models for select using (public.is_allowed());
exception when duplicate_object then null;
end $$;

do $$
begin
  create policy api_key_status_read on public.api_key_status for select using (public.is_allowed());
exception when duplicate_object then null;
end $$;
