"""Write CEX.csv (same columns/order as the CEX form), plus evidence.csv and review.csv."""
from __future__ import annotations

import csv
from pathlib import Path

from .normalize import CallRow
from .schema import Schema


def _write(path: Path, header: list[str], rows: list[dict], encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding=encoding, newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)  # never leave a half-written CSV behind


EVIDENCE_COLS = ["recording", "field", "value", "confidence", "evidence", "timestamp"]
REVIEW_COLS = ["recording", "field", "kind", "detail"]


def format_transcript(turns: list[dict]) -> str:
    """'CEX: as salam oa alaikum. (00:00:07)' one line per turn."""
    return "\n".join(f"{t['speaker']}: {t['text']} ({t['time']})" for t in turns) + ("\n" if turns else "")


def write_outputs(out_dir: Path, results: dict[str, tuple[CallRow, dict[str, str]]], schema: Schema,
                  encoding: str, main_csv: str, evidence_csv: str, review_csv: str,
                  transcript_file: str = "transcript.txt") -> None:
    """`results`: recording stem -> (CallRow, base values from manifest/filename).

    Writes output/<stem>/{CEX,evidence,review}.csv for each call and the same three files
    combined (all calls) in output/.
    """
    all_main, all_ev, all_review = [], [], []
    for stem in sorted(results):
        row, base = results[stem]
        merged = {**base, **row.values}
        main = {c: merged.get(c, "") for c in schema.columns}
        ev = [{"recording": stem, "field": col, **e} for col, e in row.evidence.items()]
        rev = [{"recording": stem, "field": i.field, "kind": i.kind, "detail": i.detail} for i in row.issues]
        d = out_dir / stem
        _write(d / main_csv, schema.columns, [main], encoding)
        _write(d / evidence_csv, EVIDENCE_COLS, ev, encoding)
        _write(d / review_csv, REVIEW_COLS, rev, encoding)
        if row.transcript:
            (d / transcript_file).write_text(format_transcript(row.transcript), encoding="utf-8")
        all_main.append(main)
        all_ev += ev
        all_review += rev
    _write(out_dir / main_csv, schema.columns, all_main, encoding)
    _write(out_dir / evidence_csv, EVIDENCE_COLS, all_ev, encoding)
    _write(out_dir / review_csv, REVIEW_COLS, all_review, encoding)
