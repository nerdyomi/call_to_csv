"""Compare pipeline output with hand-filled CEX sheets (the ground truth) and score it.

Rows are matched by the last 10 digits of the phone number, so '+8801727641576',
'8801745196254' and '01745196254' all match.

Cell statuses (truth = hand-filled CEX, pred = pipeline):
  match      both filled, same value
  mismatch   both filled, different value
  missed     truth filled, pipeline blank
  extra      truth blank, pipeline filled   (could be a model hallucination OR an agent omission)
  (both blank cells are not counted)

Headline accuracy uses structured fields only (number / enum / multi). Free-text fields are
compared too, but exact string equality is the wrong test for them, so they are reported apart.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from .normalize import parse_number
from .schema import Schema

UNIT_FACTOR_FIELDS = ("yield",)  # model reports kg, hand-filled sheet may hold maund (x40)


def phone_key(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    return digits[-10:]


def _canon(value: str, ftype: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if ftype == "number":
        return parse_number(v) or v.lower()
    if ftype == "multi":
        return ", ".join(sorted({re.sub(r"\s+", "_", p.strip().lower()) for p in re.split(r"[,;|]", v) if p.strip()}))
    if ftype == "enum":
        return re.sub(r"\s+", "_", v.lower())
    return re.sub(r"\s+", " ", v.lower())


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_truth(paths: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in paths:
        for r in _read(p):
            k = phone_key(r.get("Phone", ""))
            if k:  # the first reference file contains blank template rows
                out[k] = r
    return out


def compare(pred_rows: list[dict], truth: dict[str, dict], schema: Schema,
            evidence: dict[tuple[str, str], dict] | None = None) -> list[dict]:
    evidence = evidence or {}
    cells = []
    for pred in pred_rows:
        key = phone_key(pred.get("Phone", ""))
        t = truth.get(key)
        if t is None:
            continue
        rec = f"{pred.get('Started at', '')[:10]} {pred.get('Phone', '')}"
        for f in schema.audio_fields:
            if f.name in ("Notes", "eng_notes") or f.name not in t:
                continue  # field not in that truth sheet's form version
            tv, pv = _canon(t[f.name], f.type), _canon(pred.get(f.name, ""), f.type)
            if not tv and not pv:
                continue
            status = "match" if tv == pv else "mismatch" if tv and pv else "missed" if tv else "extra"
            note = ""
            if status == "mismatch" and f.name.endswith(UNIT_FACTOR_FIELDS):
                a, b = parse_number(tv), parse_number(pv)
                if a and b and float(b) == float(a) * 40:
                    note = "x40 (sheet likely in maund, model in kg)"
            ev = evidence.get((pred.get("_stem", ""), f.name), {})
            cells.append({"recording": rec, "stem": pred.get("_stem", ""), "field": f.name, "type": f.type,
                          "truth": t[f.name], "pred": pred.get(f.name, ""), "status": status, "note": note,
                          "confidence": ev.get("confidence", ""), "timestamp": ev.get("timestamp", ""),
                          "evidence": ev.get("evidence", "")})
    return cells


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def summarize(cells: list[dict], n_calls: int) -> str:
    structured = [c for c in cells if c["type"] != "text"]
    lines = [f"# Evaluation summary ({n_calls} calls)", ""]

    def block(title: str, subset: list[dict]) -> None:
        cnt = defaultdict(int)
        for c in subset:
            cnt[c["status"]] += 1
        truth_filled = cnt["match"] + cnt["mismatch"] + cnt["missed"]
        pred_filled = cnt["match"] + cnt["mismatch"] + cnt["extra"]
        lines.append(f"## {title}")
        lines.append(f"- hand-filled cells: {truth_filled}; pipeline-filled cells: {pred_filled}")
        lines.append(f"- **recall** (hand-filled cells the pipeline got right): {_pct(cnt['match'], truth_filled)}"
                     f"  ({cnt['match']}/{truth_filled})")
        lines.append(f"- **precision** (pipeline cells that equal the hand-filled value): {_pct(cnt['match'], pred_filled)}"
                     f"  ({cnt['match']}/{pred_filled})")
        lines.append(f"- mismatch {cnt['mismatch']} | missed {cnt['missed']} | extra {cnt['extra']}")
        lines.append("")

    block("Structured fields (number / enum / multi) - the headline", structured)
    block("Free-text fields (exact match is harsh here - judge by eye)", [c for c in cells if c["type"] == "text"])

    lines += ["## By confidence the model gave (structured; does 'high' really mean right?)", "",
              "| confidence | cells | correct | % correct |", "|---|---|---|---|"]
    for conf in ("high", "medium", "low"):
        sub = [c for c in structured if c["confidence"] == conf and c["status"] in ("match", "mismatch")]
        ok = sum(c["status"] == "match" for c in sub)
        lines.append(f"| {conf} | {len(sub)} | {ok} | {_pct(ok, len(sub))} |")
    lines.append("")

    lines += ["## Per call (structured)", "", "| call | hand-filled | recall | precision | mismatch | missed | extra |",
              "|---|---|---|---|---|---|---|"]
    for rec in sorted({c["recording"] for c in structured}):
        sub = [c for c in structured if c["recording"] == rec]
        n = defaultdict(int)
        for c in sub:
            n[c["status"]] += 1
        tf, pf = n["match"] + n["mismatch"] + n["missed"], n["match"] + n["mismatch"] + n["extra"]
        lines.append(f"| {rec} | {tf} | {_pct(n['match'], tf)} | {_pct(n['match'], pf)} | "
                     f"{n['mismatch']} | {n['missed']} | {n['extra']} |")
    lines.append("")

    by_field: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in cells:
        by_field[c["field"]][c["status"]] += 1
    bad = sorted(((f, s) for f, s in by_field.items() if s["match"] < sum(s.values())),
                 key=lambda x: -(sum(x[1].values()) - x[1]["match"]))
    lines += ["## Fields that went wrong most often", "", "| field | match | mismatch | missed | extra |", "|---|---|---|---|---|"]
    for f, s in bad[:25]:
        lines.append(f"| {f} | {s['match']} | {s['mismatch']} | {s['missed']} | {s['extra']} |")
    lines.append("")

    x40 = [c for c in cells if c["note"]]
    if x40:
        lines += [f"## Unit note: {len(x40)} yield cells differ exactly by x40", "",
                  "These are cases where the hand-filled number looks like maund while the pipeline reports kg "
                  "(1 maund = 40 kg). They are counted as mismatches above.", ""]
    return "\n".join(lines)


def write_report(out_dir: Path, cells: list[dict], n_calls: int, encoding: str = "utf-8-sig") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["recording", "field", "type", "status", "truth", "pred", "confidence", "timestamp", "evidence", "note"]
    with (out_dir / "cells.csv").open("w", encoding=encoding, newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        order = {"mismatch": 0, "missed": 1, "extra": 2, "match": 3}
        w.writerows(sorted(cells, key=lambda c: (c["recording"], order[c["status"]], c["field"])))
    summary = out_dir / "summary.md"
    summary.write_text(summarize(cells, n_calls), encoding="utf-8")
    return summary


def evaluate(output_dir: Path, truth_paths: list[Path], schema: Schema) -> tuple[list[dict], int]:
    """Reads each output/<recording>/CEX.csv + evidence.csv, so it also works on partial runs."""
    preds, evidence = [], {}
    for d in sorted(p for p in output_dir.iterdir() if (p / "CEX.csv").exists()):
        for row in _read(d / "CEX.csv"):
            row["_stem"] = d.name
            preds.append(row)
        for r in _read(d / "evidence.csv"):
            evidence[(d.name, r["field"])] = r
    cells = compare(preds, load_truth(truth_paths), schema, evidence)
    return cells, len({c["recording"] for c in cells})
