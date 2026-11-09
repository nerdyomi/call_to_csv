"use client";

import { Card } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";
import type { Call, CallResult } from "@/lib/types";

const FACTS: [string, string][] = [
  ["loan_amount", "Loan wanted (BDT)"],
  ["current_landsize", "Land cultivated (decimals)"],
  ["own", "Own land (decimals)"],
  ["lease_mortgage", "Leased / mortgaged (decimals)"],
  ["invest", "Investment (BDT)"],
  ["yield", "Yield (kg)"],
  ["unit_price", "Unit price (BDT)"],
  ["number_of_dependents", "Dependents"],
  ["monthly_expenses", "Monthly expenses (BDT)"],
  ["current_loan_count", "Farmer's running loans"],
  ["current_spouse_loan_count", "Spouse's running loans"],
  ["income_from_agriculture", "Yearly farm income (BDT)"],
  ["income_from_business", "Yearly business income (BDT)"],
];

const KIND_LABEL: Record<string, string> = {
  low_confidence: "Low confidence", warning: "Warning", invalid_value: "Invalid value",
  unknown_code: "New value", duplicate: "Duplicate", not_in_schema: "Unknown field",
};

export default function SummaryTab({ call, result }: { call: Call; result: CallResult }) {
  const facts = FACTS.filter(([k]) => result.fields[k] !== undefined);
  const a = result.assessment;
  const usage = (result.usage ?? {}) as Record<string, number | string>;
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card title="Summary">
          <p className="text-[15px] leading-relaxed text-slate-800">{result.eng_notes || "No summary."}</p>
          {result.notes && (
            <details className="mt-3">
              <summary className="cursor-pointer text-sm text-slate-500">Banglish version (as the CEX team writes it)</summary>
              <p className="mt-2 rounded-lg bg-slate-50 p-3 text-sm leading-relaxed text-slate-700">{result.notes}</p>
            </details>
          )}
        </Card>

        <Card title="Key facts">
          {facts.length === 0 ? <p className="text-sm text-slate-500">No key facts were extracted.</p> : (
            <dl className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {facts.map(([k, label]) => (
                <div key={k} className="rounded-xl bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">{label}</dt>
                  <dd className="mt-0.5 text-lg font-semibold tabular-nums">{Number(result.fields[k]).toLocaleString("en-US") === "NaN" ? result.fields[k] : Number(result.fields[k]).toLocaleString("en-US")}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-3 text-xs text-slate-400">{Object.keys(result.fields).length} fields were filled in total — see the “Fields” tab.</p>
        </Card>
      </div>

      <div className="space-y-6">
        <Card title="Call quality">
          <ul className="space-y-2 text-sm">
            <li className="flex justify-between"><span className="text-slate-500">Audio quality</span><b className="capitalize">{a?.audio_quality ?? "–"}</b></li>
            <li className="flex justify-between"><span className="text-slate-500">KYC call</span><b>{a?.is_kyc_call === false ? "No" : "Yes"}</b></li>
            <li className="flex justify-between"><span className="text-slate-500">Farmer answered</span><b className="capitalize">{a?.respondent_is_farmer ?? "–"}</b></li>
            {a?.language_note && <li className="text-slate-600">{a.language_note}</li>}
          </ul>
        </Card>

        <Card title={`Needs a human look (${result.review.length})`}>
          {result.review.length === 0 ? <p className="text-sm text-slate-500">Nothing flagged.</p> : (
            <ul className="space-y-2">
              {result.review.map((r, i) => (
                <li key={i} className="rounded-lg bg-amber-50 p-2.5 text-sm text-amber-900">
                  <span className="mr-1 rounded bg-amber-200/70 px-1.5 py-0.5 text-xs font-medium">{KIND_LABEL[r.kind] ?? r.kind}</span>
                  {r.field && <b className="mr-1">{r.field}:</b>}{r.detail}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Technical">
          <ul className="space-y-1 text-xs text-slate-500">
            <li>Model: {result.model ?? call.model ?? "–"}</li>
            <li>Evaluated: {fmtDateTime(result.updated_at)}</li>
            {usage.prompt_tokens !== undefined && <li>Tokens: {String(usage.prompt_tokens)} in · {String(usage.output_tokens)} out · {String(usage.thought_tokens ?? 0)} thinking</li>}
            <li>File: {call.file_name}</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
