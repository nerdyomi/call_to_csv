"use client";

import { useMemo, useState } from "react";
import { Confidence } from "@/components/ui";
import type { CallResult } from "@/lib/types";

export default function FieldsTab({ result, onSeek }: { result: CallResult; onSeek: (t: string) => void }) {
  const [q, setQ] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);

  const rows = useMemo(() => {
    const order = { low: 0, medium: 1, high: 2 } as Record<string, number>;
    return Object.entries(result.fields)
      .map(([name, value]) => ({ name, value, ev: result.evidence?.[name] }))
      .filter((r) => (!onlyReview || (r.ev && r.ev.confidence !== "high")))
      .filter((r) => !q || `${r.name} ${r.value} ${r.ev?.evidence ?? ""}`.toLowerCase().includes(q.toLowerCase()))
      .sort((a, b) => (order[a.ev?.confidence ?? "high"] - order[b.ev?.confidence ?? "high"]) || a.name.localeCompare(b.name));
  }, [result, q, onlyReview]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
        <input
          value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search field, value or evidence…"
          className="w-72 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-emerald-500"
        />
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={onlyReview} onChange={(e) => setOnlyReview(e.target.checked)} /> Only medium / low confidence
        </label>
        <span className="ml-auto text-sm text-slate-500">{rows.length} of {Object.keys(result.fields).length} fields · least certain first</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-4 py-2">Field</th><th className="px-4 py-2">Value</th><th className="px-4 py-2">Confidence</th><th className="px-4 py-2">Time</th><th className="px-4 py-2">What the farmer said</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => (
              <tr key={r.name} className="align-top hover:bg-slate-50/70">
                <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-slate-600">{r.name}</td>
                <td className="px-4 py-2 font-semibold">{r.value}</td>
                <td className="px-4 py-2">{r.ev ? <Confidence level={r.ev.confidence} /> : "–"}</td>
                <td className="px-4 py-2">
                  {r.ev?.timestamp ? <button className="font-mono text-xs text-emerald-700 hover:underline" onClick={() => onSeek(r.ev!.timestamp)} title="Play from here">▶ {r.ev.timestamp}</button> : "–"}
                </td>
                <td className="max-w-[420px] px-4 py-2 text-slate-600">{r.ev?.evidence}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No fields match.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
