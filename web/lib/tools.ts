/** Query tools for the global chatbot. The model asks, this code computes - so counts and sums are exact. */

export interface Row {
  id: string;
  phone: string;
  date: string | null;
  seq: number;
  fields: Record<string, string>;
  notes: string;
  eng_notes: string;
}

export interface Filter {
  field: string;
  op: string;
  value?: string | number | string[];
}

const KEY_FIELDS = ["loan_amount", "current_landsize", "own", "lease_mortgage", "number_of_dependents", "monthly_expenses"];

export function rowRef(r: Row): string {
  return `${r.phone}|${r.date ?? "none"}${r.seq > 1 ? `(${r.seq})` : ""}`;
}

function getValue(r: Row, field: string): string | undefined {
  switch (field) {
    case "phone": return r.phone;
    case "date": case "call_date": return r.date ?? undefined;
    case "notes": return r.notes;
    case "eng_notes": return r.eng_notes;
    default: return r.fields[field];
  }
}

const num = (s: unknown): number | null => {
  if (typeof s === "number") return s;
  if (typeof s !== "string" || s.trim() === "") return null;
  const n = Number(s.replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
};

export function matches(r: Row, f: Filter): boolean {
  const v = getValue(r, f.field);
  const has = v !== undefined && v !== "";
  if (f.op === "empty") return !has;
  if (f.op === "nonempty") return has;
  if (!has) return false;
  const a = v as string;
  const b = f.value;
  const na = num(a), nb = num(b);
  const both = na !== null && nb !== null;
  switch (f.op) {
    case "eq": return both ? na === nb : a.toLowerCase() === String(b).toLowerCase();
    case "neq": return both ? na !== nb : a.toLowerCase() !== String(b).toLowerCase();
    case "gt": return both ? na! > nb! : a > String(b);
    case "gte": return both ? na! >= nb! : a >= String(b);
    case "lt": return both ? na! < nb! : a < String(b);
    case "lte": return both ? na! <= nb! : a <= String(b);
    case "contains": return a.toLowerCase().includes(String(b).toLowerCase());
    case "not_contains": return !a.toLowerCase().includes(String(b).toLowerCase());
    case "in": return (Array.isArray(b) ? b : [String(b)]).some((x) => x.toLowerCase() === a.toLowerCase());
    default: return false;
  }
}

export function applyFilters(rows: Row[], filters: Filter[] = []): Row[] {
  return rows.filter((r) => filters.every((f) => matches(r, f)));
}

export function searchCalls(rows: Row[], args: { filters?: Filter[]; fields?: string[]; limit?: number; sort_by?: string; sort_dir?: string }) {
  let out = applyFilters(rows, args.filters);
  const total = out.length;
  if (args.sort_by) {
    const dir = args.sort_dir === "asc" ? 1 : -1;
    out = [...out].sort((x, y) => {
      const a = getValue(x, args.sort_by!), b = getValue(y, args.sort_by!);
      const na = num(a), nb = num(b);
      if (na !== null && nb !== null) return (na - nb) * dir;
      return String(a ?? "").localeCompare(String(b ?? "")) * dir;
    });
  }
  const limit = Math.min(Math.max(args.limit ?? 15, 1), 40);
  const cols = args.fields?.length ? args.fields.slice(0, 14) : KEY_FIELDS;
  return {
    total_matching: total,
    shown: Math.min(total, limit),
    rows: out.slice(0, limit).map((r) => ({ call: rowRef(r), ...Object.fromEntries(cols.map((c) => [c, getValue(r, c) ?? null])) })),
  };
}

export function aggregate(rows: Row[], args: { op: string; field?: string; filters?: Filter[]; group_by?: string }) {
  const sel = applyFilters(rows, args.filters);
  const calc = (rs: Row[]) => {
    if (args.op === "count" && !args.field) return rs.length;
    const vals = rs.map((r) => getValue(r, args.field ?? "")).filter((v) => v !== undefined && v !== "") as string[];
    if (args.op === "count") return vals.length;
    const nums = vals.map(num).filter((n): n is number => n !== null);
    if (!nums.length) return null;
    const sum = nums.reduce((s, n) => s + n, 0);
    switch (args.op) {
      case "sum": return sum;
      case "avg": return Math.round((sum / nums.length) * 100) / 100;
      case "min": return Math.min(...nums);
      case "max": return Math.max(...nums);
      default: return null;
    }
  };
  if (!args.group_by) return { calls_considered: sel.length, result: calc(sel) };
  const groups = new Map<string, Row[]>();
  for (const r of sel) {
    const k = getValue(r, args.group_by) ?? "(blank)";
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  return { calls_considered: sel.length, groups: [...groups].slice(0, 40).map(([k, rs]) => ({ [args.group_by!]: k, calls: rs.length, result: calc(rs) })) };
}

const FILTER_SCHEMA = {
  type: "array",
  description: "All filters must match. field = a field name, or phone / date / notes / eng_notes.",
  items: {
    type: "object",
    properties: {
      field: { type: "string" },
      op: { type: "string", enum: ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains", "in", "empty", "nonempty"] },
      value: { description: "number, string, or list of strings for op=in" },
    },
    required: ["field", "op"],
  },
};

export const TOOLS = [
  {
    type: "function",
    function: {
      name: "search_calls",
      description: "List evaluated calls that match filters, with chosen field values. Use for 'which farmers...', 'show me...'.",
      parameters: {
        type: "object",
        properties: {
          filters: FILTER_SCHEMA,
          fields: { type: "array", items: { type: "string" }, description: "field values to return (max 14)" },
          limit: { type: "integer", description: "max rows, default 15, max 40" },
          sort_by: { type: "string" },
          sort_dir: { type: "string", enum: ["asc", "desc"] },
        },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "aggregate",
      description: "Exact count / sum / avg / min / max over matching calls, optionally grouped. Use for any total, average or 'how many'.",
      parameters: {
        type: "object",
        properties: {
          op: { type: "string", enum: ["count", "sum", "avg", "min", "max"] },
          field: { type: "string", description: "field to compute on; omit for a plain count of calls" },
          filters: FILTER_SCHEMA,
          group_by: { type: "string", description: "optional field to group by" },
        },
        required: ["op"],
      },
    },
  },
];

export function runTool(name: string, rawArgs: string, rows: Row[]): string {
  let args: any;
  try {
    args = rawArgs ? JSON.parse(rawArgs) : {};
  } catch {
    return JSON.stringify({ error: "arguments were not valid JSON" });
  }
  try {
    const out = name === "search_calls" ? searchCalls(rows, args) : name === "aggregate" ? aggregate(rows, args) : { error: `unknown tool ${name}` };
    const s = JSON.stringify(out);
    return s.length > 7000 ? s.slice(0, 7000) + "...(truncated)" : s;
  } catch (e) {
    return JSON.stringify({ error: String(e) });
  }
}

export const GLOBAL_SYSTEM_PROMPT = `You are an assistant for the iFarmer data team. iFarmer gives agri-loans to farmers in Bangladesh. CEX agents phone farmers to verify KYC details; each call was transcribed and its form fields extracted. You can query ALL evaluated calls with tools.

Rules:
- For any count, total, average, list or comparison you MUST call a tool; never compute or guess from memory. Tools return exact numbers.
- Only state what the tool results show. If nothing matches, say so. Mention how many calls were considered.
- Refer to calls as phone and date, e.g. 8801762709049 (2026-11-01).
- Land is in decimals (shotok), money in BDT, yield in kg. Field values are stored as text numbers.
- Reply in Bangla (Bengali script), short and clear; keep numbers, phone numbers and field names as they are. The user may write in Bangla, Banglish or English.`;
