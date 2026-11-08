"""Checks that every Gemini key in .env works (one tiny text request per key). Prints only the last 4 characters.

    python scripts/check_api.py                 # each key, main model
    python scripts/check_api.py --model gemini-3.6-flash
    python scripts/check_api.py --list          # also list models the first key can see
"""
import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from google import genai  # noqa: E402

from call_pipeline.config import load_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--list", action="store_true")
ap.add_argument("--model")
a = ap.parse_args()

s = load_settings()
model = a.model or s.model
print(f"{len(s.api_keys)} key(s) found; model: {model}; fallbacks: {', '.join(s.models[1:]) or 'none'}")
bad = 0
for i, key in enumerate(s.api_keys, 1):
    client = genai.Client(api_key=key)
    try:
        if a.list and i == 1:
            for m in client.models.list():
                print("  ", m.name)
        r = client.models.generate_content(model=model, contents="Reply with the single word: ok")
        print(f"key #{i} (...{key[-4:]}): OK - {(r.text or '').strip()[:20]!r}")
    except Exception as exc:
        bad += 1
        print(f"key #{i} (...{key[-4:]}): FAILED - {str(exc)[:260]}")
sys.exit(1 if bad == len(s.api_keys) else 0)
