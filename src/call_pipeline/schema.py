"""The extraction schema, built from the real form export (config/form/*.json) plus config/schema.yaml.

Every form question becomes a Field: key, the Bangla question, answer options (code + Bangla label), the
"ask only if" rule, a type, and an optional hint. Column order = metadata columns, Notes, the form questions
in form order, calculated columns, eng_notes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TYPES = {"text", "number", "enum", "multi"}
SOURCES = {"audio", "manifest", "derived", "meta"}
NOTES = "Notes"
ENG_NOTES = "eng_notes"

# keys that hold a number even though the form stores them as plain strings
_NUMERIC_KEY = re.compile(
    r"^(decimals_per_.*|(decimal|katha|bigha|acre|kora|don|kani|gonda)_(own|lease_mortgage)|number_of_.*|sold_.*_(number|profit)"
    r"|.*_(land_size|invest|yield|unit_price|sell|amount|duration|repaid_amount|capacity|price|cost|profit)"
    r"|income_from_.*|monthly_expenses|current_landsize|previous_year_landsize|loan_amount|invest|yield|unit_price|selling_price"
    r"|purchase_and_rearing_cost|if_\d_(purchase_price|duration|rearing_cost|sell))$"
)

# columns calculated by the pipeline from several answers (see normalize.derive_land)
DERIVED = [
    ("calc_land_own_decimals", "Own land in decimals (calculated from the unit, amount and conversion)"),
    ("calc_land_lease_decimals", "Leased / mortgaged land in decimals (calculated)"),
    ("calc_land_total_decimals", "Total land in decimals (calculated)"),
]


@dataclass(frozen=True)
class Field:
    name: str
    source: str                     # audio | manifest | derived | meta
    type: str                       # text | number | enum | multi
    description: str = ""           # the hint shown to the AI (may be empty)
    known_values: tuple[str, ...] = ()          # option codes
    label: str = ""                 # the Bangla question as the agent asks it
    options: tuple[tuple[str, str], ...] = ()   # (code, Bangla label)
    required: bool = False
    section: str = ""
    visible_when: dict | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Schema:
    fields: tuple[Field, ...]
    closed_enums: bool = False
    by_name: dict[str, Field] = field(default_factory=dict, compare=False)
    form_version: str = ""
    truth_aliases: dict = field(default_factory=dict, compare=False)          # old CEX column -> form key (evaluate only)
    truth_value_aliases: dict = field(default_factory=dict, compare=False)    # form key -> {old value: new value}

    @property
    def columns(self) -> list[str]:
        return [f.name for f in self.fields]

    @property
    def audio_fields(self) -> list[Field]:
        return [f for f in self.fields if f.source == "audio"]

    @property
    def question_fields(self) -> list[Field]:
        """Form questions the AI should answer from the call (no Notes)."""
        return [f for f in self.fields if f.source == "audio" and f.name not in (NOTES, ENG_NOTES)]

    def catalog_text(self) -> str:
        """The form as the AI sees it: sections in interview order, one line per question."""
        out: list[str] = []
        section = None
        for f in self.question_fields:
            if f.section != section:
                section = f.section
                out.append(f"\n## {section}")
            bits = [f"`{f.name}` [{f.type}{', required' if f.required else ''}] {f.label}".rstrip()]
            if f.options:
                bits.append("options: " + ", ".join(f"{c}={l}" for c, l in f.options))
            cond = describe_condition(f.visible_when)
            if cond:
                bits.append(f"ask only if: {cond}")
            if f.description:
                bits.append(f"note: {f.description}")
            out.append("- " + " | ".join(bits))
        return "\n".join(out).strip()


def describe_condition(vw: dict | None) -> str:
    """{'all': [{'op': 'eq', 'key': 'farmland', 'value': 'bigha'}]} -> 'farmland = bigha'."""
    if not vw:
        return ""
    for mode, joiner in (("all", " AND "), ("any", " OR ")):
        conds = vw.get(mode) or []
        if conds:
            parts = []
            for c in conds:
                v = c["value"]
                if c["op"] == "eq":
                    parts.append(f"{c['key']} = {v}")
                elif c["op"] == "neq":
                    parts.append(f"{c['key']} is not {v}")
                else:
                    parts.append(f"{c['key']} is one of [{', '.join(map(str, v))}]")
            return joiner.join(parts)
    return ""


def infer_type(key: str, form_type: str, has_options: bool) -> str:
    if form_type == "multi_select":
        return "multi"
    if has_options:
        return "enum"           # 'select', and 'text' questions that still have a fixed option list
    if form_type in ("integer", "decimal"):
        return "number"
    return "number" if _NUMERIC_KEY.match(key) else "text"


def load_schema(path: Path) -> Schema:
    path = Path(path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    form_path = (path.parent.parent / cfg["form"]).resolve() if not Path(cfg["form"]).is_absolute() else Path(cfg["form"])
    form = json.loads(form_path.read_text(encoding="utf-8"))
    overrides = cfg.get("overrides") or {}
    patterns = [(re.compile(p["match"]), p["hint"].strip()) for p in cfg.get("hint_patterns") or []]
    manifest_fields = set(cfg.get("manifest_fields") or [])

    fields: list[Field] = []
    for col in cfg.get("metadata_columns") or []:
        fields.append(Field(col, "meta", "text"))
    fields.append(Field(NOTES, "audio", "text", "Short summary of the call in romanized Bangla (Banglish)."))

    seen: set[str] = set()
    for sec in form["schema"]["sections"]:
        for q in sec["fields"]:
            key = q["key"]
            if key in seen:
                raise ValueError(f"duplicate question key in the form: {key}")
            seen.add(key)
            ov = overrides.get(key, {})
            options = tuple((o["code"], o["label"]) for o in q.get("options") or [])
            ftype = ov.get("type") or infer_type(key, q["type"], bool(options))
            if ftype not in TYPES:
                raise ValueError(f"{key}: unknown type {ftype!r}")
            hint = (ov.get("hint") or next((h for rx, h in patterns if rx.search(key)), "")).strip()
            fields.append(Field(
                name=key, source="manifest" if key in manifest_fields else "audio", type=ftype, description=hint,
                known_values=tuple(c for c, _ in options), label=q.get("label", "").strip(), options=options,
                required=bool(q.get("required")), section=sec["title"], visible_when=q.get("visible_when"),
            ))

    unknown = [k for k in overrides if k not in seen]
    if unknown:
        raise ValueError(f"overrides refer to questions that are not in the form: {unknown}")
    for name, desc in DERIVED:
        fields.append(Field(name, "derived", "number", desc))
    fields.append(Field(ENG_NOTES, "audio", "text", "Same summary as Notes, in plain English."))

    names = [f.name for f in fields]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate column names: {sorted({n for n in names if names.count(n) > 1})}")
    version = form.get("version", {}).get("number", "")
    return Schema(tuple(fields), bool(cfg.get("closed_enums", True)), {f.name: f for f in fields}, str(version),
                  dict(cfg.get("truth_aliases") or {}), dict(cfg.get("truth_value_aliases") or {}))
