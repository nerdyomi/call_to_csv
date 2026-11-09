/** Shared by the /api/chat route and the live test script, so both run exactly the same logic. */
import type { SupabaseClient } from "@supabase/supabase-js";
import { chatOnce, stripThink, type GroqMessage } from "./groq";
import { GLOBAL_SYSTEM_PROMPT, TOOLS, runTool, type Row } from "./tools";
import type { ChatMessage } from "./types";

const HISTORY_MESSAGES = 6;
const HISTORY_CHARS = 700;

export function history(messages: ChatMessage[]): GroqMessage[] {
  return messages.slice(-HISTORY_MESSAGES).map((m) => ({
    role: m.role,
    content: m.content.length > HISTORY_CHARS ? m.content.slice(0, HISTORY_CHARS) + "…" : m.content,
  }));
}

/** All evaluated calls with their extracted fields (row level security applies to the client you pass). */
export async function loadRows(sb: SupabaseClient): Promise<Row[]> {
  const { data } = await sb
    .from("calls")
    .select("id,phone,call_date,call_seq,call_results(fields,notes,eng_notes)")
    .eq("status", "done")
    .limit(2000);
  return ((data ?? []) as any[]).flatMap((c) => {
    const r = Array.isArray(c.call_results) ? c.call_results[0] : c.call_results;
    if (!r) return [];
    return [{ id: c.id, phone: c.phone, date: c.call_date, seq: c.call_seq, fields: r.fields ?? {}, notes: r.notes ?? "", eng_notes: r.eng_notes ?? "" } as Row];
  });
}

/** Answers a question about ALL calls by letting the model call search/aggregate tools (exact numbers). */
export async function globalAnswer(rows: Row[], messages: ChatMessage[]): Promise<string> {
  if (rows.length === 0) return "এখনো কোনো কল মূল্যায়ন (evaluate) করা হয়নি, তাই উত্তর দেওয়ার মতো ডেটা নেই।";
  const counts = new Map<string, number>();
  for (const r of rows) for (const k of Object.keys(r.fields)) counts.set(k, (counts.get(k) ?? 0) + 1);
  const names = [...counts].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k}(${n})`).join(", ");
  const system = `${GLOBAL_SYSTEM_PROMPT}\n\nEvaluated calls available: ${rows.length}.\nField names with the number of calls that have a value: ${names || "none yet"}.`;

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
