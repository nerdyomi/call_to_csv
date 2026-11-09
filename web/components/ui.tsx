"use client";

import { useEffect, useState } from "react";
import { STAGE_LABEL } from "@/lib/format";
import type { Call, CallStatus } from "@/lib/types";

const CHIP: Record<CallStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700 ring-slate-200",
  queued: "bg-amber-50 text-amber-800 ring-amber-200",
  processing: "bg-sky-50 text-sky-800 ring-sky-200",
  done: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  failed: "bg-red-50 text-red-800 ring-red-200",
};
const CHIP_LABEL: Record<CallStatus, string> = {
  uploaded: "Uploaded",
  queued: "Waiting in queue",
  processing: "Evaluating",
  done: "Evaluated",
  failed: "Failed",
};

export function StatusChip({ status }: { status: CallStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${CHIP[status]}`}>
      {CHIP_LABEL[status]}
    </span>
  );
}

/** Re-renders every second while `active`, so elapsed-time labels tick. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export function elapsed(since: string | null | undefined, now: number): string {
  if (!since) return "";
  const s = Math.max(0, Math.round((now - new Date(since).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Live bar for an evaluating call: real percentage while the transcript is written, striped while the AI thinks. */
export function CallProgress({ call, now }: { call: Call; now: number }) {
  const pct = Math.max(0, Math.min(100, call.progress ?? 0));
  const thinking = call.status === "processing" && (call.stage === "thinking" || call.stage === "downloading" || pct <= 10);
  const label =
    call.status === "queued"
      ? "Waiting for the analysis worker…"
      : STAGE_LABEL[call.stage ?? ""] ?? "Evaluating";
  return (
    <div className="min-w-[220px]">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="tabular-nums text-slate-500">
          {call.status === "processing" ? `${pct}%` : ""}
          {call.status === "processing" && call.started_at ? ` · ${elapsed(call.started_at, now)}` : ""}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full rounded-full bg-emerald-500 transition-all duration-700 ${thinking || call.status === "queued" ? "bar-indeterminate" : ""}`}
          style={{ width: call.status === "queued" ? "8%" : `${Math.max(pct, 4)}%` }}
        />
      </div>
    </div>
  );
}

export function Card({ title, children, right }: { title?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export const btn = {
  primary: "rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50",
  secondary: "rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50",
  danger: "rounded-lg px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50",
  link: "text-sm font-medium text-emerald-700 hover:underline",
};

export function Confidence({ level }: { level: string }) {
  const cls = level === "high" ? "bg-emerald-50 text-emerald-700" : level === "medium" ? "bg-amber-50 text-amber-800" : "bg-red-50 text-red-700";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{level}</span>;
}

/** Queues a call for the worker. Falls back gracefully when migration 002 (progress columns) has not been run. */
export async function queueCall(sb: ReturnType<typeof import("@/lib/supabase/client").supabaseBrowser>, id: string) {
  const base = { status: "queued", queued_at: new Date().toISOString(), error: null };
  let { error } = await sb.from("calls").update({ ...base, progress: 0, stage: null }).eq("id", id);
  if (error) ({ error } = await sb.from("calls").update(base).eq("id", id));
  return error;
}
