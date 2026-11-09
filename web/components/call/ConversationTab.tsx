"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { hmsToSeconds } from "@/lib/format";
import type { CallResult } from "@/lib/types";

const WHO: Record<string, { label: string; bubble: string; tag: string }> = {
  CEX: { label: "CEX agent", bubble: "bg-sky-50 border-sky-100", tag: "text-sky-700" },
  farmer: { label: "Farmer", bubble: "bg-emerald-50 border-emerald-100", tag: "text-emerald-700" },
  other: { label: "Other person", bubble: "bg-slate-50 border-slate-200", tag: "text-slate-600" },
};

export default function ConversationTab({ result, playhead, playing, onSeek }: {
  result: CallResult; playhead: number; playing: boolean; onSeek: (t: string) => void;
}) {
  const [q, setQ] = useState("");
  const turns = result.transcript ?? [];
  const starts = useMemo(() => turns.map((t) => hmsToSeconds(t.time)), [turns]);
  const active = useMemo(() => {
    let idx = -1;
    starts.forEach((s, i) => { if (s <= playhead) idx = i; });
    return idx;
  }, [starts, playhead]);
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (playing) activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active, playing]);

  if (turns.length === 0) return <p className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-500">No conversation text was saved for this call.</p>;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
        <input
          value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the conversation…"
          className="w-72 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-emerald-500"
        />
        <span className="ml-auto text-sm text-slate-500">{turns.length} turns · click a time to play from there · written in Banglish by AI, may contain mistakes</span>
      </div>
      <div className="max-h-[640px] space-y-2 overflow-y-auto p-4">
        {turns.map((t, i) => {
          const w = WHO[t.speaker] ?? WHO.other;
          const hit = !q || t.text.toLowerCase().includes(q.toLowerCase());
          const isActive = i === active;
          return (
            <div key={i} ref={isActive ? activeRef : undefined} className={`flex ${t.speaker === "farmer" ? "justify-end" : "justify-start"} ${hit ? "" : "opacity-25"}`}>
              <div className={`max-w-[85%] rounded-2xl border px-4 py-2 ${w.bubble} ${isActive ? "ring-2 ring-emerald-500" : ""}`}>
                <div className="mb-0.5 flex items-center gap-2 text-xs">
                  <span className={`font-semibold ${w.tag}`}>{w.label}</span>
                  <button className="font-mono text-slate-400 hover:text-emerald-700 hover:underline" onClick={() => onSeek(t.time)}>▶ {t.time}</button>
                </div>
                <p className="text-[15px] leading-relaxed text-slate-800">{t.text}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
