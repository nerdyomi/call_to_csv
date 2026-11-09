"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";
import type { ChatMessage } from "@/lib/types";
import { btn } from "./ui";

interface Props {
  scope: "call" | "global";
  callId?: string;
  suggestions: string[];
  intro: string;
  height?: string;
}

export default function ChatPanel({ scope, callId, suggestions, intro, height = "h-[560px]" }: Props) {
  const sb = useMemo(() => supabaseBrowser(), []);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // earlier conversation of this user on this call / globally
  useEffect(() => {
    let q = sb.from("chat_messages").select("role,content").eq("scope", scope).order("created_at", { ascending: true }).limit(60);
    q = scope === "call" ? q.eq("call_id", callId ?? "") : q.is("call_id", null);
    q.then(({ data }) => setMessages((data ?? []) as ChatMessage[]));
  }, [sb, scope, callId]);

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [messages, sending]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || sending) return;
    setError(null);
    setInput("");
    const asked: ChatMessage[] = [...messages, { role: "user", content: question }];
    setMessages([...asked, { role: "assistant", content: "" }]);
    setSending(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope, callId, messages: asked }),
      });
      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.error ?? `Request failed (${res.status})`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let answer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        answer += decoder.decode(value, { stream: true });
        setMessages([...asked, { role: "assistant", content: answer }]);
      }
    } catch (e) {
      setMessages(asked);
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className={`${height} space-y-3 overflow-y-auto p-4`}>
        {messages.length === 0 && (
          <div className="mx-auto max-w-xl py-6 text-center">
            <div className="mb-2 text-3xl">💬</div>
            <p className="text-slate-600">{intro}</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
                <button key={s} onClick={() => send(s)} className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-800 hover:bg-emerald-100">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`prose-chat max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] ${
              m.role === "user" ? "bg-emerald-600 text-white" : "border border-slate-200 bg-slate-50 text-slate-900"
            }`}>
              {m.content || (sending && i === messages.length - 1 ? <span className="spinner" /> : "")}
            </div>
          </div>
        ))}
        {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">⚠ {error}</div>}
        <div ref={bottom} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="flex gap-2 border-t border-slate-100 p-3">
        <input
          value={input} onChange={(e) => setInput(e.target.value)} disabled={sending}
          placeholder="Ask in Bangla, Banglish or English…"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100"
        />
        <button className={btn.primary} disabled={sending || !input.trim()}>{sending ? "…" : "Ask"}</button>
        {messages.length > 0 && <button type="button" className={btn.secondary} disabled={sending} onClick={() => setMessages([])}>Clear view</button>}
      </form>
    </div>
  );
}
