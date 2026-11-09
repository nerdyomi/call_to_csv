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
