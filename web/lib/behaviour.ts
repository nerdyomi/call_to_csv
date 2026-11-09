import { buildCallContext } from "./context";
import { chatOnce, stripThink } from "./groq";
import type { Behaviour, Call, CallResult } from "./types";

const LEVELS3 = ["high", "medium", "low"];
const CONSISTENCY = ["consistent", "mostly_consistent", "inconsistent"];

function str(x: unknown, fallback = "not clear from the call"): string {
  return typeof x === "string" && x.trim() ? x.trim() : fallback;
}
function list(x: unknown): string[] {
  return Array.isArray(x) ? x.filter((s) => typeof s === "string" && s.trim()).map((s) => s.trim()) : [];
}
function points(x: unknown): { point: string; time: string }[] {
  return Array.isArray(x)
    ? x.filter((p) => p && typeof p.point === "string").map((p) => ({ point: p.point.trim(), time: typeof p.time === "string" ? p.time : "" }))
    : [];
}

/** Accepts the model's JSON and returns a complete Behaviour even if some keys are missing. */
export function normalizeBehaviour(raw: any): Behaviour {
  const lvl = (o: any, allowed: string[], dflt: string) => ({
    level: allowed.includes(o?.level) ? o.level : dflt,
    why: str(o?.why),
  });
  return {
    overall: str(raw?.overall),
    tone: str(raw?.tone),
    cooperation: lvl(raw?.cooperation, LEVELS3, "medium") as Behaviour["cooperation"],
    consistency: lvl(raw?.consistency, CONSISTENCY, "mostly_consistent") as Behaviour["consistency"],
    confidence_in_answers: lvl(raw?.confidence_in_answers, LEVELS3, "medium") as Behaviour["confidence_in_answers"],
    financial_stress_signals: list(raw?.financial_stress_signals),
    red_flags: points(raw?.red_flags),
    positives: points(raw?.positives),
    follow_up_questions: list(raw?.follow_up_questions),
  };
}

export function parseJson(text: string): unknown {
  const cleaned = stripThink(text).replace(/^```(?:json)?/i, "").replace(/```\s*$/, "").trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    const a = cleaned.indexOf("{"), b = cleaned.lastIndexOf("}");
    if (a >= 0 && b > a) return JSON.parse(cleaned.slice(a, b + 1));
    throw new Error("the model did not return JSON");
  }
}

const BEHAVIOUR_SYSTEM = `You are a credit-risk and customer-experience analyst at iFarmer, an agri-loan company in Bangladesh. You read ONE verification call between a CEX agent and a farmer (Banglish transcript plus the form fields extracted from it) and describe the FARMER'S BEHAVIOUR in the call.

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

/** Reads one call (fields + transcript) and returns the behaviour analysis. Shared by the API route and the live test. */
export async function generateBehaviour(call: Call, result: CallResult): Promise<{ behaviour: Behaviour; model: string }> {
  const context = buildCallContext(call, { ...result, behaviour: null }, 4800);
  const { message, model } = await chatOnce(
    [{ role: "system", content: BEHAVIOUR_SYSTEM }, { role: "user", content: `CALL DATA
${context}

Return the JSON object now.` }],
    { json: true, maxTokens: 1500, temperature: 0.2 },
  );
  return { behaviour: normalizeBehaviour(parseJson(message.content ?? "")), model };
}
