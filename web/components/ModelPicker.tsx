"use client";

import { useEffect, useMemo, useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";

const KEY = "evalModel";

/** The model chosen for the next evaluation ("" = Auto). Remembered in this browser. */
export function useModelChoice(): [string, (v: string) => void] {
  const [value, setValue] = useState("");
  useEffect(() => {
    try { setValue(localStorage.getItem(KEY) ?? ""); } catch { /* private window: just start on Auto */ }
  }, []);
  return [value, (v) => { setValue(v); try { localStorage.setItem(KEY, v); } catch { /* ignore */ } }];
}

interface Opt { model: string; in_chain: boolean; free_available: boolean | null }

export default function ModelPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const sb = useMemo(() => supabaseBrowser(), []);
  const [opts, setOpts] = useState<Opt[]>([]);
  useEffect(() => {
    sb.from("api_models").select("model,in_chain,free_available").eq("provider", "gemini").then(({ data }) => {
      setOpts(((data ?? []) as Opt[]).sort((a, b) => Number(b.in_chain) - Number(a.in_chain) || a.model.localeCompare(b.model)));
    });
  }, [sb]);

  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      Model
      <select
        value={value} onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900"
        title="Auto uses the main model and falls back to the others if it is busy. A chosen model is used on its own."
      >
        <option value="">Auto (main, then backups)</option>
        {opts.map((o) => (
          <option key={o.model} value={o.model}>
            {o.model}{o.free_available === false ? " (no free tier)" : ""}
          </option>
        ))}
        {value && !opts.some((o) => o.model === value) && <option value={value}>{value}</option>}
      </select>
    </label>
  );
}
