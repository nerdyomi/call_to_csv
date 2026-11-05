from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import sys

from pathlib import Path

from . import cost, evaluate, pipeline
from .schema import load_schema
from .config import load_settings


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="call-pipeline", description="Call recordings -> CEX CSV via Gemini")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="process new recordings and (re)write the CSVs")
    r.add_argument("--file", nargs="+", type=Path, metavar="AUDIO",
                   help="process just these audio files (any location) instead of the input folder")
    r.add_argument("--model", help="use this Gemini model for this run only (overrides GEMINI_MODEL)")
    r.add_argument("--force", action="store_true", help="re-extract even if a cached result exists")
    r.add_argument("--limit", type=int, help="process at most N recordings (handy for a first test)")
    r.add_argument("--only", nargs="+", help="only recordings whose file name contains one of these strings")

    sub.add_parser("rebuild", help="rewrite the CSVs from cached results, no API calls")

    e = sub.add_parser("evaluate", help="score output/ against hand-filled CEX sheets")
    e.add_argument("--truth", nargs="+", required=True, type=Path, help="one or more hand-filled CEX csv files")

    c = sub.add_parser("cost", help="token / cost numbers")
    c.add_argument("what", choices=["estimate", "report"])
    c.add_argument("--exact", action="store_true", help="estimate: count tokens via the API (needs key)")
    c.add_argument("--calls-per-day", type=int, default=200)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "google_genai", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "run":
        s = load_settings()
        if args.model:
            s = replace(s, model=args.model)
        res = pipeline.run(s, force=args.force, limit=args.limit, only=args.only, files=args.file)
        print(f"\nDone: {res['ok']} extracted, {res['failed']} failed, {res['skipped']} already cached. "
              f"{res['rows']} rows in {s.output_dir / s.main_csv}")
        if res["failed"]:
            print(f"Failures are listed in {s.error_log}; re-run the same command to retry only those.")
            sys.exit(1)
    elif args.cmd == "rebuild":
        s = load_settings(require_key=False)
        print(f"{pipeline.rebuild(s)} rows written to {s.output_dir / s.main_csv}")
    elif args.cmd == "evaluate":
        s = load_settings(require_key=False)
        cells, n = evaluate.evaluate(s.output_dir, args.truth, load_schema(s.schema_path))
        if not cells:
            sys.exit("No recordings matched any row in the truth files (matching is by phone number).")
        path = evaluate.write_report(s.output_dir / "evaluation", cells, n, s.csv_encoding)
        print(path.read_text(encoding="utf-8"))
        print(f"\nDetails per cell: {path.parent / 'cells.csv'}")
    elif args.cmd == "cost":
        s = load_settings(require_key=args.what == "estimate" and args.exact)
        if args.what == "estimate":
            cost.estimate(s, exact=args.exact, calls_per_day=args.calls_per_day)
        else:
            cost.report(s)
