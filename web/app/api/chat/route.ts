import { NextRequest, NextResponse } from "next/server";
import { requireAllowedUser } from "@/lib/supabase/server";
import { chatStream, GroqBusy, type GroqMessage } from "@/lib/groq";
import { globalAnswer, history, loadRows } from "@/lib/globalChat";
import { buildCallContext, CALL_SYSTEM_PROMPT } from "@/lib/context";
import type { Row } from "@/lib/tools";
import type { Call, CallResult, ChatMessage } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

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
