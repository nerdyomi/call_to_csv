import { NextRequest, NextResponse } from "next/server";
import type { SupabaseClient } from "@supabase/supabase-js";
import { requireAllowedUser } from "@/lib/supabase/server";
import { chatOnce, chatStream, GroqBusy, stripThink, type GroqMessage } from "@/lib/groq";
import { buildCallContext, CALL_SYSTEM_PROMPT } from "@/lib/context";
import { GLOBAL_SYSTEM_PROMPT, TOOLS, runTool, type Row } from "@/lib/tools";
import type { Call, CallResult, ChatMessage } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

const HISTORY_MESSAGES = 6;
const HISTORY_CHARS = 700;

function history(messages: ChatMessage[]): GroqMessage[] {
  return messages.slice(-HISTORY_MESSAGES).map((m) => ({
    role: m.role,
    content: m.content.length > HISTORY_CHARS ? m.content.slice(0, HISTORY_CHARS) + "…" : m.content,
  }));
}

async function loadRows(sb: SupabaseClient): Promise<Row[]> {
  const { data } = await sb
    .from("calls")
    .select("id,phone,call_date,call_seq,call_results(fields,notes,eng_notes)")
    .eq("status", "done")
    .limit(2000);
  return (data ?? []).flatMap((c: any) => {
    const r = Array.isArray(c.call_results) ? c.call_results[0] : c.call_results;
    if (!r) return [];
    return [{ id: c.id, phone: c.phone, date: c.call_date, seq: c.call_seq, fields: r.fields ?? {}, notes: r.notes ?? "", eng_notes: r.eng_notes ?? "" }];
  });
}

async function globalAnswer(rows: Row[], messages: ChatMessage[]): Promise<string> {
  const counts = new Map<string, number>();
  for (const r of rows) for (const k of Object.keys(r.fields)) counts.set(k, (counts.get(k) ?? 0) + 1);
  const names = [...counts].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k}(${n})`).join(", ");
  const system = `${GLOBAL_SYSTEM_PROMPT}\n\nEvaluated calls available: ${rows.length}.\nField names with the number of calls that have a value: ${names || "none yet"}.`;
  if (rows.length === 0) return "এখনো কোনো কল মূল্যায়ন (evaluate) করা হয়নি, তাই উত্তর দেওয়ার মতো ডেটা নেই।";

  const msgs: GroqMessage[] = [{ role: "system", content: system }, ...history(messages)];
  for (let i = 0; i < 4; i++) {
    const { message } = await chatOnce(msgs, { tools: TOOLS, maxTokens: 900 });
    if (!message.tool_calls?.length) return stripThink(message.content ?? "");
    msgs.push({ role: "assistant", content: message.content ?? null, tool_calls: message.tool_calls });
    for (const tc of message.tool_calls) {
      msgs.push({ role: "tool", tool_call_id: tc.id, content: runTool(tc.function.name, tc.function.arguments, rows) });
    }
  }
  const { message } = await chatOnce([...msgs, { role: "user", content: "Now answer using the tool results above." }], { maxTokens: 900 });
  return stripThink(message.content ?? "");
}

export async function POST(req: NextRequest) {
  const auth = await requireAllowedUser();
  if (!auth) return NextResponse.json({ error: "not allowed" }, { status: 403 });
  const { sb, user } = auth;

  const body = await req.json().catch(() => null);
  const scope: "call" | "global" = body?.scope === "global" ? "global" : "call";
  const messages: ChatMessage[] = Array.isArray(body?.messages) ? body.messages : [];
  const last = messages[messages.length - 1];
  if (!last || last.role !== "user" || !last.content?.trim()) return NextResponse.json({ error: "empty question" }, { status: 400 });
  const callId: string | null = scope === "call" ? String(body?.callId ?? "") : null;

  let system = "";
  let rows: Row[] = [];
  if (scope === "call") {
    const [{ data: call }, { data: result }] = await Promise.all([
      sb.from("calls").select("*").eq("id", callId).maybeSingle(),
      sb.from("call_results").select("*").eq("call_id", callId).maybeSingle(),
    ]);
    if (!call) return NextResponse.json({ error: "call not found" }, { status: 404 });
    if (!result) return NextResponse.json({ error: "This call has not been evaluated yet." }, { status: 409 });
    system = `${CALL_SYSTEM_PROMPT}\n\n=== CALL DATA ===\n${buildCallContext(call as Call, result as CallResult)}`;
  } else {
    rows = await loadRows(sb);
  }

  await sb.from("chat_messages").insert({ scope, call_id: callId, user_id: user.id, role: "user", content: last.content });

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      let full = "";
      const send = (s: string) => {
        full += s;
        controller.enqueue(encoder.encode(s));
      };
      try {
        if (scope === "call") {
          const msgs: GroqMessage[] = [{ role: "system", content: system }, ...history(messages)];
          for await (const piece of chatStream(msgs, { maxTokens: 900 })) send(piece);
        } else {
          const text = await globalAnswer(rows, messages);
          for (let i = 0; i < text.length; i += 60) send(text.slice(i, i + 60));
        }
        if (!full.trim()) send("(কোনো উত্তর পাওয়া যায়নি — আবার চেষ্টা করুন।)");
        await sb.from("chat_messages").insert({ scope, call_id: callId, user_id: user.id, role: "assistant", content: full });
      } catch (e) {
        const msg = e instanceof GroqBusy ? e.message : `Chat failed: ${String((e as Error).message ?? e).slice(0, 300)}`;
        send(`\n\n⚠ ${msg}`);
      } finally {
        controller.close();
      }
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
}
