import { NextRequest, NextResponse } from "next/server";
import { requireAllowedUser, supabaseService } from "@/lib/supabase/server";
import { GroqBusy } from "@/lib/groq";
import { generateBehaviour } from "@/lib/behaviour";
import type { Call, CallResult } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

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
    const { behaviour, model } = await generateBehaviour(call as Call, r);
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
