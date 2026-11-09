-- Migration 002: progress bar + behaviour analysis.
-- Run once in Supabase -> SQL Editor. Safe to run again.

-- live progress while the worker analyses a call
alter table public.calls
  add column if not exists stage    text,
  add column if not exists progress int not null default 0;

do $$
begin
  alter table public.calls add constraint calls_progress_range check (progress between 0 and 100);
exception when duplicate_object then null;
end $$;

-- AI behaviour analysis of the farmer (generated from the transcript, cached here)
alter table public.call_results
  add column if not exists behaviour       jsonb,
  add column if not exists behaviour_model text,
  add column if not exists behaviour_at    timestamptz;
