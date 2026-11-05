"""Turn the model's raw JSON into one clean CEX row plus review issues.

Pure functions, no I/O: easy to unit-test and to reuse when the comparison step arrives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Field, Schema

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


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


def parse_number(text: str) -> str | None:
    """'৫০,০০০' -> '50000', '16.50' -> '16.5'. None if there is no clean number."""
    t = text.translate(_BN_DIGITS).replace(",", "").strip()
    if not _NUM_RE.fullmatch(t):
        return None
    n = float(t)
    return str(int(n)) if n == int(n) else f"{n:g}"


def _split_multi(text: str) -> list[str]:
    seen: list[str] = []
    for part in re.split(r"[,;|]", text):
        p = re.sub(r"\s+", "_", part.strip().lower())
        if p and p not in seen:
            seen.append(p)
    return seen


def _normalize_value(f: Field, raw: str, closed: bool) -> tuple[str | None, str | None]:
    """Returns (clean value or None, problem text or None)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    if f.type == "number":
        n = parse_number(raw)
        return (n, None) if n is not None else (None, f"not a number: {raw!r}")
    if f.type == "enum":
        v = re.sub(r"\s+", "_", raw.lower())
        if f.known_values and v not in f.known_values:
            return (None, f"{v!r} not in {list(f.known_values)}") if closed else (v, f"new code {v!r}")
        return v, None
    if f.type == "multi":
        items = _split_multi(raw)
        new = [i for i in items if f.known_values and i not in f.known_values]
        if new and closed:
            items = [i for i in items if i not in new]
        return ", ".join(items) or None, (f"new code(s) {new}" if new else None)
    return raw, None


def build_row(raw: dict, schema: Schema) -> CallRow:
    row = CallRow()
    for item in raw.get("fields", []):
        name = item.get("field", "")
        f = schema.by_name.get(name)
        if f is None or f.source != "audio" or name in ("Notes", "eng_notes"):
            row.issues.append(Issue(name, "not_in_schema", "model returned a field that is not an audio field"))
            continue
        if name in row.values:
            row.issues.append(Issue(name, "duplicate", f"returned more than once; kept the last: {item.get('value')!r}"))
        value, problem = _normalize_value(f, str(item.get("value", "")), schema.closed_enums)
        if problem:
            kind = "unknown_code" if problem.startswith("new code") else "invalid_value"
            row.issues.append(Issue(name, kind, problem))
        if value is None:
            row.values.pop(name, None)
            row.evidence.pop(name, None)
            continue
        row.values[name] = value
        row.evidence[name] = {k: item.get(k, "") for k in ("confidence", "evidence", "timestamp")} | {"value": value}
        if item.get("confidence") == "low":
            row.issues.append(Issue(name, "low_confidence", item.get("evidence", "")))

    row.values["Notes"] = (raw.get("notes") or "").strip()
    row.values["eng_notes"] = (raw.get("eng_notes") or "").strip()

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
