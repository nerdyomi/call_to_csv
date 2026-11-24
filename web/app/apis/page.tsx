"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { btn, Card } from "@/components/ui";
import { ago, compact, money, quotaDay, shownStatus, typicalCallCost, usedToday, type KeyModelRow, type ModelInfo, type Tone } from "@/lib/apiStatus";
import { supabaseBrowser } from "@/lib/supabase/client";

const TONE: Record<Tone, string> = {
  good: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warn: "bg-amber-50 text-amber-800 ring-amber-200",
  bad: "bg-red-50 text-red-800 ring-red-200",
  idle: "bg-slate-100 text-slate-600 ring-slate-200",
};
const DOT: Record<Tone, string> = { good: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500", idle: "bg-slate-300" };

// Providers that will be added later. Only Gemini keys are tracked today.
const PROVIDERS: { id: string; label: string; ready: boolean }[] = [
  { id: "gemini", label: "Gemini (Google)", ready: true },
  { id: "openai", label: "OpenAI", ready: false },
  { id: "groq", label: "Groq", ready: false },
  { id: "grok", label: "Grok (xAI)", ready: false },
];

export default function ApisPage() {
  const sb = useMemo(() => supabaseBrowser(), []);
  const [provider, setProvider] = useState("gemini");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [rows, setRows] = useState<KeyModelRow[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    const [m, k] = await Promise.all([
      sb.from("api_models").select("*").eq("provider", "gemini"),
      sb.from("api_key_status").select("*").eq("provider", "gemini").order("slot"),
    ]);
    if (m.error || k.error) setError(m.error?.message ?? k.error?.message ?? null);
    else setError(null);
    const ms = ((m.data ?? []) as ModelInfo[]).sort((a, b) => Number(b.in_chain) - Number(a.in_chain) || a.model.localeCompare(b.model));
    setModels(ms);
    setRows((k.data ?? []) as KeyModelRow[]);
    setModel((cur) => cur ?? ms[0]?.model ?? null);
    setNow(Date.now());
    setLoading(false);
  }, [sb]);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const today = quotaDay();
  const info = models.find((m) => m.model === model);
  const slots = useMemo(() => {
    const seen = new Map<number, KeyModelRow>();
    rows.forEach((r) => { if (!seen.has(r.slot)) seen.set(r.slot, r); });
    return [...seen.values()].sort((a, b) => a.slot - b.slot);
  }, [rows]);
  const forModel = (slot: number) => rows.find((r) => r.slot === slot && r.model === model);
  const summary = slots.map((s) => shownStatus(forModel(s.slot), today));
  const ready = summary.filter((s) => s.tone === "good").length;
  const cost = info ? typicalCallCost(info) : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-2xl font-semibold">API status</h1>
          <p className="text-slate-500">Which keys work, per model. Keys themselves are never shown here, only the last 4 characters.</p>
        </div>
        <button className={`${btn.secondary} ml-auto`} onClick={load}>Refresh</button>
      </div>

      <div className="flex flex-wrap gap-2">
        {PROVIDERS.map((p) => (
          <button
            key={p.id} disabled={!p.ready} onClick={() => setProvider(p.id)}
            className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition ${provider === p.id ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"} disabled:cursor-not-allowed disabled:opacity-50`}
            title={p.ready ? "" : "Not connected yet"}
          >
            {p.label}{!p.ready && <span className="ml-1.5 text-xs font-normal">soon</span>}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load the status: {error}. If this is the first time, run <code>supabase/migrations/003_api_status.sql</code> in Supabase.
        </div>
      )}

      {!loading && !error && slots.length === 0 && (
        <Card>
          <p className="py-6 text-center text-slate-500">
            Nothing reported yet. Start (or restart) the worker with <code className="rounded bg-slate-100 px-1">python -m call_pipeline worker</code>; it lists every key from your <code className="rounded bg-slate-100 px-1">.env</code> here.
          </p>
        </Card>
      )}

      {models.length > 0 && (
        <>
          <Card title="Model">
            <div className="flex flex-wrap gap-2">
              {models.map((m) => (
                <button
                  key={m.model} onClick={() => setModel(m.model)}
                  className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${model === m.model ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}
                >
                  {m.model}
                  {m.in_chain && <span className="ml-1.5 rounded bg-slate-100 px-1 text-[10px] font-normal uppercase text-slate-500">in use</span>}
                </button>
              ))}
            </div>

            {info && (
              <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <Fact title="Price per 1M tokens (USD)">
                  <div>Text in: <b>{money(info.input_per_m)}</b></div>
                  <div>Audio in: <b>{money(info.audio_per_m)}</b></div>
                  <div>Output: <b>{money(info.output_per_m)}</b></div>
                </Fact>
                <Fact title="About one evaluation">
                  {cost === null ? <span className="text-slate-500">Price not set</span> : (
                    <>
                      <div><b>${cost.toFixed(3)}</b> for a 5-minute call</div>
                      <div className="text-xs text-slate-500">if you were on the paid plan (about {Math.round(cost * 122 * 100) / 100} BDT)</div>
                    </>
                  )}
                </Fact>
                <Fact title="Free tier">
                  <div>
                    {info.free_available === true ? <b className="text-emerald-700">Available</b>
                      : info.free_available === false ? <b className="text-red-700">Not available</b>
                      : <b className="text-slate-600">Not checked</b>}
                  </div>
                  <div>Requests per day: <b>{info.free_rpd ?? "not set"}</b></div>
                  <div>Per minute: <b>{info.free_rpm ?? "not set"}</b> · tokens/min: <b>{info.free_tpm ?? "not set"}</b></div>
                </Fact>
                <Fact title="Good to know">
                  <div className="text-slate-600">{info.note ?? "No note."}</div>
                  <div className="mt-1 text-xs text-slate-400">Numbers come from config/pricing.yaml: verify them on Google&apos;s pricing page.</div>
                </Fact>
              </div>
            )}
          </Card>

          <Card
            title={`API keys for ${model ?? ""}`}
            right={slots.length > 0 && <span className="text-sm text-slate-500"><b className="text-emerald-700">{ready}</b> of {slots.length} working right now</span>}
          >
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr><th className="px-3 py-2">Key</th><th className="px-3 py-2">Variable in .env</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Last seen</th><th className="px-3 py-2">Used today (estimate)</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {slots.map((s) => {
                    const r = forModel(s.slot);
                    const st = shownStatus(r, today);
                    const used = usedToday(r, today);
                    const limit = info?.free_rpd ?? null;
                    const pct = limit ? Math.min(100, (used.requests / limit) * 100) : 0;
                    return (
                      <tr key={s.slot} className="align-top">
                        <td className="whitespace-nowrap px-3 py-3 font-medium">
                          api{s.slot} <span className="font-mono text-xs font-normal text-slate-400">…{s.key_tail}</span>
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-slate-500">{s.env_name}</td>
                        <td className="px-3 py-3">
                          <span title={st.hint} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE[st.tone]}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${DOT[st.tone]}`} />{st.label}
                          </span>
                          {r?.detail && st.tone !== "good" && <div className="mt-1 max-w-[320px] truncate text-xs text-slate-400" title={r.detail}>{r.detail}</div>}
                        </td>
                        <td className="whitespace-nowrap px-3 py-3 text-slate-600">
                          {ago(r?.last_seen_at, now)}
                          {r?.last_ok_at && r.status !== "ok" && <div className="text-xs text-slate-400">last worked {ago(r.last_ok_at, now)}</div>}
                        </td>
                        <td className="min-w-[200px] px-3 py-3">
                          <div className="tabular-nums">
                            <b>{used.requests}</b>{limit ? ` of ~${limit} requests` : " requests"} · {compact(used.tokens)} tokens
                          </div>
                          {limit ? (
                            <div className="mt-1 h-1.5 w-40 overflow-hidden rounded-full bg-slate-200">
                              <div className={`h-full rounded-full ${pct >= 90 ? "bg-red-500" : pct >= 60 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${pct}%` }} />
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <ul className="mt-4 space-y-1 text-xs text-slate-500">
              <li>Status is learned from real evaluations (&quot;last seen&quot;); nothing is tested in the background, so no quota is spent.</li>
              <li>A request counts as one whatever its size, but the per-minute token limit is separate. Keys from the same Google project share one quota.</li>
              <li>Daily quotas reset at midnight Pacific time. Counts only include calls made by your worker, so they are an estimate. Today&apos;s quota day: {today}.</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

function Fact({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      {children}
    </div>
  );
}
