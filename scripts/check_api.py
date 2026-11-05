"""Checks that the API key in .env works, without touching the pipeline.

    python scripts/check_api.py              # uses GEMINI_MODEL from .env
    python scripts/check_api.py --list       # also lists models your key can see
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from google import genai  # noqa: E402

from call_pipeline.config import load_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--list", action="store_true")
a = ap.parse_args()

s = load_settings()
print(f"key loaded: yes (ends with ...{s.api_key[-4:]}), model: {s.model}")
client = genai.Client(api_key=s.api_key)
try:
    if a.list:
        for m in client.models.list():
            print("  ", m.name)
    r = client.models.generate_content(model=s.model, contents="Reply with the single word: ok")
    print("RESPONSE:", (r.text or "").strip())
    print("RESULT: key and model work")
except Exception as exc:
    print("RESULT: FAILED\n", str(exc)[:600])
    sys.exit(1)
