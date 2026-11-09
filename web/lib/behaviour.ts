import { stripThink } from "./groq";
import type { Behaviour } from "./types";

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
