"""Token and cost estimates.

estimate: forecast from audio durations (optionally exact prompt token counts via the API).
report:   real spend from output/usage.jsonl, written by `run`.
Prices come from config/pricing.yaml - verify them against Google's pricing page.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import yaml

from . import audio
from .config import Settings
from .prompting import USER_INSTRUCTION, build_system_prompt
from .schema import load_schema

CHARS_PER_TOKEN = 3.0  # conservative for English/markdown prompt text


@dataclass
class Rates:
    text_input: float
    audio_input: float
    output: float


def load_pricing(settings: Settings, model: str) -> tuple[Rates, dict]:
    cfg = yaml.safe_load(settings.pricing_path.read_text(encoding="utf-8"))
    if model not in cfg["models"]:
        raise SystemExit(f"No prices for model {model!r} in {settings.pricing_path}. Add it there.")
    return Rates(**cfg["models"][model]), cfg


def _money(usd: float, bdt_rate: float) -> str:
    return f"${usd:,.4f}  (~BDT {usd * bdt_rate:,.2f})"


def call_cost(rates: Rates, audio_tokens: int, text_tokens: int, output_tokens: int) -> float:
    return (audio_tokens * rates.audio_input + text_tokens * rates.text_input
            + output_tokens * rates.output) / 1_000_000


def estimate(settings: Settings, exact: bool = False, calls_per_day: int = 200) -> None:
    rates, cfg = load_pricing(settings, settings.model)
    schema = load_schema(settings.schema_path)
    system_prompt = build_system_prompt(settings, schema)
    recs = audio.discover(settings.input_dir, settings.audio_extensions)
    if not recs:
        print(f"No recordings in {settings.input_dir}")
        return

    est_text = int(len(system_prompt + USER_INSTRUCTION) / CHARS_PER_TOKEN)
    client = None
    if exact:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=settings.api_key)
        est_text = client.models.count_tokens(model=settings.model, contents=system_prompt + USER_INSTRUCTION).total_tokens

    out_tokens = int(cfg["assumed_output_tokens_per_call"])
    total_audio = total_text = total_cost = 0.0
    print(f"model: {settings.model}   ({'exact counts from API' if exact else 'estimated counts'})")
    print(f"{'recording':<58}{'sec':>7}{'audio tok':>11}{'text tok':>10}{'cost USD':>10}")
    for rec in recs:
        dur = audio.duration_seconds(rec.path) or 0
        a_tok = round(dur * cfg["audio_tokens_per_second"])
        if exact and client is not None:
            part = types.Part.from_bytes(data=rec.path.read_bytes(), mime_type=rec.mime_type)
            a_tok = max(client.models.count_tokens(model=settings.model, contents=[part]).total_tokens, 0)
        c = call_cost(rates, a_tok, est_text, out_tokens)
        total_audio += a_tok
        total_text += est_text
        total_cost += c
        print(f"{rec.name[:57]:<58}{dur:>7.0f}{a_tok:>11,}{est_text:>10,}{c:>10.4f}")

    n = len(recs)
    avg = total_cost / n
    rate = cfg["usd_to_bdt"]
    print(f"\n{n} recordings: {int(total_audio):,} audio tokens, {int(total_text):,} text tokens, "
          f"~{n * out_tokens:,} output tokens (assumed {out_tokens:,}/call)")
    print(f"batch total        : {_money(total_cost, rate)}")
    print(f"average per call   : {_money(avg, rate)}")
    print(f"{calls_per_day} calls/day       : {_money(avg * calls_per_day, rate)}  | per 30 days: "
          f"{_money(avg * calls_per_day * 30, rate)}")
    print("Free tier: you are billed nothing, but this is what the same usage costs on the paid tier.")


def report(settings: Settings) -> None:
    if not settings.usage_log.exists():
        print(f"No usage yet ({settings.usage_log} does not exist). Run the pipeline first.")
        return
    cfg = yaml.safe_load(settings.pricing_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in settings.usage_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_model: dict[str, list[dict]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r)
    grand = 0.0
    for model, items in by_model.items():
        if model not in cfg["models"]:
            print(f"{model}: no prices in pricing.yaml, skipped")
            continue
        rates = Rates(**cfg["models"][model])
        a = sum(i.get("audio_prompt_tokens", 0) for i in items)
        p = sum(i.get("prompt_tokens", 0) for i in items)
        o = sum(i.get("output_tokens", 0) + i.get("thought_tokens", 0) for i in items)
        cost = call_cost(rates, a, max(p - a, 0), o)
        grand += cost
        n = len(items)
        print(f"{model}: {n} calls | prompt {p:,} (audio {a:,}) | output+thinking {o:,} "
              f"| {_money(cost, cfg['usd_to_bdt'])} | avg {_money(cost / n, cfg['usd_to_bdt'])}/call")
    print(f"TOTAL (paid-tier equivalent): {_money(grand, cfg['usd_to_bdt'])}")
    print("Note: re-processed recordings (--force) appear once per attempt.")
