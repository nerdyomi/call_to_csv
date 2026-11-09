"use client";

import { useRef, useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";
import { isValidDate, normalizePhone, parseRecordingName, safeStorageName } from "@/lib/filename";
import { fmtBytes } from "@/lib/format";
import { btn } from "./ui";

const AUDIO = /\.(mp3|mpeg|mpga|wav|m4a|aac|ogg|flac)$/i;

interface Item {
  key: string;
  file: File;
  phone: string;
  date: string; // YYYY-MM-DD or "" (= none)
  state: "ready" | "uploading" | "done" | "error";
  error?: string;
}

function contentType(f: File): string {
  if (/\.(mp3|mpeg|mpga)$/i.test(f.name)) return "audio/mpeg";
  return f.type || "application/octet-stream";
}

export default function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rejected, setRejected] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);

  function add(files: FileList | File[]) {
    const list = Array.from(files);
    setRejected(list.filter((f) => !AUDIO.test(f.name)).map((f) => f.name));
    const fresh = list
      .filter((f) => AUDIO.test(f.name))
      .map((file): Item => {
        const p = parseRecordingName(file.name);
        return { key: `${file.name}-${file.size}-${Math.random()}`, file, phone: p.phone ?? "", date: p.date ?? "", state: "ready" };
      });
    setItems((cur) => [...cur, ...fresh]);
  }

  const patch = (key: string, p: Partial<Item>) => setItems((cur) => cur.map((i) => (i.key === key ? { ...i, ...p } : i)));
  const remove = (key: string) => setItems((cur) => cur.filter((i) => i.key !== key));

  const problems = (i: Item) => ({
    phone: !normalizePhone(i.phone),
    date: i.date !== "" && !isValidDate(i.date),
  });
  const canUpload = items.some((i) => i.state === "ready") && items.every((i) => i.state !== "ready" || (!problems(i).phone && !problems(i).date));

  async function uploadOne(i: Item) {
    const sb = supabaseBrowser();
    const phone = normalizePhone(i.phone)!;
    const date = i.date || null;
    patch(i.key, { state: "uploading", error: undefined });
    try {
      const { data: u } = await sb.auth.getUser();
      const f = await sb.from("farmers").upsert({ phone }, { onConflict: "phone", ignoreDuplicates: true });
      if (f.error) throw new Error(f.error.message);

      let q = sb.from("calls").select("call_seq").eq("phone", phone);
      q = date ? q.eq("call_date", date) : q.is("call_date", null);
      const { data: existing, error: qe } = await q;
      if (qe) throw new Error(qe.message);
      const seq = 1 + Math.max(0, ...(existing ?? []).map((r: { call_seq: number }) => r.call_seq));

      const path = `${phone}/${date ?? "none"}-${seq}/${safeStorageName(i.file.name)}`;
      const up = await sb.storage.from("recordings").upload(path, i.file, { contentType: contentType(i.file), upsert: false });
      if (up.error) throw new Error(up.error.message);

      const ins = await sb.from("calls").insert({
        phone, call_date: date, call_seq: seq, file_name: i.file.name, storage_path: path,
        file_size: i.file.size, status: "uploaded", created_by: u.user?.id,
      });
      if (ins.error) {
        await sb.storage.from("recordings").remove([path]);
        throw new Error(ins.error.message);
      }
      patch(i.key, { state: "done" });
    } catch (e) {
      patch(i.key, { state: "error", error: (e as Error).message });
    }
  }

  async function uploadAll() {
    setBusy(true);
    for (const i of items.filter((x) => x.state === "ready" || x.state === "error")) await uploadOne(i);
    setBusy(false);
    onUploaded();
    setTimeout(() => setItems((cur) => cur.filter((i) => i.state !== "done")), 1500);
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${
          over ? "border-emerald-500 bg-emerald-50" : "border-slate-300 bg-slate-50 hover:border-emerald-400 hover:bg-emerald-50/40"
        }`}
      >
        <div className="mb-2 text-3xl">🎙️</div>
        <p className="font-medium text-slate-800">Drag and drop call recordings here</p>
        <p className="text-sm text-slate-500">or click to choose files · mp3, wav, m4a …</p>
        <input
          ref={input} type="file" multiple accept="audio/*,.mp3,.mpeg,.mpga,.m4a,.wav,.aac,.ogg,.flac" className="hidden"
          onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }}
        />
      </div>

      {rejected.length > 0 && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Not an audio file, skipped: {rejected.join(", ")}
        </p>
      )}

      {items.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-sm text-slate-600">
            Check the phone number and date for each call. The date is optional: if you leave it empty it is stored as <b>none</b>.
          </p>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">File</th><th className="px-3 py-2">Farmer phone</th><th className="px-3 py-2">Call date</th><th className="px-3 py-2">State</th><th /></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((i) => {
                  const pr = problems(i);
                  return (
                    <tr key={i.key}>
                      <td className="max-w-[280px] px-3 py-2"><div className="truncate font-medium" title={i.file.name}>{i.file.name}</div><div className="text-xs text-slate-400">{fmtBytes(i.file.size)}</div></td>
                      <td className="px-3 py-2">
                        <input
                          value={i.phone} disabled={i.state !== "ready" && i.state !== "error"} placeholder="01XXXXXXXXX"
                          onChange={(e) => patch(i.key, { phone: e.target.value })}
                          className={`w-44 rounded-md border px-2 py-1 ${pr.phone ? "border-red-400 bg-red-50" : "border-slate-300"}`}
                        />
                        {pr.phone && <div className="text-xs text-red-600">Enter the farmer's phone number</div>}
                      </td>
                      <td className="px-3 py-2">
                        <input
                          type="date" value={i.date} disabled={i.state !== "ready" && i.state !== "error"}
                          onChange={(e) => patch(i.key, { date: e.target.value })}
                          className={`rounded-md border px-2 py-1 ${i.date === "" ? "border-amber-300 bg-amber-50" : "border-slate-300"}`}
                        />
                        {i.date === "" && <div className="text-xs text-amber-700">no date → stored as "none"</div>}
                      </td>
                      <td className="px-3 py-2">
                        {i.state === "ready" && <span className="text-slate-500">Ready</span>}
                        {i.state === "uploading" && <span className="text-sky-700"><span className="spinner mr-1" />Uploading…</span>}
                        {i.state === "done" && <span className="font-medium text-emerald-700">✓ Uploaded</span>}
                        {i.state === "error" && <span className="text-red-700" title={i.error}>✕ {i.error?.slice(0, 60)}</span>}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {i.state !== "uploading" && i.state !== "done" && <button className={btn.danger} onClick={() => remove(i.key)}>Remove</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button className={btn.primary} disabled={!canUpload || busy} onClick={uploadAll}>
              {busy ? "Uploading…" : `Upload ${items.filter((i) => i.state === "ready" || i.state === "error").length} file(s)`}
            </button>
            <button className={btn.secondary} disabled={busy} onClick={() => setItems([])}>Clear</button>
          </div>
        </div>
      )}
    </div>
  );
}
