-- Migration 004: choose the AI model when evaluating a call (from the website).
-- Run once in Supabase -> SQL Editor. Safe to run again.
-- null / empty = Auto (the worker's main model, then its backups).
alter table public.calls add column if not exists requested_model text;
