"""Token / cost calculator.

    python scripts/estimate_cost.py                 # forecast for recordings in input/recordings
    python scripts/estimate_cost.py --exact         # exact token counts via the API
    python scripts/estimate_cost.py --report        # real usage so far (output/usage.jsonl)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from call_pipeline import cost  # noqa: E402
from call_pipeline.config import load_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--report", action="store_true")
ap.add_argument("--exact", action="store_true")
ap.add_argument("--calls-per-day", type=int, default=200)
a = ap.parse_args()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
s = load_settings(require_key=a.exact and not a.report)
cost.report(s) if a.report else cost.estimate(s, exact=a.exact, calls_per_day=a.calls_per_day)
