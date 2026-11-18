/** Builds the text the chatbot sees for ONE call. Structured fields first (reliable), transcript after (nuance). */
import { callLabel, fmtDuration } from "./format";
import type { Call, CallResult } from "./types";

/** Groq's free tier allows ~8,000 tokens per minute per model; Banglish is roughly 2.6 characters per token. */
export const CHARS_PER_TOKEN = 2.6;
export const CALL_CONTEXT_TOKENS = 5200;

export function estimateTokens(s: string): number {
  return Math.ceil(s.length / CHARS_PER_TOKEN);
}

export function buildCallContext(call: Call, r: CallResult, budgetTokens = CALL_CONTEXT_TOKENS): string {
  const lines: string[] = [];
  lines.push(`CALL: ${callLabel(call)} | audio length ${fmtDuration(call.duration_seconds)} | file ${call.file_name}`);
  lines.push("", "EXTRACTED FIELDS (name = value [confidence @time]) - most reliable source for numbers:");
  for (const [name, value] of Object.entries(r.fields).sort(([a], [b]) => a.localeCompare(b))) {
    const ev = r.evidence?.[name];
    lines.push(`${name} = ${value}${ev ? ` [${ev.confidence} @${ev.timestamp}]` : ""}`);
  }
  if (r.eng_notes) lines.push("", `SUMMARY (English): ${r.eng_notes}`);
  if (r.notes) lines.push(`SUMMARY (Banglish): ${r.notes}`);
  if (r.review?.length) {
    lines.push("", "REVIEW FLAGS:");
    for (const f of r.review.slice(0, 12)) lines.push(`- ${f.field ? f.field + ": " : ""}${f.detail}`);
  }
  if (r.behaviour?.overall) lines.push("", `BEHAVIOUR ANALYSIS: ${r.behaviour.overall}`);

  const head = lines.join("\n");
  const left = Math.max(budgetTokens - estimateTokens(head) - 60, 0);
  let transcript = r.transcript_text || "";
  let cut = false;
  if (estimateTokens(transcript) > left) {
    transcript = transcript.slice(0, Math.floor(left * CHARS_PER_TOKEN));
    cut = true;
  }
  return `${head}\n\nCONVERSATION TRANSCRIPT (speaker: words (time)):\n${transcript}${cut ? "\n[transcript cut here to fit the model's size limit]" : ""}`;
}

export const CALL_SYSTEM_PROMPT = `You are an assistant for the iFarmer data team. iFarmer gives agri-loans to farmers in Bangladesh. A CEX agent phoned one farmer to verify KYC details; the data below comes from that single call.

Rules:
- Answer ONLY from the call data below. Never guess or use outside knowledge about this farmer.
- If a value is missing from EXTRACTED FIELDS, search the CONVERSATION TRANSCRIPT before answering. If you find it there, give it and say it comes from the conversation (with the time) and is not in the extracted fields. Say the call does not contain it only when it is in neither place.
- For numbers (money, land, counts) prefer EXTRACTED FIELDS; use the transcript for context, wording and nuance. If they seem to disagree, say so and mention both.
- Land: current_landsize and *_land_size are in decimals (shotok); <unit>_own / <unit>_lease_mortgage are in the unit named in farmland (decimals_per_<unit> is the farmer's conversion); calc_land_* fields are calculated decimals. Money is Bangladeshi Taka (BDT). Yield is in maund (mon) and unit prices are per maund. Option answers are stored as codes such as Crop-6 or bigha.
- When useful, point to the time in the call, like (00:02:33).
- Reply in Bangla (Bengali script), short and clear. Keep numbers, names and field names as they are. The user may write in Bangla, Banglish or English.`;
