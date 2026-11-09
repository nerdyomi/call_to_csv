import { afterEach, describe, expect, it, vi } from "vitest";
import { isValidDate, normalizePhone, parseRecordingName, safeStorageName, stripAudioExtensions } from "../lib/filename";
import { hmsToSeconds, callLabel } from "../lib/format";
import { aggregate, matches, runTool, searchCalls, type Row } from "../lib/tools";
import { normalizeBehaviour, parseJson } from "../lib/behaviour";
import { buildCallContext, estimateTokens } from "../lib/context";
import { chatOnce, chatStream, stripThink } from "../lib/groq";
import type { Call, CallResult } from "../lib/types";

describe("recording file names", () => {
  it("reads phone and date from the CEX naming pattern", () => {
    expect(parseRecordingName("20261101-183111_IFARMER__4004_01727641576-all.mp3")).toEqual({ phone: "8801727641576", date: "2026-11-01" });
    expect(parseRecordingName("20261025-114133_IFARMERR__4004_01745196254-all.mp3")).toEqual({ phone: "8801745196254", date: "2026-10-25" });
  });
  it("handles a bare phone number and double extensions, with no date", () => {
    expect(parseRecordingName("01762709049.mp3.mpeg")).toEqual({ phone: "8801762709049", date: null });
    expect(stripAudioExtensions("01762709049.mp3.mpeg")).toBe("01762709049");
  });
  it("returns null when there is no phone number", () => {
    expect(parseRecordingName("recording.mp3").phone).toBeNull();
  });
  it("normalises phone numbers typed by hand", () => {
    for (const p of ["01762709049", "1762709049", "8801762709049", "+88 01762-709049"]) expect(normalizePhone(p)).toBe("8801762709049");
    expect(normalizePhone("12345")).toBeNull();
  });
  it("validates dates and makes storage-safe names", () => {
    expect(isValidDate("2026-11-01")).toBe(true);
    expect(isValidDate("2026-02-30")).toBe(false);
    expect(isValidDate("01/11/2026")).toBe(false);
    expect(safeStorageName("কল রেকর্ড (1).mp3")).toBe("_1_.mp3");
  });
  it("formats call labels as phone · date (seq)", () => {
    expect(callLabel({ phone: "8801", call_date: null, call_seq: 1 })).toBe("8801 · none");
    expect(callLabel({ phone: "8801", call_date: "2026-11-01", call_seq: 2 })).toBe("8801 · 2026-11-01 (2)");
    expect(hmsToSeconds("00:02:33")).toBe(153);
    expect(hmsToSeconds("02:33")).toBe(153);
  });
});

const rows: Row[] = [
  { id: "a", phone: "8801", date: "2026-11-01", seq: 1, fields: { loan_amount: "40000", own: "16.5", farmland: "own, lease_mortgage", monthly_expenses: "8000" }, notes: "", eng_notes: "wife has a loan" },
  { id: "b", phone: "8802", date: "2026-11-02", seq: 1, fields: { loan_amount: "50000", own: "108", monthly_expenses: "3000" }, notes: "", eng_notes: "" },
  { id: "c", phone: "8803", date: null, seq: 2, fields: { loan_amount: "9500", farmland: "own" }, notes: "", eng_notes: "" },
];

describe("global chat tools (exact numbers)", () => {
  it("sums, averages and counts", () => {
    expect(aggregate(rows, { op: "sum", field: "loan_amount" })).toEqual({ calls_considered: 3, result: 99500 });
    expect(aggregate(rows, { op: "avg", field: "monthly_expenses" }).result).toBe(5500);
    expect(aggregate(rows, { op: "count" }).result).toBe(3);
    expect(aggregate(rows, { op: "count", field: "own" }).result).toBe(2);
    expect(aggregate(rows, { op: "max", field: "loan_amount" }).result).toBe(50000);
  });
  it("filters numerically, not alphabetically", () => {
    // as text "9500" > "40000", as numbers it is smaller
    expect(searchCalls(rows, { filters: [{ field: "loan_amount", op: "gt", value: 20000 }], fields: ["loan_amount"] }).rows.map((r) => r.call))
      .toEqual(["8801|2026-11-01", "8802|2026-11-02"]);
  });
  it("supports contains / in / empty / nonempty and pseudo fields", () => {
    expect(matches(rows[0], { field: "farmland", op: "contains", value: "lease" })).toBe(true);
    expect(matches(rows[2], { field: "own", op: "empty" })).toBe(true);
    expect(matches(rows[1], { field: "farmland", op: "nonempty" })).toBe(false);
    expect(matches(rows[0], { field: "phone", op: "in", value: ["8801", "8809"] })).toBe(true);
    expect(matches(rows[0], { field: "eng_notes", op: "contains", value: "wife" })).toBe(true);
    expect(matches(rows[2], { field: "date", op: "empty" })).toBe(true);
  });
  it("groups results and sorts", () => {
    const g = aggregate(rows, { op: "sum", field: "loan_amount", group_by: "farmland" }) as any;
    expect(g.groups.find((x: any) => x.farmland === "own").result).toBe(9500);
    const s = searchCalls(rows, { sort_by: "loan_amount", sort_dir: "desc", fields: ["loan_amount"], limit: 2 });
    expect(s.total_matching).toBe(3);
    expect(s.rows.map((r) => (r as Record<string, unknown>).loan_amount)).toEqual(["50000", "40000"]);
    expect(s.rows[0].call).toBe("8802|2026-11-02");
  });
  it("marks calls with a sequence number and survives bad tool input", () => {
    expect(searchCalls(rows, { fields: ["own"] }).rows[2].call).toBe("8803|none(2)");
    expect(JSON.parse(runTool("search_calls", "{not json", rows)).error).toBeTruthy();
    expect(JSON.parse(runTool("nope", "{}", rows)).error).toBeTruthy();
    expect(JSON.parse(runTool("aggregate", JSON.stringify({ op: "sum", field: "loan_amount" }), rows)).result).toBe(99500);
  });
});

describe("behaviour analysis parsing", () => {
  it("accepts fenced JSON and think blocks", () => {
    expect((parseJson('<think>hmm</think>```json\n{"overall":"ok"}\n```') as any).overall).toBe("ok");
    expect((parseJson('Here you go: {"overall":"x"} thanks') as any).overall).toBe("x");
    expect(() => parseJson("no json here")).toThrow();
  });
  it("fills missing and invalid parts with safe defaults", () => {
    const b = normalizeBehaviour({ overall: "Calm farmer", cooperation: { level: "very high", why: "" }, red_flags: [{ point: "changed answer", time: "00:01:00" }, { nope: 1 }], follow_up_questions: ["a", 3, ""] });
    expect(b.overall).toBe("Calm farmer");
    expect(b.cooperation.level).toBe("medium");
    expect(b.consistency.level).toBe("mostly_consistent");
    expect(b.red_flags).toEqual([{ point: "changed answer", time: "00:01:00" }]);
    expect(b.follow_up_questions).toEqual(["a"]);
    expect(b.positives).toEqual([]);
  });
});

describe("per-call chat context", () => {
  const call = { phone: "8801762709049", call_date: null, call_seq: 1, duration_seconds: 835, file_name: "x.mp3" } as Call;
  const turns = Array.from({ length: 400 }, (_, i) => `CEX: ami ${i} ta proshno korchi ekhon apnake (00:00:${String(i % 60).padStart(2, "0")})`).join("\n");
  const result = {
    fields: { loan_amount: "50000", current_landsize: "486" },
    evidence: { loan_amount: { confidence: "high", evidence: "q", timestamp: "00:02:33" } },
    eng_notes: "Wants 50k.", notes: "n", review: [{ field: "", kind: "warning", detail: "land in bigha" }], transcript_text: turns, behaviour: null,
  } as unknown as CallResult;

  it("puts fields first and keeps the prompt inside the token budget", () => {
    const ctx = buildCallContext(call, result, 3000);
    expect(ctx.indexOf("loan_amount = 50000 [high @00:02:33]")).toBeLessThan(ctx.indexOf("CONVERSATION TRANSCRIPT"));
    expect(estimateTokens(ctx)).toBeLessThanOrEqual(3000 + 80);
    expect(ctx).toContain("[transcript cut here");
    expect(ctx).toContain("land in bigha");
  });
  it("keeps a short transcript whole", () => {
    const ctx = buildCallContext(call, { ...result, transcript_text: "CEX: hello (00:00:01)" } as CallResult);
    expect(ctx).toContain("CEX: hello (00:00:01)");
    expect(ctx).not.toContain("cut here");
  });
});

describe("Groq failover (network mocked)", () => {
  const OLD = process.env;
  afterEach(() => { vi.unstubAllGlobals(); process.env = OLD; });

  const ok = (content: string) => new Response(JSON.stringify({ choices: [{ message: { role: "assistant", content } }] }), { status: 200 });
  const sse = (...pieces: string[]) =>
    new Response(new ReadableStream({ start(c) { pieces.forEach((p) => c.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ choices: [{ delta: { content: p } }] })}\n\n`))); c.enqueue(new TextEncoder().encode("data: [DONE]\n\n")); c.close(); } }), { status: 200 });

  it("moves to the next model on 429 and reports which one answered", async () => {
    process.env = { ...OLD, GROQ_API_KEY: "k", GROQ_MODELS: "m1,m2,m3" };
    const used: string[] = [];
    vi.stubGlobal("fetch", async (_u: string, init: RequestInit) => {
      const model = JSON.parse(init.body as string).model;
      used.push(model);
      return model === "m1" ? new Response("rate limited", { status: 429 }) : ok("hello");
    });
    const r = await chatOnce([{ role: "user", content: "hi" }]);
    expect(used).toEqual(["m1", "m2"]);
    expect(r.model).toBe("m2");
    expect(r.message.content).toBe("hello");
  });
  it("gives a friendly error when every model is busy, and does not retry a too-large request", async () => {
    process.env = { ...OLD, GROQ_API_KEY: "k", GROQ_MODELS: "m1,m2" };
    vi.stubGlobal("fetch", async () => new Response("slow down", { status: 429 }));
    await expect(chatOnce([{ role: "user", content: "hi" }])).rejects.toThrow(/busy or rate-limited/);
    let calls = 0;
    vi.stubGlobal("fetch", async () => { calls++; return new Response("Request too large", { status: 413 }); });
    await expect(chatOnce([{ role: "user", content: "hi" }])).rejects.toThrow(/413/);
    expect(calls).toBe(1);
  });
  it("streams text and hides <think> blocks even when split across chunks", async () => {
    process.env = { ...OLD, GROQ_API_KEY: "k", GROQ_MODELS: "m1" };
    vi.stubGlobal("fetch", async () => sse("<thi", "nk>secret reasoning</th", "ink>Answer ", "part two"));
    let out = "";
    for await (const piece of chatStream([{ role: "user", content: "q" }])) out += piece;
    expect(out).toBe("Answer part two");
    expect(stripThink("<think>x</think>  final")).toBe("final");
  });
  it("sends reasoning_effort only to gpt-oss models", async () => {
    process.env = { ...OLD, GROQ_API_KEY: "k", GROQ_MODELS: "openai/gpt-oss-120b,qwen/qwen3.8-27b" };
    const bodies: any[] = [];
    vi.stubGlobal("fetch", async (_u: string, init: RequestInit) => { bodies.push(JSON.parse(init.body as string)); return bodies.length === 1 ? new Response("x", { status: 503 }) : ok("fine"); });
    await chatOnce([{ role: "user", content: "hi" }]);
    expect(bodies[0].reasoning_effort).toBe("low");
    expect(bodies[1].reasoning_effort).toBeUndefined();
  });
});

describe("ThinkFilter", () => {
  it("handles tags split at every possible position", async () => {
    const { ThinkFilter } = await import("../lib/groq");
    const full = "Hi <think>private</think>there <b>ok</b>";
    for (let cut = 1; cut < full.length; cut++) {
      const f = new ThinkFilter();
      expect(f.push(full.slice(0, cut)) + f.push(full.slice(cut)) + f.flush()).toBe("Hi there <b>ok</b>");
    }
  });
  it("keeps a lone '<' that is not a think tag", async () => {
    const { ThinkFilter } = await import("../lib/groq");
    const f = new ThinkFilter();
    expect(f.push("a < b and <th") + f.push("is> c") + f.flush()).toBe("a < b and <this> c");
  });
});
