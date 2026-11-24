// Logic for the API status page: turns what the worker recorded into a plain status for each key and model.

export interface KeyModelRow {
  provider: string;
  slot: number;
  model: string;
  env_name: string | null;
  key_tail: string | null;
  status: "unknown" | "ok" | "busy" | "quota" | "key_rejected" | "unavailable" | "error";
  detail: string | null;
  last_ok_at: string | null;
  last_fail_at: string | null;
  last_seen_at: string | null;
  day: string | null;
  requests_today: number;
  tokens_today: number;
}

export interface ModelInfo {
  provider: string;
  model: string;
  input_per_m: number | null;
  audio_per_m: number | null;
  output_per_m: number | null;
  free_available: boolean | null;
  free_rpd: number | null;
  free_rpm: number | null;
  free_tpm: number | null;
  note: string | null;
  in_chain: boolean;
}

export type Tone = "good" | "warn" | "bad" | "idle";
export interface Shown { label: string; tone: Tone; hint: string }

/** The date in Pacific time: Gemini's daily quota is counted (and reset at midnight) there. */
export function quotaDay(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

const STALE_BUSY_MS = 15 * 60 * 1000;

/** When the daily quota next resets (midnight in Pacific time), and how long from now, in plain words. */
export function resetInfo(now: Date = new Date()): string {
  const day = quotaDay(now);
  let t = now.getTime();
  // step forward until the Pacific date changes (at most 25 h away)
  for (const step of [3600_000, 60_000]) {
    while (quotaDay(new Date(t + step)) === day && t - now.getTime() < 26 * 3600_000) t += step;
  }
  const next = new Date(t + 60_000);
  const mins = Math.max(0, Math.round((next.getTime() - now.getTime()) / 60000));
  const bd = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Dhaka", hour: "numeric", minute: "2-digit", hour12: true }).format(next);
  return `in ${Math.floor(mins / 60)} h ${mins % 60} min (${bd} Bangladesh time)`;
}

export function shownStatus(r: KeyModelRow | undefined, today: string = quotaDay(), now: number = Date.now()): Shown {
  if (!r || r.status === "unknown" || !r.last_seen_at) {
    return { label: "Not used yet", tone: "idle", hint: "No evaluation has used this key with this model yet, so its state is unknown." };
  }
  switch (r.status) {
    case "ok":
      return { label: "Working", tone: "good", hint: "The last request on this key and model succeeded." };
    case "busy":
      if (now - new Date(r.last_seen_at).getTime() > STALE_BUSY_MS) {
        return { label: "Was busy earlier", tone: "idle", hint: "Google said the model was overloaded when this key last tried, a while ago. The key has not been tried since, so its state now is unknown." };
      }
      return { label: "Busy", tone: "warn", hint: "Google said the model is overloaded or rate limited. This usually clears within minutes." };
    case "quota":
      return r.day && r.day !== today
        ? { label: "Quota may have reset", tone: "warn", hint: "The daily quota ran out on an earlier day. It resets at midnight Pacific time, so this key probably works again." }
        : { label: "Daily quota used up", tone: "bad", hint: "The free allowance for this model is used up. It resets at midnight Pacific time (2 pm in Bangladesh in winter, 1 pm in summer)." };
    case "key_rejected":
      return { label: "Key rejected", tone: "bad", hint: "Google refused this key (invalid, disabled, or the project has no access)." };
    case "unavailable":
      return { label: "Model not available", tone: "bad", hint: "This key cannot use this model." };
    default:
      return { label: "Error", tone: "bad", hint: "The last request failed for another reason." };
  }
}

export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Requests used today, but only if the stored counter belongs to today's quota day. */
export function usedToday(r: KeyModelRow | undefined, today: string = quotaDay()): { requests: number; tokens: number } {
  return r && r.day === today ? { requests: r.requests_today, tokens: r.tokens_today } : { requests: 0, tokens: 0 };
}

export function money(v: number | null | undefined): string {
  return v === null || v === undefined ? "not set" : `$${v}`;
}

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/** Cost of one typical evaluation in USD: audio_seconds * 32 tokens/s as audio input, plus output tokens. */
export function typicalCallCost(m: ModelInfo, audioSeconds = 300, outputTokens = 6000, textTokens = 12000): number | null {
  if (m.input_per_m === null || m.audio_per_m === null || m.output_per_m === null) return null;
  return (audioSeconds * 32 * m.audio_per_m + textTokens * m.input_per_m + outputTokens * m.output_per_m) / 1_000_000;
}

export interface CheckReq {
  id: string;
  slot: number;
  model: string;
  status: "pending" | "running" | "done";
  result: string | null;
  detail: string | null;
  created_at: string;
}

const CHECK_OPEN_MS = 3 * 60 * 1000; // a request older than this is treated as lost
const CHECK_STUCK_MS = 90 * 1000; // not picked up by the worker for this long: tell the user

/** Is a "Check now" for this key + model still waiting for the worker? */
export function checkPending(checks: CheckReq[], slot: number, model: string, now: number = Date.now()): boolean {
  return checks.some((c) => c.slot === slot && c.model === model && c.status !== "done" && now - new Date(c.created_at).getTime() < CHECK_OPEN_MS);
}

/** Checks the worker has not even started after a while (probably not running). */
export function checkStuck(checks: CheckReq[], now: number = Date.now()): boolean {
  return checks.some((c) => {
    const age = now - new Date(c.created_at).getTime();
    return c.status === "pending" && age > CHECK_STUCK_MS && age < CHECK_OPEN_MS;
  });
}
