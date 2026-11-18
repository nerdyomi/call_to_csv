"""Turn the model's raw JSON into one clean CEX row plus review issues.

Pure functions, no I/O: easy to unit-test and to reuse when the comparison step arrives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rules import apply_rules, derive_land, why_hidden
from .schema import ENG_NOTES, NOTES, Field, Schema

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_BN_SCRIPT = re.compile(r"[ঀ-৿]")


def format_ts(text: str) -> str:
    """'7' -> '00:00:07', '01:48' -> '00:01:48', '1:02:03' -> '01:02:03'. Unparseable input is returned as is."""
    t = (text or "").strip().translate(_BN_DIGITS)
    parts = t.split(":")
    if not t or not all(p.strip().isdigit() for p in parts) or len(parts) > 3:
        return t
    nums = [int(p) for p in parts]
    while len(nums) < 3:
        nums.insert(0, 0)
    h, m, s = nums
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class Issue:
    field: str
    kind: str          # low_confidence | invalid_value | unknown_code | duplicate | warning | not_in_schema
    detail: str


@dataclass
class CallRow:
    values: dict[str, str] = field(default_factory=dict)       # column -> cell text
    evidence: dict[str, dict] = field(default_factory=dict)    # column -> {value, confidence, evidence, timestamp}
    issues: list[Issue] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)       # [{speaker, time, text}]


def parse_number(text: str) -> str | None:
    """'৫০,০০০' -> '50000', '16.50' -> '16.5'. None if there is no clean number."""
    t = text.translate(_BN_DIGITS).replace(",", "").strip()
    if not _NUM_RE.fullmatch(t):
        return None
    n = float(t)
    return str(int(n)) if n == int(n) else f"{n:g}"


def _split_multi(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;|]", text) if p.strip()]


def _key(s: str) -> str:
    """Comparison form of an option code or label: case, spaces, '_' and '-' do not matter."""
    return re.sub(r"[\s_\-]+", "", s.lower().translate(_BN_DIGITS))


def match_option(f: Field, token: str) -> str | None:
    """The option CODE for something the AI wrote: the code itself, or its Bangla label, in any casing."""
    k = _key(token)
    for code, label in f.options:
        if k == _key(code) or k == _key(label):
            return code
    return None


def _normalize_value(f: Field, raw: str, closed: bool) -> tuple[str | None, str | None]:
    """Returns (clean value or None, problem text or None)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    if f.type == "number":
        n = parse_number(raw)
        return (n, None) if n is not None else (None, f"not a number: {raw!r}")
    if f.type in ("enum", "multi"):
        tokens = _split_multi(raw) if f.type == "multi" else [raw]
        good: list[str] = []
        bad: list[str] = []
        for t in tokens:
            code = match_option(f, t) if f.options else re.sub(r"\s+", "_", t.lower())
            if code is None:
                bad.append(t)
            elif code not in good:
                good.append(code)
        problem = None
        if bad:
            allowed = ", ".join(c for c, _ in f.options[:12]) + ("…" if len(f.options) > 12 else "")
            problem = f"not an option: {bad} (allowed: {allowed})"
            if not closed:                       # keep what was said, but make it visible
                good += [re.sub(r"\s+", "_", b.lower()) for b in bad]
                problem = "new code " + problem
        return (", ".join(good) or None), problem
    return raw, None


def build_row(raw: dict, schema: Schema) -> CallRow:
    row = CallRow()
    for item in raw.get("fields", []):
        name = item.get("field", "")
        f = schema.by_name.get(name)
        if f is None or f.source != "audio" or name in (NOTES, ENG_NOTES):
            row.issues.append(Issue(name, "not_in_schema", "model returned a field that is not an audio field"))
            continue
        if name in row.values:
            row.issues.append(Issue(name, "duplicate", f"returned more than once; kept the last: {item.get('value')!r}"))
        value, problem = _normalize_value(f, str(item.get("value", "")), schema.closed_enums)
        if problem:
            kind = "unknown_code" if problem.startswith("new code") else "invalid_option" if problem.startswith("not an option") else "invalid_value"
            row.issues.append(Issue(name, kind, problem))
        if value is None:
            row.values.pop(name, None)
            row.evidence.pop(name, None)
            continue
        row.values[name] = value
        row.evidence[name] = {k: item.get(k, "") for k in ("confidence", "evidence", "timestamp")} | {"value": value}
        row.evidence[name]["timestamp"] = format_ts(row.evidence[name]["timestamp"])
        if item.get("confidence") == "low":
            row.issues.append(Issue(name, "low_confidence", item.get("evidence", "")))

    # --- the form's own rules: drop answers to questions it would not have asked, flag what is unverifiable or missing
    outcome = apply_rules(schema, row.values)
    for key, value in outcome.dropped.items():
        row.values.pop(key, None)
        row.evidence.pop(key, None)
        row.issues = [i for i in row.issues if not (i.field == key and i.kind == "low_confidence")]
        row.issues.append(Issue(key, "not_applicable", f"answered {value!r}, but the form only asks this when {why_hidden(schema, key)}; answer dropped"))
    for gate, deps in outcome.unverified.items():
        row.issues.append(Issue(gate, "missing_gate", f"{len(deps)} answer(s) depend on `{gate}`, which was not extracted: {', '.join(deps[:6])}{'…' if len(deps) > 6 else ''}"))
    if outcome.missing_required:
        n = len(outcome.missing_required)
        row.issues.append(Issue("", "missing_required", f"{n} required question(s) that apply to this loan have no answer: {', '.join(outcome.missing_required[:12])}{'…' if n > 12 else ''}"))

    # --- land in decimals, calculated from the unit, the amounts and the stated conversion
    calc, why = derive_land(row.values)
    for key, value in calc.items():
        row.values[key] = value
        row.evidence[key] = {"value": value, "confidence": "calculated", "evidence": why[key], "timestamp": ""}

    row.values[NOTES] = (raw.get("notes") or "").strip()
    row.values[ENG_NOTES] = (raw.get("eng_notes") or "").strip()

    prev = -1
    for turn in raw.get("transcript") or []:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        time = format_ts(turn.get("time", ""))
        secs = sum(int(x) * m for x, m in zip(reversed(time.split(":")), (1, 60, 3600))) if re.fullmatch(r"\d\d:\d\d:\d\d", time) else None
        if secs is not None and secs < prev:
            row.issues.append(Issue("", "warning", f"transcript time goes backwards at {time}"))
        prev = max(prev, secs if secs is not None else prev)
        row.transcript.append({"speaker": turn.get("speaker", "other"), "time": time, "text": text})

    if any(_BN_SCRIPT.search(t["text"]) for t in row.transcript):
        row.issues.append(Issue("", "warning", "transcript contains Bangla-script characters (expected Banglish only)"))

    ca = raw.get("call_assessment") or {}
    if not ca.get("is_kyc_call", True):
        row.issues.append(Issue("", "warning", "model says this is not a KYC call"))
    if ca.get("respondent_is_farmer") in ("no", "unclear"):
        row.issues.append(Issue("", "warning", f"respondent_is_farmer = {ca['respondent_is_farmer']}"))
    if ca.get("audio_quality") == "poor":
        row.issues.append(Issue("", "warning", "poor audio quality"))
    for w in raw.get("warnings") or []:
        row.issues.append(Issue("", "warning", w))
    return row
