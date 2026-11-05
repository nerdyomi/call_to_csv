"""Optional manifest.csv: call-system / loan-app columns that are not in the audio.

Layout: first column `recording_file` (file name, with or without extension), then any
CEX columns (Call ID, Customer ID, loan_id, Agent, ...). Extra columns are ignored.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .audio import recording_stem


def load_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "recording_file" not in reader.fieldnames:
            raise SystemExit(f"{path}: needs a 'recording_file' column")
        out: dict[str, dict[str, str]] = {}
        for r in reader:
            key = recording_stem((r.pop("recording_file") or "").strip())
            if key:
                out[key] = {k: (v or "").strip() for k, v in r.items() if k and v and v.strip()}
        return out
