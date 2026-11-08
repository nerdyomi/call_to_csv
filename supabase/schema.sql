-- iFarmer call analysis: database schema for Supabase (Postgres).
-- Run once in Supabase -> SQL Editor -> New query -> paste all -> Run.
-- It is safe to run again (uses IF NOT EXISTS / OR REPLACE where possible).
--
-- BEFORE RUNNING: replace YOUR_LOGIN_EMAIL in the allowed_users insert at the bottom
-- with the email you will log in with.

-- ---------------------------------------------------------------- who may use the app
create table if not exists public.allowed_users (
  email      text primary key,
  role       text not null default 'admin',          -- roles are decided later; everyone is 'admin' for now
  created_at timestamptz not null default now()
);

create or replace function public.is_allowed() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.allowed_users u
    where lower(u.email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- ---------------------------------------------------------------- farmers and calls
-- A farmer is identified by phone number, stored as 8801XXXXXXXXX.
create table if not exists public.farmers (
  phone      text primary key,
  name       text,
  created_at timestamptz not null default now()
);

create table if not exists public.calls (
  id               uuid primary key default gen_random_uuid(),
  phone            text not null references public.farmers(phone),
  call_date        date,                              -- null = date unknown (shown as "none")
  call_seq         int  not null default 1,           -- 1, 2, 3 ... when the same phone+date repeats: shown as (2), (3)
  file_name        text not null,
  storage_path     text not null unique,              -- path inside the 'recordings' bucket
  file_size        bigint,
  duration_seconds numeric,
  status           text not null default 'uploaded'
                   check (status in ('uploaded', 'queued', 'processing', 'done', 'failed')),
  error            text,
  attempts         int  not null default 0,
  model            text,
  queued_at        timestamptz,
  started_at       timestamptz,
  finished_at      timestamptz,
  created_by       uuid references auth.users(id),
  created_at       timestamptz not null default now()
);
-- one row per phone + date + sequence number (date null counts as one "unknown" date)
create unique index if not exists calls_unique_idx
  on public.calls (phone, coalesce(call_date, date '0001-01-01'), call_seq);
create index if not exists calls_phone_idx  on public.calls (phone);
create index if not exists calls_status_idx on public.calls (status);
create index if not exists calls_date_idx   on public.calls (call_date desc);

-- ---------------------------------------------------------------- analysis result (latest run per call)
create table if not exists public.call_results (
  call_id         uuid primary key references public.calls(id) on delete cascade,
  transcript      jsonb not null default '[]',        -- [{speaker, time, text}]
  transcript_text text  not null default '',          -- "CEX: ... (00:00:07)" lines, handy for the chatbot
  fields          jsonb not null default '{}',        -- {"loan_amount": "40000", ...}  only filled fields
  evidence        jsonb not null default '{}',        -- {"loan_amount": {confidence, evidence, timestamp}, ...}
  review          jsonb not null default '[]',        -- [{field, kind, detail}]
  notes           text,
  eng_notes       text,
  assessment      jsonb,
  usage           jsonb,
  raw             jsonb,
  model           text,
  updated_at      timestamptz not null default now()
);
create index if not exists call_results_fields_gin on public.call_results using gin (fields);

-- ---------------------------------------------------------------- chat history
create table if not exists public.chat_messages (
  id         bigint generated always as identity primary key,
  scope      text not null check (scope in ('call', 'global')),
  call_id    uuid references public.calls(id) on delete cascade,   -- set when scope = 'call'
  user_id    uuid references auth.users(id),
  role       text not null check (role in ('user', 'assistant')),
  content    text not null,
  created_at timestamptz not null default now()
);
create index if not exists chat_call_idx on public.chat_messages (call_id, created_at);

-- ---------------------------------------------------------------- worker queue helpers (service role only)
-- Atomically takes the oldest queued call so that several workers never get the same one.
create or replace function public.claim_next_call() returns setof public.calls
language plpgsql security definer set search_path = public as $$
declare r public.calls;
begin
  select * into r from public.calls
   where status = 'queued'
   order by queued_at nulls last, created_at
   for update skip locked
   limit 1;
  if not found then
    return;
  end if;
  update public.calls
     set status = 'processing', attempts = attempts + 1, started_at = now(), error = null
   where id = r.id
   returning * into r;
  return next r;
end;
$$;

-- Puts calls back in the queue when a worker died while processing (e.g. PC switched off).
create or replace function public.requeue_stale_calls(max_minutes int default 15) returns int
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update public.calls set status = 'queued', queued_at = now()
   where status = 'processing' and started_at < now() - make_interval(mins => max_minutes);
  get diagnostics n = row_count;
  return n;
end;
$$;

revoke all on function public.claim_next_call()          from public, anon, authenticated;
revoke all on function public.requeue_stale_calls(int)   from public, anon, authenticated;
grant execute on function public.claim_next_call()        to service_role;
grant execute on function public.requeue_stale_calls(int) to service_role;

-- ---------------------------------------------------------------- row level security
alter table public.allowed_users enable row level security;   -- no policies: only the service role can read it
alter table public.farmers       enable row level security;
alter table public.calls         enable row level security;
alter table public.call_results  enable row level security;
alter table public.chat_messages enable row level security;

drop policy if exists farmers_all on public.farmers;
create policy farmers_all on public.farmers for all to authenticated
  using (public.is_allowed()) with check (public.is_allowed());

drop policy if exists calls_all on public.calls;
create policy calls_all on public.calls for all to authenticated
  using (public.is_allowed()) with check (public.is_allowed());

-- results are written by the worker (service role); users can only read them
drop policy if exists results_read on public.call_results;
create policy results_read on public.call_results for select to authenticated
  using (public.is_allowed());

drop policy if exists chat_read on public.chat_messages;
create policy chat_read on public.chat_messages for select to authenticated
  using (public.is_allowed() and user_id = auth.uid());
drop policy if exists chat_write on public.chat_messages;
create policy chat_write on public.chat_messages for insert to authenticated
  with check (public.is_allowed() and user_id = auth.uid());

-- ---------------------------------------------------------------- private storage bucket for recordings
insert into storage.buckets (id, name, public, file_size_limit)
values ('recordings', 'recordings', false, 52428800)       -- private, 50 MB per file
on conflict (id) do nothing;

drop policy if exists recordings_read on storage.objects;
create policy recordings_read on storage.objects for select to authenticated
  using (bucket_id = 'recordings' and public.is_allowed());
drop policy if exists recordings_insert on storage.objects;
create policy recordings_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'recordings' and public.is_allowed());
drop policy if exists recordings_delete on storage.objects;
create policy recordings_delete on storage.objects for delete to authenticated
  using (bucket_id = 'recordings' and public.is_allowed());

-- ---------------------------------------------------------------- live status updates in the browser
do $$
begin
  alter publication supabase_realtime add table public.calls;
exception when duplicate_object then null;
end $$;

-- ---------------------------------------------------------------- first user  (EDIT THE EMAIL)
insert into public.allowed_users (email) values ('YOUR_LOGIN_EMAIL')
on conflict (email) do nothing;
