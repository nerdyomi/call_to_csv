"use client";

import { useEffect, useState } from "react";
import { btn, Card } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";
import type { Behaviour, CallResult } from "@/lib/types";

const LEVEL_STYLE: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-800", consistent: "bg-emerald-50 text-emerald-800",
  medium: "bg-amber-50 text-amber-800", mostly_consistent: "bg-amber-50 text-amber-800",
  low: "bg-red-50 text-red-800", inconsistent: "bg-red-50 text-red-800",
};
const pretty = (s: string) => s.replace(/_/g, " ");

function Trait({ title, level, why }: { title: string; level: string; why: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${LEVEL_STYLE[level] ?? "bg-slate-100"}`}>{pretty(level)}</span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-slate-600">{why}</p>
    </div>
  );
}

export default function BehaviourTab({ callId, result, onSeek }: { callId: string; result: CallResult; onSeek: (t: string) => void }) {
  const [b, setB] = useState<Behaviour | null>(result.behaviour ?? null);
  const [model, setModel] = useState<string | null>(result.behaviour_model ?? null);
  const [at, setAt] = useState<string | null>(result.behaviour_at ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  async function generate(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/behaviour", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ callId, force }) });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `Request failed (${res.status})`);
      setB(j.behaviour);
      setModel(j.model ?? null);
      setAt(new Date().toISOString());
      setWarning(j.warning ?? null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // first visit: generate automatically
  useEffect(() => { if (!b) generate(false); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  if (!b) {
    return (
      <Card>
        <div className="py-8 text-center">
          {busy ? <><span className="spinner" /> <span className="ml-2 text-slate-600">AI is reading the conversation…</span></> : (
            <>
              {error && <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">⚠ {error}</p>}
              <button className={btn.primary} onClick={() => generate(false)}>Generate behaviour analysis</button>
            </>
          )}
        </div>
      </Card>
    );
  }

  const Points = ({ items, tone }: { items: Behaviour["red_flags"]; tone: "red" | "green" }) => (
    items.length === 0 ? <p className="text-sm text-slate-500">None found.</p> : (
      <ul className="space-y-2">
        {items.map((p, i) => (
          <li key={i} className={`rounded-lg p-2.5 text-sm ${tone === "red" ? "bg-red-50 text-red-900" : "bg-emerald-50 text-emerald-900"}`}>
            {p.point}
            {p.time && <button className="ml-2 font-mono text-xs underline" onClick={() => onSeek(p.time)}>▶ {p.time}</button>}
          </li>
        ))}
      </ul>
    )
  );

  return (
    <div className="space-y-6">
      <Card
        title="Behaviour of the farmer in this call"
        right={<button className={btn.secondary} disabled={busy} onClick={() => generate(true)}>{busy ? "Working…" : "Regenerate"}</button>}
      >
        <p className="text-[15px] leading-relaxed text-slate-800">{b.overall}</p>
        <p className="mt-2 text-sm text-slate-500"><b>Tone:</b> {b.tone}</p>
        {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">⚠ {error}</p>}
        {warning && <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{warning}</p>}
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Trait title="Cooperation" level={b.cooperation.level} why={b.cooperation.why} />
        <Trait title="Consistency" level={b.consistency.level} why={b.consistency.why} />
        <Trait title="Sureness of answers" level={b.confidence_in_answers.level} why={b.confidence_in_answers.why} />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Points to look at"><Points items={b.red_flags} tone="red" /></Card>
        <Card title="Positive signs"><Points items={b.positives} tone="green" /></Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Financial stress signals">
          {b.financial_stress_signals.length === 0 ? <p className="text-sm text-slate-500">None found.</p> : (
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{b.financial_stress_signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
          )}
        </Card>
        <Card title="Suggested follow-up questions">
          {b.follow_up_questions.length === 0 ? <p className="text-sm text-slate-500">None.</p> : (
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{b.follow_up_questions.map((s, i) => <li key={i}>{s}</li>)}</ul>
          )}
        </Card>
      </div>

      <p className="text-xs text-slate-400">
        Written by AI ({model ?? "Groq"}, {fmtDateTime(at)}) from this call only. It describes how the farmer behaved in the call; it is not a credit decision. Please verify against the conversation.
      </p>
    </div>
  );
}
