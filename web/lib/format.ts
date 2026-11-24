import type { Call } from "./types";

export function callLabel(c: Pick<Call, "phone" | "call_date" | "call_seq">): string {
  return `${c.phone} · ${c.call_date ?? "none"}${c.call_seq > 1 ? ` (${c.call_seq})` : ""}`;
}

export const STAGE_LABEL: Record<string, string> = {
  downloading: "Downloading audio",
  thinking: "AI is listening and thinking",
  transcribing: "Writing the conversation",
  extracting: "Filling the fields",
  checking: "Checking results",
  saving: "Saving",
};

/** Readable text for calls.stage. Besides the plain stages the worker writes "trying|2|gemini-3.8-flash|1"
 *  (asking key api2, attempt 1) and "busy|2|gemini-3.8-flash|1" (Google is overloaded, retrying). */
export function stageLabel(stage: string | null | undefined): string {
  const [kind, slot, model, attempt] = (stage ?? "").split("|");
  if (kind === "trying") return `Waiting for ${model} · api${slot}${Number(attempt) > 1 ? `, try ${attempt}` : ""}`;
  if (kind === "busy") return `Google is busy · retrying api${slot} (${model}, try ${attempt})`;
  return STAGE_LABEL[kind] ?? "Evaluating";
}

/** True while the AI has not written anything yet, so there is no real percentage to show. */
export function isWaitingStage(stage: string | null | undefined): boolean {
  return ["", "downloading", "thinking", "trying", "busy"].includes((stage ?? "").split("|")[0]);
}

export function fmtDuration(sec: number | null | undefined): string {
  if (!sec) return "–";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function hmsToSeconds(t: string): number {
  const p = t.split(":").map((x) => parseInt(x, 10));
  if (p.length === 0 || p.some(Number.isNaN)) return 0;
  while (p.length < 3) p.unshift(0);
  return p[0] * 3600 + p[1] * 60 + p[2];
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "–";
  return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
}
