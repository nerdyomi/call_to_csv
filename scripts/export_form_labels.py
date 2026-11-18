"""Writes web/lib/formLabels.json (question text, section, options per form key) for the website.

    python scripts/export_form_labels.py        # re-run whenever config/schema.yaml points to a new form export
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from call_pipeline.config import PROJECT_ROOT  # noqa: E402
from call_pipeline.schema import load_schema  # noqa: E402

schema = load_schema(PROJECT_ROOT / "config" / "schema.yaml")
out = {}
for i, f in enumerate(schema.fields):
    if f.source in ("audio", "derived") and f.name not in ("Notes", "eng_notes"):
        out[f.name] = {"order": i, "label": f.label or f.description, "section": f.section or "Calculated",
                       "type": f.type, "options": [list(o) for o in f.options]}
target = PROJECT_ROOT / "web" / "lib" / "formLabels.json"
target.write_text(json.dumps({"formVersion": schema.form_version, "fields": out}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"wrote {target.relative_to(PROJECT_ROOT)}: {len(out)} questions, form v{schema.form_version}")
