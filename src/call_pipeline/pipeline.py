"""Orchestration: recordings -> (cached) Gemini JSON -> normalized rows -> CSVs."""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import audio
from .config import Settings
from .gemini_client import GeminiExtractor
from .manifest import load_manifest
from .normalize import CallRow, build_row
from .prompting import USER_INSTRUCTION, build_response_schema, build_system_prompt
from .schema import Schema, load_schema
from .writer import write_outputs

log = logging.getLogger(__name__)
_log_lock = threading.Lock()


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock, path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_one(rec: audio.Recording, extractor: GeminiExtractor, settings: Settings) -> bool:
    """Call Gemini for one recording and cache the raw JSON. Returns True on success."""
    try:
        res = extractor.extract(rec, USER_INSTRUCTION)
    except Exception as exc:
        log.error("%s: FAILED: %s", rec.name, str(exc)[:300])
        _append_jsonl(settings.error_log, {"at": _now(), "recording": rec.name, "error": str(exc)[:2000]})
        return False
    payload = {"recording": rec.name, "source_path": str(rec.path), "model": res.model, "api_key_tail": res.key_tail, "extracted_at": _now(),
               "usage": res.usage, "response": res.data}
    settings.call_dir(rec.stem).mkdir(parents=True, exist_ok=True)
    tmp = settings.call_dir(rec.stem) / "raw.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings.raw_file(rec.stem))
    _append_jsonl(settings.usage_log, {"at": _now(), "recording": rec.name, "model": res.model, "key": res.key_tail, **res.usage})
    log.info("%s: ok (%s)", rec.name, res.usage)
    return True


def run(settings: Settings, force: bool = False, limit: int | None = None,
        only: list[str] | None = None, extractor: GeminiExtractor | None = None,
        files: list[Path] | None = None) -> dict:
    """`files`: process exactly these audio files (from anywhere) instead of scanning the input folder."""
    schema = load_schema(settings.schema_path)
    if files:
        missing = [str(f) for f in files if not Path(f).is_file()]
        if missing:
            raise SystemExit(f"File not found: {', '.join(missing)}")
        recs = [audio.Recording(Path(f).resolve()) for f in files]
    else:
        recs = audio.discover(settings.input_dir, settings.audio_extensions)
    if only:
        recs = [r for r in recs if any(o in r.name for o in only)]
    todo = [r for r in recs if force or not settings.raw_file(r.stem).exists()]
    skipped = len(recs) - len(todo)
    if limit is not None:
        todo = todo[:limit]
    log.info("%d recordings found, %d already done, %d to process", len(recs), skipped, len(todo))

    ok = failed = 0
    if todo:
        extractor = extractor or GeminiExtractor(
            settings, build_system_prompt(settings, schema),
            build_response_schema(schema, settings.include_transcript))
        with ThreadPoolExecutor(max_workers=max(settings.workers, 1)) as pool:
            futures = [pool.submit(extract_one, r, extractor, settings) for r in todo]
            for fut in as_completed(futures):
                ok, failed = (ok + 1, failed) if fut.result() else (ok, failed + 1)

    rows = rebuild(settings, schema)
    return {"found": len(recs), "skipped": skipped, "ok": ok, "failed": failed, "rows": rows}


def rebuild(settings: Settings, schema: Schema | None = None) -> int:
    """Regenerate all CSVs from the cached output/<recording>/raw.json files. No API calls.

    Works from the output folders, so moving or deleting audio files never removes a call
    from the combined CSVs.
    """
    schema = schema or load_schema(settings.schema_path)
    manifest = load_manifest(settings.manifest)
    manifest_cols = {f.name for f in schema.fields if f.source == "manifest"}

    results: dict[str, tuple[CallRow, dict[str, str]]] = {}
    for raw_file in sorted(settings.output_dir.glob("*/raw.json")):
        payload = json.loads(raw_file.read_text(encoding="utf-8"))
        stem, name = raw_file.parent.name, payload.get("recording", raw_file.parent.name)
        candidates = [Path(payload["source_path"])] if payload.get("source_path") else []
        audio_path = next((c for c in candidates + [settings.input_dir / name] if c.exists()), None)
        duration = audio.duration_seconds(audio_path) if audio_path else None
        base = audio.metadata_from_filename(name, settings.filename_regex, settings.timezone_offset,
                                            settings.phone_country_prefix, duration)
        base.update({k: v for k, v in manifest.get(stem, {}).items() if k in manifest_cols})
        results[stem] = (build_row(payload["response"], schema), base)

    write_outputs(settings.output_dir, results, schema, settings.csv_encoding,
                  settings.main_csv, settings.evidence_csv, settings.review_csv, settings.transcript_csv)
    return len(results)
