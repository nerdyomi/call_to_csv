"""The CEX form definition (config/schema.yaml): column order, types, meaning, known values."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

TYPES = {"text", "number", "enum", "multi"}
SOURCES = {"audio", "manifest"}


@dataclass(frozen=True)
class Field:
    name: str
    source: str
    type: str
    description: str
    known_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Schema:
    fields: tuple[Field, ...]
    closed_enums: bool = False
    by_name: dict[str, Field] = field(default_factory=dict, compare=False)

    @property
    def columns(self) -> list[str]:
        return [f.name for f in self.fields]

    @property
    def audio_fields(self) -> list[Field]:
        return [f for f in self.fields if f.source == "audio"]

    def catalog_text(self) -> str:
        """Compact field catalog that is appended to the system prompt."""
        lines = ["| field | type | known values | meaning |", "|---|---|---|---|"]
        for f in self.audio_fields:
            known = ", ".join(f.known_values) if f.known_values else ""
            lines.append(f"| {f.name} | {f.type} | {known} | {f.description} |")
        return "\n".join(lines)


def load_schema(path: Path) -> Schema:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    fields = []
    for raw in doc["fields"]:
        if raw["type"] not in TYPES:
            raise ValueError(f"{raw['name']}: unknown type {raw['type']!r}")
        if raw["source"] not in SOURCES:
            raise ValueError(f"{raw['name']}: unknown source {raw['source']!r}")
        fields.append(Field(raw["name"], raw["source"], raw["type"], raw.get("description", ""),
                            tuple(raw.get("known_values") or ())))
    names = [f.name for f in fields]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"duplicate field names in schema: {dupes}")
    return Schema(tuple(fields), bool(doc.get("closed_enums", False)), {f.name: f for f in fields})
