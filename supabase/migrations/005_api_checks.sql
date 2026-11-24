-- Migration 005: "Check now" on the API status page.
-- The website adds a row here; the worker on your PC sees it, sends one tiny request to that key + model,
-- and writes the result into api_key_status. Run once in Supabase -> SQL Editor. Safe to run again.
create table if not exists public.api_check_requests (
  id          uuid primary key default gen_random_uuid(),
  provider    text not null default 'gemini',
  slot        int  not null,                 -- 1 = api1, 2 = api2 ...
  model       text not null,
  status      text not null default 'pending',   -- pending | running | done
  result      text,                           -- ok | busy | quota | key_rejected | unavailable | error
  detail      text,
  created_at  timestamptz not null default now(),
  finished_at timestamptz
);

alter table public.api_check_requests enable row level security;

do $$
begin
  create policy api_check_read on public.api_check_requests for select using (public.is_allowed());
exception when duplicate_object then null;
end $$;

do $$
begin
  create policy api_check_insert on public.api_check_requests for insert with check (public.is_allowed());
exception when duplicate_object then null;
end $$;
