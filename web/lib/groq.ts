/** Groq (OpenAI-compatible) client with model failover. Server only.
 *
 * Every Groq model has its own free-tier rate limit, so when one answers 429 (or is down) the next
 * model in GROQ_MODELS is tried. A request that is simply too big (413) is not retried elsewhere.
 */
const API = "https://api.groq.com/openai/v1/chat/completions";

export interface GroqToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}
export interface GroqMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_calls?: GroqToolCall[];
  tool_call_id?: string;
}

export class GroqBusy extends Error {}

export function groqModels(): string[] {
  const raw = process.env.GROQ_MODELS ?? "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b";
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function extraParams(model: string): Record<string, unknown> {
  // gpt-oss models "think" before answering; keep it short so the answer fits the token budget
  return model.startsWith("openai/gpt-oss") ? { reasoning_effort: "low" } : {};
}

interface CallOptions {
  tools?: unknown[];
  maxTokens?: number;
  json?: boolean;
  stream?: boolean;
  temperature?: number;
}

async function request(model: string, messages: GroqMessage[], o: CallOptions): Promise<Response> {
  const body: Record<string, unknown> = {
    model,
    messages,
    temperature: o.temperature ?? 0.2,
    max_tokens: o.maxTokens ?? 900,
    stream: o.stream ?? false,
    ...extraParams(model),
  };
  if (o.tools) {
    body.tools = o.tools;
    body.tool_choice = "auto";
  }
  if (o.json) body.response_format = { type: "json_object" };
  return fetch(API, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.GROQ_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function withFailover(messages: GroqMessage[], o: CallOptions): Promise<{ res: Response; model: string }> {
  if (!process.env.GROQ_API_KEY) throw new Error("GROQ_API_KEY is not set on the server.");
  const problems: string[] = [];
  for (const model of groqModels()) {
    let res: Response;
    try {
      res = await request(model, messages, o);
    } catch (e) {
      problems.push(`${model}: network error`);
      continue;
    }
    if (res.ok) return { res, model };
    const text = await res.text();
    const retryable = [404, 408, 429, 500, 502, 503, 504].includes(res.status) || (res.status === 400 && /model/i.test(text));
    if (!retryable) throw new Error(`Groq ${res.status}: ${text.slice(0, 300)}`);
    problems.push(`${model}: HTTP ${res.status}`);
  }
  throw new GroqBusy(`All Groq models are busy or rate-limited (${problems.join("; ")}). Wait a minute and try again.`);
}

/** One non-streaming completion (used for tool calling and JSON output). */
export async function chatOnce(messages: GroqMessage[], o: CallOptions = {}) {
  const { res, model } = await withFailover(messages, { ...o, stream: false });
  const data = await res.json();
  const message = data.choices?.[0]?.message as GroqMessage & { content: string | null };
  return { message, model, usage: data.usage };
}

/** Removes <think>...</think> blocks some models put into the visible answer. */
export function stripThink(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/g, "").replace(/^\s+/, "");
}

/** Streaming filter that hides <think>...</think>, even when a tag is split across chunks. */
export class ThinkFilter {
  private pending = "";
  private inThink = false;
  private static OPEN = "<think>";
  private static CLOSE = "</think>";

  /** Length of the longest suffix of `s` that is a proper prefix of `tag` (a tag that may continue in the next chunk). */
  private static partial(s: string, tag: string): number {
    for (let n = Math.min(tag.length - 1, s.length); n > 0; n--) if (tag.startsWith(s.slice(s.length - n))) return n;
    return 0;
  }

  push(piece: string): string {
    this.pending += piece;
    let out = "";
    for (;;) {
      if (this.inThink) {
        const end = this.pending.indexOf(ThinkFilter.CLOSE);
        if (end < 0) {
          this.pending = this.pending.slice(this.pending.length - ThinkFilter.partial(this.pending, ThinkFilter.CLOSE));
          return out;
        }
        this.pending = this.pending.slice(end + ThinkFilter.CLOSE.length);
        this.inThink = false;
      } else {
        const start = this.pending.indexOf(ThinkFilter.OPEN);
        if (start < 0) {
          const keep = ThinkFilter.partial(this.pending, ThinkFilter.OPEN);
          out += this.pending.slice(0, this.pending.length - keep);
          this.pending = this.pending.slice(this.pending.length - keep);
          return out;
        }
        out += this.pending.slice(0, start);
        this.pending = this.pending.slice(start + ThinkFilter.OPEN.length);
        this.inThink = true;
      }
    }
  }

  /** End of stream: anything held back that is not inside a think block is real text. */
  flush(): string {
    const rest = this.inThink ? "" : this.pending;
    this.pending = "";
    return rest;
  }
}

/** Streams the answer text piece by piece. */
export async function* chatStream(messages: GroqMessage[], o: CallOptions = {}): AsyncGenerator<string> {
  const { res } = await withFailover(messages, { ...o, stream: true });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const filter = new ThinkFilter();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") {
        const tail = filter.flush();
        if (tail) yield tail;
        return;
      }
      let piece = "";
      try {
        piece = JSON.parse(payload).choices?.[0]?.delta?.content ?? "";
      } catch {
        continue;
      }
      if (!piece) continue;
      const out = filter.push(piece);
      if (out) yield out;
    }
  }
  const tail = filter.flush();
  if (tail) yield tail;
}
