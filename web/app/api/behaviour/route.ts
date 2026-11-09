import { NextRequest, NextResponse } from "next/server";
import { requireAllowedUser, supabaseService } from "@/lib/supabase/server";
import { chatOnce, GroqBusy } from "@/lib/groq";
import { normalizeBehaviour, parseJson } from "@/lib/behaviour";
import { buildCallContext } from "@/lib/context";
import type { Call, CallResult } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

const SYSTEM = `You are a credit-risk and customer-experience analyst at iFarmer, an agri-loan company in Bangladesh. You read ONE verification call between a CEX agent and a farmer (Banglish transcript plus the form fields extracted from it) and describe the FARMER'S BEHAVIOUR in the call.

Rules:
- Use only what is in the call data. Do not invent facts. If something cannot be judged, say "not clear from the call".
- Be fair and specific. Every red flag or positive must point to a moment in the call (time as HH:MM:SS taken from the transcript).
- Behaviour means: how cooperative, how consistent, how sure of his/her answers, tone, any hesitation, guessing, contradiction, pressure for money, or other signals relevant to a loan decision. Do NOT judge the person's character and do NOT recommend approving or rejecting the loan.
- Write in simple English.

Return ONLY a JSON object with exactly these keys:
{
  "overall": "2-3 sentence summary of the farmer's behaviour",
  "tone": "short description of tone and manner",
  "cooperation": {"level": "high|medium|low", "why": "..."},
  "consistency": {"level": "consistent|mostly_consistent|inconsistent", "why": "... mention contradictions with times"},
  "confidence_in_answers": {"level": "high|medium|low", "why": "... hesitation, guessing, needing to ask family"},
  "financial_stress_signals": ["..."],
  "red_flags": [{"point": "...", "time": "HH:MM:SS"}],
  "positives": [{"point": "...", "time": "HH:MM:SS"}],
  "follow_up_questions": ["questions the agent should ask next"]
}
Use empty lists when there is nothing to report.`;

export async function POST(req: NextRequest) {
  const auth = await requireAllowedUser();
  if (!auth) return NextResponse.json({ error: "not allowed" }, { status: 403 });
  const body = await req.json().catch(() => null);
  const callId = String(body?.callId ?? "");
  const force = body?.force === true;

  const [{ data: call }, { data: result }] = await Promise.all([
    auth.sb.from("calls").select("*").eq("id", callId).maybeSingle(),
    auth.sb.from("call_results").select("*").eq("call_id", callId).maybeSingle(),
  ]);
  if (!call || !result) return NextResponse.json({ error: "This call has not been evaluated yet." }, { status: 404 });
  const r = result as CallResult;
  if (r.behaviour && !force) return NextResponse.json({ behaviour: r.behaviour, model: r.behaviour_model, cached: true });

  try {
    const context = buildCallContext(call as Call, { ...r, behaviour: null }, 4800);
    const { message, model } = await chatOnce(
      [{ role: "system", content: SYSTEM }, { role: "user", content: `CALL DATA\n${context}\n\nReturn the JSON object now.` }],
      { json: true, maxTokens: 1500, temperature: 0.2 },
    );
    const behaviour = normalizeBehaviour(parseJson(message.content ?? ""));
    const saved = await supabaseService()
      .from("call_results")
      .update({ behaviour, behaviour_model: model, behaviour_at: new Date().toISOString() })
      .eq("call_id", callId);
    return NextResponse.json({
      behaviour,
      model,
      cached: false,
      saved: !saved.error,
      warning: saved.error ? "Analysis was not saved: run supabase/migrations/002_progress_behaviour.sql" : undefined,
    });
  } catch (e) {
    const status = e instanceof GroqBusy ? 503 : 500;
    return NextResponse.json({ error: String((e as Error).message ?? e).slice(0, 400) }, { status });
  }
}
