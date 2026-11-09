"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import UploadPanel from "@/components/UploadPanel";
import { btn, CallProgress, queueCall, StatusChip, useNow } from "@/components/ui";
import { supabaseBrowser } from "@/lib/supabase/client";
import { callLabel, fmtDateTime, fmtDuration } from "@/lib/format";
import type { Call } from "@/lib/types";

type Filter = "all" | "uploaded" | "active" | "done" | "failed";

export default function CallsPage() {
  const sb = useMemo(() => supabaseBrowser(), []);
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data, error } = await sb.from("calls").select("*").order("created_at", { ascending: false }).limit(500);
    if (error) setNote(`Could not load calls: ${error.message}`);
    else setCalls((data ?? []) as Call[]);
    setLoading(false);
  }, [sb]);

  useEffect(() => {
    load();
    const channel = sb
      .channel("calls-live")
      .on("postgres_changes", { event: "*", schema: "public", table: "calls" }, (p) => {
        if (p.eventType === "DELETE") setCalls((cur) => cur.filter((c) => c.id !== (p.old as Call).id));
        else {
          const row = p.new as Call;
          setCalls((cur) => (cur.some((c) => c.id === row.id) ? cur.map((c) => (c.id === row.id ? { ...c, ...row } : c)) : [row, ...cur]));
        }
      })
      .subscribe();
    return () => { sb.removeChannel(channel); };
  }, [sb, load]);

  const busy = calls.some((c) => c.status === "queued" || c.status === "processing");
  // safety net in case the live connection drops: refresh every 4 s while something is running
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [busy, load]);
  const now = useNow(busy);

  const queuedSince = calls.filter((c) => c.status === "queued").map((c) => new Date(c.queued_at ?? c.created_at).getTime());
  const workerIdle = queuedSince.length > 0 && !calls.some((c) => c.status === "processing") && now - Math.min(...queuedSince) > 45000;

  async function evaluate(c: Call) {
    if (c.status === "done" && !confirm("This call is already evaluated. Evaluate it again and replace the results?")) return;
    const err = await queueCall(sb, c.id);
    if (err) setNote(`Could not start: ${err.message}`);
    else setCalls((cur) => cur.map((x) => (x.id === c.id ? { ...x, status: "queued", progress: 0, stage: null, error: null } : x)));
  }

  async function evaluateAll() {
    const todo = calls.filter((c) => c.status === "uploaded");
    for (const c of todo) await queueCall(sb, c.id);
    load();
  }

  async function remove(c: Call) {
    if (!confirm(`Delete ${callLabel(c)} and its results? This cannot be undone.`)) return;
    await sb.storage.from("recordings").remove([c.storage_path]);
    const { error } = await sb.from("calls").delete().eq("id", c.id);
    if (error) setNote(error.message);
  }

  const counts = {
    all: calls.length,
    uploaded: calls.filter((c) => c.status === "uploaded").length,
    active: calls.filter((c) => c.status === "queued" || c.status === "processing").length,
    done: calls.filter((c) => c.status === "done").length,
    failed: calls.filter((c) => c.status === "failed").length,
  };
  const shown = calls.filter((c) => {
    if (filter === "active" ? !(c.status === "queued" || c.status === "processing") : filter !== "all" && c.status !== filter) return false;
    const q = search.trim().toLowerCase();
    return !q || c.phone.includes(q) || c.file_name.toLowerCase().includes(q) || (c.call_date ?? "none").includes(q);
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Calls</h1>
        <p className="text-slate-500">Upload recordings, press <b>Evaluate</b>, then open a call to see the conversation, fields and AI analysis.</p>
      </div>

      <UploadPanel onUploaded={load} />

      {note && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{note} <button className="ml-2 underline" onClick={() => setNote(null)}>dismiss</button></div>}
      {workerIdle && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <b>Waiting for the analysis worker.</b> No worker has picked up the queued call(s) yet. On the computer that runs it, start:
          <code className="ml-1 rounded bg-white px-1.5 py-0.5 text-xs">python -m call_pipeline worker</code>
        </div>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
          <div className="flex flex-wrap gap-1">
            {([["all", "All"], ["uploaded", "Not evaluated"], ["active", "In progress"], ["done", "Evaluated"], ["failed", "Failed"]] as [Filter, string][]).map(([k, label]) => (
              <button
                key={k} onClick={() => setFilter(k)}
                className={`rounded-full px-3 py-1 text-sm ${filter === k ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
              >
                {label} <span className="opacity-70">{counts[k]}</span>
              </button>
            ))}
          </div>
          <input
            value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search phone, date or file…"
            className="ml-auto w-60 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-emerald-500"
          />
          <button className={btn.primary} disabled={counts.uploaded === 0} onClick={evaluateAll}>
            Evaluate all not evaluated ({counts.uploaded})
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Farmer phone</th><th className="px-4 py-2">Call date</th><th className="px-4 py-2">File</th>
                <th className="px-4 py-2">Length</th><th className="px-4 py-2">Status</th><th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400"><span className="spinner" /> Loading…</td></tr>}
              {!loading && shown.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-slate-400">{calls.length === 0 ? "No calls yet. Drop a recording above to start." : "No calls match this filter."}</td></tr>
              )}
              {shown.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50/70">
                  <td className="px-4 py-3 font-medium">
                    <Link href={`/calls/${c.id}`} className="hover:text-emerald-700 hover:underline">{c.phone}</Link>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{c.call_date ?? <span className="text-slate-400">none</span>}{c.call_seq > 1 && <span className="ml-1 text-slate-400">({c.call_seq})</span>}</td>
                  <td className="max-w-[240px] truncate px-4 py-3 text-slate-500" title={c.file_name}>{c.file_name}</td>
                  <td className="px-4 py-3 tabular-nums text-slate-500">{fmtDuration(c.duration_seconds)}</td>
                  <td className="px-4 py-3">
                    {c.status === "queued" || c.status === "processing" ? (
                      <CallProgress call={c} now={now} />
                    ) : (
                      <div>
                        <StatusChip status={c.status} />
                        {c.status === "done" && <div className="mt-0.5 text-xs text-slate-400">{fmtDateTime(c.finished_at)}</div>}
                        {c.status === "failed" && <div className="mt-0.5 max-w-[260px] truncate text-xs text-red-600" title={c.error ?? ""}>{c.error}</div>}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {c.status === "done" && <Link href={`/calls/${c.id}`} className={`${btn.secondary} mr-2 inline-block`}>View details</Link>}
                    {(c.status === "uploaded" || c.status === "failed") && <button className={`${btn.primary} mr-2`} onClick={() => evaluate(c)}>{c.status === "failed" ? "Retry" : "Evaluate"}</button>}
                    {c.status === "done" && <button className={btn.secondary} onClick={() => evaluate(c)}>Re-evaluate</button>}
                    {(c.status === "uploaded" || c.status === "done" || c.status === "failed") && <button className={`${btn.danger} ml-1`} onClick={() => remove(c)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
