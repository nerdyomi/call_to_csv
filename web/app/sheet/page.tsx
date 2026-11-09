"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { btn, StatusChip } from "@/components/ui";
import { supabaseBrowser } from "@/lib/supabase/client";
import { applyFilters, type Filter, type Row } from "@/lib/tools";
import type { CallStatus } from "@/lib/types";

interface SheetRow extends Row {
  status: CallStatus;
  reviewCount: number;
  model: string | null;
}

const DEFAULT_COLS = [
  "loan_amount", "current_landsize", "own", "lease_mortgage", "yield", "unit_price", "number_of_dependents",
  "monthly_expenses", "current_loan_count", "current_spouse_loan_count", "income_from_agriculture", "income_from_business",
];
const OPS: [string, string][] = [
  ["eq", "is"], ["neq", "is not"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"],
  ["contains", "contains"], ["nonempty", "is filled"], ["empty", "is empty"],
];
const PAGE = 50;

export default function SheetPage() {
  const sb = useMemo(() => supabaseBrowser(), []);
  const [rows, setRows] = useState<SheetRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [text, setText] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState<"all" | CallStatus>("all");
  const [flagged, setFlagged] = useState(false);
  const [fieldFilters, setFieldFilters] = useState<Filter[]>([]);
  const [visible, setVisible] = useState<string[] | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQ, setPickerQ] = useState("");
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 }>({ col: "date", dir: -1 });
  const [page, setPage] = useState(0);
  const [allColsExport, setAllColsExport] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    sb.from("calls").select("id,phone,call_date,call_seq,status,model,call_results(fields,review,notes,eng_notes)").order("created_at", { ascending: false }).limit(2000)
      .then(({ data, error }) => {
        if (error) setError(error.message);
        setRows(((data ?? []) as any[]).map((c) => {
          const r = Array.isArray(c.call_results) ? c.call_results[0] : c.call_results;
          return {
            id: c.id, phone: c.phone, date: c.call_date, seq: c.call_seq, status: c.status, model: c.model,
            fields: r?.fields ?? {}, notes: r?.notes ?? "", eng_notes: r?.eng_notes ?? "", reviewCount: (r?.review ?? []).length,
          } as SheetRow;
        }));
        setLoading(false);
      });
  }, [sb]);

  const fieldNames = useMemo(() => {
    const n = new Map<string, number>();
    rows.forEach((r) => Object.keys(r.fields).forEach((k) => n.set(k, (n.get(k) ?? 0) + 1)));
    return [...n].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k]) => k);
  }, [rows]);
  const cols = visible ?? DEFAULT_COLS.filter((c) => fieldNames.includes(c));

  const filtered = useMemo(() => {
    let out = rows.filter((r) => {
      if (status !== "all" && r.status !== status) return false;
      if (flagged && r.reviewCount === 0) return false;
      if (from && (!r.date || r.date < from)) return false;
      if (to && (!r.date || r.date > to)) return false;
      if (text) {
        const q = text.toLowerCase();
        if (!(r.phone.includes(q) || Object.values(r.fields).some((v) => v.toLowerCase().includes(q)) || r.eng_notes.toLowerCase().includes(q))) return false;
      }
      return true;
    });
    out = applyFilters(out, fieldFilters.filter((f) => f.field)) as SheetRow[];
    const val = (r: SheetRow) => (sort.col === "phone" ? r.phone : sort.col === "date" ? r.date ?? "" : sort.col === "status" ? r.status : sort.col === "review" ? r.reviewCount : r.fields[sort.col] ?? "");
    return [...out].sort((a, b) => {
      const x = val(a), y = val(b);
      const nx = Number(x), ny = Number(y);
      if (x !== "" && y !== "" && !Number.isNaN(nx) && !Number.isNaN(ny)) return (nx - ny) * sort.dir;
      return String(x).localeCompare(String(y)) * sort.dir;
    });
  }, [rows, status, flagged, from, to, text, fieldFilters, sort]);

  useEffect(() => setPage(0), [status, flagged, from, to, text, fieldFilters]);
  const pageRows = filtered.slice(page * PAGE, (page + 1) * PAGE);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));

  const head = (col: string, label: string) => (
    <th key={col} className="cursor-pointer select-none whitespace-nowrap px-3 py-2 hover:text-slate-800" onClick={() => setSort((s) => ({ col, dir: s.col === col ? (s.dir === 1 ? -1 : 1) : 1 }))}>
      {label} {sort.col === col ? (sort.dir === 1 ? "▲" : "▼") : ""}
    </th>
  );

  async function exportExcel() {
    setExporting(true);
    try {
      const ExcelJS = (await import("exceljs")).default;
      const wb = new ExcelJS.Workbook();
      const ws = wb.addWorksheet("Calls");
      const exportCols = allColsExport ? fieldNames : cols;
      ws.columns = [
        { header: "phone", key: "phone", width: 16 }, { header: "call_date", key: "date", width: 12 },
        { header: "call_no", key: "seq", width: 8 }, { header: "status", key: "status", width: 12 },
        { header: "review_flags", key: "review", width: 12 },
        ...exportCols.map((c) => ({ header: c, key: `f_${c}`, width: Math.max(12, Math.min(c.length + 2, 28)) })),
        { header: "summary", key: "summary", width: 60 },
      ];
      filtered.forEach((r) => {
        const row: Record<string, string | number | null> = { phone: r.phone, date: r.date ?? "none", seq: r.seq, status: r.status, review: r.reviewCount, summary: r.eng_notes };
        exportCols.forEach((c) => {
          const v = r.fields[c];
          row[`f_${c}`] = v === undefined ? null : v !== "" && !Number.isNaN(Number(v)) && /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v;
        });
        ws.addRow(row);
      });
      ws.getRow(1).font = { bold: true };
      ws.getRow(1).fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFD1FAE5" } };
      ws.views = [{ state: "frozen", ySplit: 1, xSplit: 2 }];
      ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: ws.columnCount } };
      const buf = await wb.xlsx.writeBuffer();
      const url = URL.createObjectURL(new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `ifarmer-calls-${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  const setFilter = (i: number, p: Partial<Filter>) => setFieldFilters((cur) => cur.map((f, j) => (j === i ? { ...f, ...p } : f)));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-2xl font-semibold">All calls sheet</h1>
          <p className="text-slate-500">Every call in one table. Filter, sort, choose columns, and download as Excel.</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-sm text-slate-600"><input type="checkbox" checked={allColsExport} onChange={(e) => setAllColsExport(e.target.checked)} /> all columns in Excel</label>
          <button className={btn.primary} disabled={exporting || filtered.length === 0} onClick={exportExcel}>{exporting ? "Preparing…" : `Download Excel (${filtered.length})`}</button>
        </div>
      </div>

      {error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-500">Search<input value={text} onChange={(e) => setText(e.target.value)} placeholder="phone, any value, summary…" className="mt-1 block w-60 rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900" /></label>
          <label className="text-xs text-slate-500">Call date from<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900" /></label>
          <label className="text-xs text-slate-500">to<input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900" /></label>
          <label className="text-xs text-slate-500">Status
            <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900">
              <option value="all">All</option><option value="done">Evaluated</option><option value="uploaded">Not evaluated</option>
              <option value="queued">Waiting</option><option value="processing">Evaluating</option><option value="failed">Failed</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 pb-2 text-sm text-slate-600"><input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} /> Only calls with review flags</label>
          <div className="relative ml-auto">
            <button className={btn.secondary} onClick={() => setPickerOpen((o) => !o)}>Columns ({cols.length})</button>
            {pickerOpen && (
              <div className="absolute right-0 z-20 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-lg">
                <input value={pickerQ} onChange={(e) => setPickerQ(e.target.value)} placeholder="Find a field…" className="mb-2 w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
                <div className="mb-2 flex gap-3 text-xs"><button className={btn.link} onClick={() => setVisible([])}>none</button><button className={btn.link} onClick={() => setVisible(fieldNames)}>all</button><button className={btn.link} onClick={() => setVisible(null)}>default</button></div>
                <div className="max-h-64 space-y-0.5 overflow-y-auto">
                  {fieldNames.filter((n) => n.includes(pickerQ.toLowerCase())).map((n) => (
                    <label key={n} className="flex items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-slate-50">
                      <input type="checkbox" checked={cols.includes(n)} onChange={(e) => setVisible(e.target.checked ? [...cols, n] : cols.filter((c) => c !== n))} /> <span className="font-mono text-xs">{n}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-2">
          {fieldFilters.map((f, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-500">Where</span>
              <select value={f.field} onChange={(e) => setFilter(i, { field: e.target.value })} className="rounded-lg border border-slate-300 px-2 py-1 text-sm">
                <option value="">choose a field…</option>
                {fieldNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <select value={f.op} onChange={(e) => setFilter(i, { op: e.target.value })} className="rounded-lg border border-slate-300 px-2 py-1 text-sm">
                {OPS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
              {f.op !== "empty" && f.op !== "nonempty" && (
                <input value={String(f.value ?? "")} onChange={(e) => setFilter(i, { value: e.target.value })} placeholder="value" className="w-40 rounded-lg border border-slate-300 px-2 py-1 text-sm" />
              )}
              <button className={btn.danger} onClick={() => setFieldFilters((cur) => cur.filter((_, j) => j !== i))}>remove</button>
            </div>
          ))}
          <button className={btn.link} onClick={() => setFieldFilters((cur) => [...cur, { field: "", op: "gte", value: "" }])}>+ Add a field filter (e.g. loan_amount ≥ 50000)</button>
        </div>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="max-h-[68vh] overflow-auto">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 shadow-[0_1px_0_#e2e8f0]">
              <tr>
                {head("phone", "Phone")}{head("date", "Call date")}{head("status", "Status")}{head("review", "Flags")}
                {cols.map((c) => head(c, c))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && <tr><td colSpan={4 + cols.length} className="px-4 py-12 text-center text-slate-400"><span className="spinner" /> Loading…</td></tr>}
              {!loading && pageRows.length === 0 && <tr><td colSpan={4 + cols.length} className="px-4 py-12 text-center text-slate-400">No calls match these filters.</td></tr>}
              {pageRows.map((r) => (
                <tr key={r.id} className="hover:bg-emerald-50/40">
                  <td className="whitespace-nowrap px-3 py-2 font-medium"><Link href={`/calls/${r.id}`} className="hover:text-emerald-700 hover:underline">{r.phone}</Link></td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">{r.date ?? <span className="text-slate-400">none</span>}{r.seq > 1 && <span className="text-slate-400"> ({r.seq})</span>}</td>
                  <td className="px-3 py-2"><StatusChip status={r.status} /></td>
                  <td className="px-3 py-2">{r.reviewCount > 0 ? <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-800">{r.reviewCount}</span> : <span className="text-slate-300">–</span>}</td>
                  {cols.map((c) => <td key={c} className="whitespace-nowrap px-3 py-2 tabular-nums">{r.fields[c] ?? <span className="text-slate-300">–</span>}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-sm text-slate-500">
          <span>{filtered.length} of {rows.length} calls</span>
          <div className="flex items-center gap-2">
            <button className={btn.secondary} disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span>Page {page + 1} / {pages}</span>
            <button className={btn.secondary} disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
      </section>
    </div>
  );
}
