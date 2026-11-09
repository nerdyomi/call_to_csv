/**
 * Live check of the AI paths with real data and real Groq models (uses the service-role key, read-only).
 *   npx tsx --env-file=.env.local scripts/live_ai_check.ts
 * It runs the same library code as /api/chat and /api/behaviour; only the login step is skipped.
 */
import { createClient } from "@supabase/supabase-js";
import { generateBehaviour } from "../lib/behaviour";
import { buildCallContext, CALL_SYSTEM_PROMPT, estimateTokens } from "../lib/context";
import { globalAnswer, history, loadRows } from "../lib/globalChat";
import { chatStream, type GroqMessage } from "../lib/groq";
import type { Call, CallResult } from "../lib/types";

const only = process.argv[2]; // chat | global | behaviour (default: all)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });

async function main() {
  const { data: calls } = await sb.from("calls").select("*").eq("status", "done").limit(1);
  if (!calls?.length) throw new Error("no evaluated call in the database");
  const call = calls[0] as Call;
  const { data: result } = await sb.from("call_results").select("*").eq("call_id", call.id).single();
  const r = result as CallResult;
  console.log(`CALL ${call.phone} ${call.call_date ?? "none"} | fields: ${Object.keys(r.fields).length} | transcript turns: ${r.transcript.length}`);
  console.log("ground truth from the stored fields:", { loan_amount: r.fields.loan_amount, current_landsize: r.fields.current_landsize, own: r.fields.own, lease_mortgage: r.fields.lease_mortgage, income_from_agriculture: r.fields.income_from_agriculture, income_from_business: r.fields.income_from_business });

  const context = buildCallContext(call, r);
  console.log(`per-call context: ~${estimateTokens(context)} tokens\n`);
  const system = `${CALL_SYSTEM_PROMPT}\n\n=== CALL DATA ===\n${context}`;

  if (!only || only === "chat") console.log("=== 1. PER-CALL CHAT (streamed) ===");
  for (const q of (only && only !== "chat" ? [] : ["কৃষক কত বিঘা জমিতে চাষ করেন?", "What loan amount does the farmer want?", "Farmer er bochorer ay koto?", "স্ত্রীর কোনো লোন আছে কি? কত টাকার?"])) {
    const t = Date.now();
    const msgs: GroqMessage[] = [{ role: "system", content: system }, ...history([{ role: "user", content: q }])];
    let ans = "", first = 0;
    try {
      for await (const piece of chatStream(msgs, { maxTokens: 900 })) { if (!first) first = Date.now() - t; ans += piece; }
    } catch (e) { ans = `ERROR: ${(e as Error).message}`; }
    console.log(`Q: ${q}\nA: ${ans.trim()}\n   (first token ${first} ms, total ${Date.now() - t} ms)\n`);
    await sleep(20000);
  }

  if (only && only !== "global") return;
  console.log("=== 2. GLOBAL CHAT (tool calling) ===");
  const rows = await loadRows(sb);
  const sum = rows.reduce((s, x) => s + Number(x.fields.loan_amount ?? 0), 0);
  console.log(`expected: ${rows.length} evaluated call(s), total loan_amount = ${sum}`);
  for (const q of ["মোট কতটি কল মূল্যায়ন হয়েছে এবং সবার মোট লোনের পরিমাণ কত?", "Which farmers have lease_mortgage land? show their phone and the amount"]) {
    const t = Date.now();
    let ans: string;
    try { ans = await globalAnswer(rows, [{ role: "user", content: q }]); } catch (e) { ans = `ERROR: ${(e as Error).message}`; }
    console.log(`Q: ${q}\nA: ${ans.trim()}\n   (${Date.now() - t} ms)\n`);
    await sleep(20000);
  }

  if (only === "global") return;
  console.log("=== 3. BEHAVIOUR ANALYSIS ===");
  const t = Date.now();
  try {
    const { behaviour, model } = await generateBehaviour(call, r);
    console.log(`model: ${model} (${Date.now() - t} ms)`);
    console.log(JSON.stringify(behaviour, null, 2));
  } catch (e) { console.log("ERROR:", (e as Error).message); }
}

main().catch((e) => { console.error(e); process.exit(1); });
