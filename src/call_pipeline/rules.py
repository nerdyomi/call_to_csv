"""The form's "ask only if ..." rules, applied to what the AI extracted.

Three-valued logic: a question is visible (True), hidden (False) or UNKNOWN (None) when the answer it depends on
was never extracted. We only drop an answer when the form would definitely not have asked it; unknown stays and
is flagged once, so a missed gate question does not wipe out good data.

Missing-answer semantics follow the form app: a gate question that was itself hidden counts as "no answer", so
`eq`/`in` are False and `neq` is True (e.g. `farmland` is asked when `agri_activity` is not 'no', and
`agri_activity` is only asked for non-farming loans, so farmers with a crop loan do see `farmland`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .schema import DERIVED, ENG_NOTES, NOTES, Schema, describe_condition

Answers = dict[str, list[str]]


def to_answers(values: dict[str, str], schema: Schema) -> Answers:
    """'own, lease_mortgage' -> ['own', 'lease_mortgage'] for every extracted value."""
    out: Answers = {}
    for k, v in values.items():
        f = schema.by_name.get(k)
        if f is None or not v:
            continue
        out[k] = [x.strip() for x in v.split(",") if x.strip()] if f.type == "multi" else [v.strip()]
    return out


def _all(vals: list[bool | None]) -> bool | None:
    if any(v is False for v in vals):
        return False
    return None if any(v is None for v in vals) else True


def _any(vals: list[bool | None]) -> bool | None:
    if any(v is True for v in vals):
        return True
    return None if any(v is None for v in vals) else False


class Visibility:
    """Evaluates whether each question would have been asked, given the extracted answers."""

    def __init__(self, schema: Schema, answers: Answers):
        self.schema, self.answers = schema, answers
        self._memo: dict[str, bool | None] = {}

    def visible(self, key: str, _stack: tuple[str, ...] = ()) -> bool | None:
        if key in self._memo:
            return self._memo[key]
        f = self.schema.by_name.get(key)
        vw = f.visible_when if f else None
        if not vw or key in _stack:
            return True if not vw else None
        mode = "all" if vw.get("all") else "any"
        res = (_all if mode == "all" else _any)([self._leaf(c, _stack + (key,)) for c in vw.get(mode) or []])
        self._memo[key] = res
        return res

    def _leaf(self, c: dict, stack: tuple[str, ...]) -> bool | None:
        have = self.answers.get(c["key"])
        op, want = c["op"], c["value"]
        if have is None:
            if self.visible(c["key"], stack) is False:     # the gate question was never asked
                return op == "neq"
            return None                                    # it should have been asked, but we have no answer
        if op == "eq":
            return want in have
        if op == "neq":
            return want not in have
        return any(v in have for v in want)                # op == "in"

    def unknown_gates(self, key: str) -> list[str]:
        """Gate questions that block a verdict for `key` because they have no extracted answer."""
        f = self.schema.by_name.get(key)
        vw = f.visible_when if f else None
        out: list[str] = []
        for c in (vw.get("all") or vw.get("any") or []) if vw else []:
            if c["key"] not in self.answers and self.visible(c["key"]) is not False:
                out.append(c["key"])
        return out


@dataclass
class RuleOutcome:
    dropped: dict[str, str] = field(default_factory=dict)          # key -> value, answers the form would not have asked
    unverified: dict[str, list[str]] = field(default_factory=dict)  # gate key -> keys that depend on it
    missing_required: list[str] = field(default_factory=list)       # visible, required, no answer


def apply_rules(schema: Schema, values: dict[str, str]) -> RuleOutcome:
    vis = Visibility(schema, to_answers(values, schema))
    out = RuleOutcome()
    for f in schema.question_fields:
        v = vis.visible(f.name)
        if f.name in values:
            if v is False:
                out.dropped[f.name] = values[f.name]
            elif v is None:
                for g in vis.unknown_gates(f.name):
                    out.unverified.setdefault(g, []).append(f.name)
        elif v is True and f.required:
            out.missing_required.append(f.name)
    return out


def why_hidden(schema: Schema, key: str) -> str:
    return describe_condition(schema.by_name[key].visible_when)


# --------------------------------------------------------------------------------------------- land maths
UNIT_FIELDS = ("katha", "bigha", "acre", "kora", "don", "kani", "gonda")


def _num(x: str | None) -> float | None:
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def derive_land(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Own / leased / total land in decimals from the unit the farmer used.

    Returns (values, explanation). Needs the unit (`farmland`), the amounts in that unit and, for units other than
    decimal, the conversion (`decimals_per_<unit>`) - exactly the answers the form collects.
    """
    unit = (values.get("farmland") or "").strip()
    if not unit:
        return {}, {}
    factor = 1.0 if unit == "decimal" else _num(values.get(f"decimals_per_{unit}"))
    if factor is None:
        return {}, {}
    out: dict[str, str] = {}
    why: dict[str, str] = {}
    totals = []
    for col, kind in (("calc_land_own_decimals", "own"), ("calc_land_lease_decimals", "lease_mortgage")):
        amount = _num(values.get(f"{unit}_{kind}"))
        if amount is None:
            continue
        dec = amount * factor
        out[col] = f"{dec:g}"
        why[col] = f"{amount:g} {unit}" + ("" if unit == "decimal" else f" x {factor:g} decimals per {unit}") + f" = {dec:g}"
        totals.append(dec)
    if totals:
        out["calc_land_total_decimals"] = f"{sum(totals):g}"
        why["calc_land_total_decimals"] = " + ".join(f"{t:g}" for t in totals) + f" = {sum(totals):g}"
    return out, why


NOT_QUESTIONS = {NOTES, ENG_NOTES, *(n for n, _ in DERIVED)}
