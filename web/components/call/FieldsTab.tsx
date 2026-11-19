"use client";

import { Fragment, useMemo, useState } from "react";
import { Confidence } from "@/components/ui";
import { formOrder, question, questionLabel, valueLabel } from "@/lib/formLabels";
import type { CallResult } from "@/lib/types";

type Mode = "form" | "certainty";

const SECTION_TITLE: Record<string, string> = {
  "Loan Purpose": "Loan purpose",
  "Household Assets": "Household and land",
  "Crop Details": "Crop details (this loan)",
  Livestock: "Livestock (this loan)",
  "Other Farming Activity": "Other crops grown",
  "Other Farming Activity Livestock": "Other livestock",
  "Loan Details": "Running loans",
  "Cow management & health": "Cow management and health",
  "Income & Expense": "Income and expenses",
  "MF Relation": "Market facilitator",
  Calculated: "Calculated by the system",
};

const ROW_TINT: Record<string, string> = {
  low: "border-l-red-400 bg-red-50/40",
  medium: "border-l-amber-400 bg-amber-50/40",
};

export default function FieldsTab({ result, onSeek, playingStamp }: { result: CallResult; onSeek: (t: string) => void; playingStamp: string | null }) {
  const [q, setQ] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);
  const [mode, setMode] = useState<Mode>("form");

  const rows = useMemo(() => {
    const certainty = { low: 0, medium: 1, high: 2, calculated: 3 } as Record<string, number>;
    return Object.entries(result.fields)
      .map(([name, value]) => ({ name, value, ev: result.evidence?.[name], section: question(name)?.section ?? "Older field names" }))
      .filter((r) => !onlyReview || (r.ev && r.ev.confidence !== "high" && r.ev.confidence !== "calculated"))
      .filter((r) => !q || `${r.name} ${r.value} ${questionLabel(r.name)} ${valueLabel(r.name, r.value)} ${r.ev?.evidence ?? ""}`.toLowerCase().includes(q.toLowerCase()))
      .sort((a, b) =>
        mode === "form"
          ? formOrder(a.name) - formOrder(b.name)
          : (certainty[a.ev?.confidence ?? "high"] - certainty[b.ev?.confidence ?? "high"]) || formOrder(a.name) - formOrder(b.name),
      );
  }, [result, q, onlyReview, mode]);

  const attention = rows.filter((r) => r.ev?.confidence === "low" || r.ev?.confidence === "medium").length;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
        <input
          value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search question, answer or evidence…"
          className="w-72 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-emerald-500"
        />
        <div className="inline-flex overflow-hidden rounded-lg border border-slate-300 text-sm">
          {([["form", "In form order"], ["certainty", "Least certain first"]] as [Mode, string][]).map(([k, label]) => (
            <button
              key={k} onClick={() => setMode(k)}
              className={`px-3 py-1.5 ${mode === k ? "bg-emerald-600 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={onlyReview} onChange={(e) => setOnlyReview(e.target.checked)} /> Only medium / low confidence
        </label>
        <span className="ml-auto text-sm text-slate-500">
          {rows.length} of {Object.keys(result.fields).length} answers
          {attention > 0 && <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-800">{attention} worth a listen</span>}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-4 py-2">Question</th><th className="px-4 py-2">Answer</th><th className="px-4 py-2">Confidence</th><th className="px-4 py-2">Time</th><th className="px-4 py-2">What the farmer said</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const newSection = mode === "form" && (i === 0 || rows[i - 1].section !== r.section);
              const count = newSection ? rows.filter((x) => x.section === r.section).length : 0;
              return (
                <Fragment key={r.name}>
                  {newSection && (
                    <tr className="bg-slate-50">
                      <td colSpan={5} className="border-y border-slate-200 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                        {SECTION_TITLE[r.section] ?? r.section} <span className="ml-1 font-normal normal-case text-slate-400">· {count} answer{count === 1 ? "" : "s"}</span>
                      </td>
                    </tr>
                  )}
                  <tr className={`align-top border-b border-slate-100 border-l-4 hover:bg-slate-50/70 ${ROW_TINT[r.ev?.confidence ?? ""] ?? "border-l-transparent"}`}>
                    <td className="max-w-[360px] px-4 py-2">
                      <div className="text-[15px] leading-snug text-slate-800">{questionLabel(r.name) || r.name}</div>
                      <div className="font-mono text-xs text-slate-400">{r.name}</div>
                    </td>
                    <td className="px-4 py-2 font-semibold">
                      {valueLabel(r.name, r.value)}
                      {valueLabel(r.name, r.value) !== r.value && <div className="font-mono text-xs font-normal text-slate-400">{r.value}</div>}
                    </td>
                    <td className="px-4 py-2">{r.ev ? <Confidence level={r.ev.confidence} /> : "–"}</td>
                    <td className="px-4 py-2">
                      {r.ev?.timestamp ? <button className="font-mono text-xs text-emerald-700 hover:underline" onClick={() => onSeek(r.ev!.timestamp)} title={playingStamp === r.ev.timestamp ? "Pause" : "Play from here"}>{playingStamp === r.ev.timestamp ? "⏸ pause" : `▶ ${r.ev.timestamp}`}</button> : "–"}
                    </td>
                    <td className="max-w-[420px] px-4 py-2 text-slate-600">{r.ev?.confidence === "calculated" && <span className="mr-1 text-xs font-medium text-slate-400">calculated:</span>}{r.ev?.evidence}</td>
                  </tr>
                </Fragment>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No answers match.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
