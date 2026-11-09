"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ChatPanel from "@/components/ChatPanel";
import BehaviourTab from "@/components/call/BehaviourTab";
import ConversationTab from "@/components/call/ConversationTab";
import FieldsTab from "@/components/call/FieldsTab";
import SummaryTab from "@/components/call/SummaryTab";
import { btn, CallProgress, Card, queueCall, StatusChip, useNow } from "@/components/ui";
import { callLabel, fmtBytes, fmtDateTime, fmtDuration, hmsToSeconds } from "@/lib/format";
import { supabaseBrowser } from "@/lib/supabase/client";
import type { Call, CallResult } from "@/lib/types";

type Tab = "summary" | "fields" | "conversation" | "behaviour" | "chat";
const TABS: [Tab, string][] = [
  ["summary", "Summary"], ["fields", "Fields"], ["conversation", "Conversation"], ["behaviour", "Behaviour analysis"], ["chat", "Ask AI"],
];

export default function CallPage() {
  const { id } = useParams<{ id: string }>();
  const sb = useMemo(() => supabaseBrowser(), []);
  const [call, setCall] = useState<Call | null>(null);
  const [result, setResult] = useState<CallResult | null>(null);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState<Tab>("summary");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);

  const loadResult = useCallback(async () => {
    const { data } = await sb.from("call_results").select("*").eq("call_id", id).maybeSingle();
    setResult((data as CallResult | null) ?? null);
  }, [sb, id]);

  const loadCall = useCallback(async () => {
    const { data } = await sb.from("calls").select("*").eq("id", id).maybeSingle();
    if (!data) { setMissing(true); return null; }
    setCall(data as Call);
    return data as Call;
  }, [sb, id]);

  useEffect(() => {
    loadCall().then((c) => {
      if (!c) return;
      loadResult();
      sb.storage.from("recordings").createSignedUrl(c.storage_path, 7200).then(({ data }) => setAudioUrl(data?.signedUrl ?? null));
    });
    const ch = sb
      .channel(`call-${id}`)
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "calls", filter: `id=eq.${id}` }, (p) => {
        const row = p.new as Call;
        setCall((cur) => {
          if (cur && cur.status !== "done" && row.status === "done") loadResult();
          return cur ? { ...cur, ...row } : cur;
        });
      })
      .subscribe();
    return () => { sb.removeChannel(ch); };
  }, [sb, id, loadCall, loadResult]);

  const active = call?.status === "queued" || call?.status === "processing";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(async () => { const c = await loadCall(); if (c?.status === "done") loadResult(); }, 4000);
    return () => clearInterval(t);
  }, [active, loadCall, loadResult]);
  const now = useNow(!!active);

  function seek(t: string) {
    const el = audio.current;
    if (!el) return;
    el.currentTime = hmsToSeconds(t);
    el.play().catch(() => undefined);
  }

  async function evaluate() {
    if (!call) return;
    if (result && !confirm("This call is already evaluated. Evaluate it again and replace the results?")) return;
    const err = await queueCall(sb, call.id);
    if (!err) setCall({ ...call, status: "queued", progress: 0, stage: null, error: null });
  }

  if (missing) return <p className="py-20 text-center text-slate-500">This call was not found. <Link href="/" className={btn.link}>Back to calls</Link></p>;
  if (!call) return <p className="py-20 text-center text-slate-500"><span className="spinner" /> Loading…</p>;

  return (
    <div className="space-y-5">
      <div>
        <Link href="/" className="text-sm text-slate-500 hover:text-emerald-700">← All calls</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{callLabel(call)}</h1>
          <StatusChip status={call.status} />
          <div className="ml-auto flex gap-2">
            {(call.status === "uploaded" || call.status === "failed") && <button className={btn.primary} onClick={evaluate}>{call.status === "failed" ? "Retry evaluation" : "Evaluate"}</button>}
            {call.status === "done" && <button className={btn.secondary} onClick={evaluate}>Re-evaluate</button>}
          </div>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {call.file_name} · {fmtDuration(call.duration_seconds)} · {fmtBytes(call.file_size)} · uploaded {fmtDateTime(call.created_at)}
        </p>
      </div>

      {active && (
        <Card title="Evaluation in progress">
          <CallProgress call={call} now={now} />
          <p className="mt-2 text-xs text-slate-500">You can leave this page; the call keeps being evaluated.{result && " The results below are from the previous evaluation until this one finishes."}</p>
        </Card>
      )}
      {call.status === "failed" && <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800"><b>Evaluation failed:</b> {call.error}</div>}

      {audioUrl && (
        <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
          <audio
            ref={audio} src={audioUrl} controls preload="metadata" className="w-full"
            onTimeUpdate={(e) => setPlayhead(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
          />
        </div>
      )}

      {!result ? (
        !active && call.status !== "failed" && (
          <Card>
            <div className="py-8 text-center">
              <p className="mb-3 text-slate-600">This call has not been evaluated yet.</p>
              <button className={btn.primary} onClick={evaluate}>Evaluate now</button>
            </div>
          </Card>
        )
      ) : (
        <>
          <div className="flex gap-1 overflow-x-auto border-b border-slate-200">
            {TABS.map(([k, label]) => (
              <button
                key={k} onClick={() => setTab(k)}
                className={`whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition ${tab === k ? "border-emerald-600 text-emerald-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
              >
                {label}
                {k === "fields" && <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs text-slate-600">{Object.keys(result.fields).length}</span>}
              </button>
            ))}
          </div>

          {tab === "summary" && <SummaryTab call={call} result={result} />}
          {tab === "fields" && <FieldsTab result={result} onSeek={seek} />}
          {tab === "conversation" && <ConversationTab result={result} playhead={playhead} playing={playing} onSeek={seek} />}
          {tab === "behaviour" && <BehaviourTab callId={call.id} result={result} onSeek={seek} />}
          {tab === "chat" && (
            <ChatPanel
              scope="call" callId={call.id}
              intro="Ask anything about this farmer's call. Answers come only from this call's fields and conversation."
              suggestions={["কৃষক কত বিঘা জমিতে চাষ করেন?", "What loan amount does the farmer want?", "স্ত্রীর কোনো ঋণ আছে কি?", "What are the risks in this call?", "Farmer er ay koto?"]}
            />
          )}
        </>
      )}
    </div>
  );
}
