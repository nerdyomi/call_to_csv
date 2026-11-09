"""Background worker: takes queued calls from Supabase, analyses the audio with Gemini, stores the result.

    python -m call_pipeline worker            # keep running (Ctrl+C to stop)
    python -m call_pipeline worker --once     # process everything queued, then exit

Flow per call:  claim (status queued -> processing) -> download audio -> Gemini -> normalise ->
save call_results -> status done.  Any error -> status failed + the reason in calls.error.
When every Gemini key/model is out of quota the call goes back to 'queued' and the worker waits.
"""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import audio
from .config import Settings
from .gemini_client import QuotaExhausted
from .normalize import build_row
from .prompting import USER_INSTRUCTION
from .schema import Schema
from .writer import format_transcript

log = logging.getLogger(__name__)

NOT_A_FIELD = ("Notes", "eng_notes")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Worker:
    def __init__(self, db, extractor_factory: Callable[[], object], schema: Schema, settings: Settings):
        """`db`: a Supa-like object. `extractor_factory`: builds a GeminiExtractor (rebuilt after a quota pause)."""
        self.db, self.schema, self.s = db, schema, settings
        self._factory = extractor_factory
        self._extractor = None
        self._lock = threading.Lock()
        self._pause_until = 0.0
        self._stop = threading.Event()

    # ---- one call -------------------------------------------------------------------------------
    def _get_extractor(self):
        with self._lock:
            if self._extractor is None:
                self._extractor = self._factory()
            return self._extractor

    def process(self, call: dict) -> str:
        """Runs one claimed call. Returns 'done', 'failed' or 'requeued'."""
        cid, name = call["id"], call["file_name"]
        try:
            data = self.db.download(call["storage_path"])
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / (Path(name).name or "call.mp3")
                path.write_bytes(data)
                rec = audio.Recording(path)
                duration = audio.duration_seconds(path)
                res = self._get_extractor().extract(rec, USER_INSTRUCTION)
        except QuotaExhausted as exc:
            # not the call's fault: keep it in the queue and wait for the quota to come back
            self.db.update_call(cid, {"status": "queued", "queued_at": _now(), "error": str(exc)[:500]})
            with self._lock:
                self._pause_until = time.monotonic() + self.s.quota_pause_minutes * 60
                self._extractor = None   # fresh key/model bookkeeping after the pause
            log.warning("%s: all Gemini keys/models are out of quota; call re-queued, pausing %.0f min",
                        name, self.s.quota_pause_minutes)
            return "requeued"
        except Exception as exc:
            log.error("%s: FAILED: %s", name, str(exc)[:300])
            self._mark_failed(cid, exc)
            return "failed"

        try:
            row = build_row(res.data, self.schema)
            self.db.save_result({
                "call_id": cid,
                "transcript": row.transcript,
                "transcript_text": format_transcript(row.transcript),
                "fields": {k: v for k, v in row.values.items() if k not in NOT_A_FIELD},
                "evidence": row.evidence,
                "review": [{"field": i.field, "kind": i.kind, "detail": i.detail} for i in row.issues],
                "notes": row.values.get("Notes", ""),
                "eng_notes": row.values.get("eng_notes", ""),
                "assessment": res.data.get("call_assessment"),
                "usage": {**res.usage, "key": res.key_tail},
                "raw": res.data,
                "model": res.model,
                "updated_at": _now(),
            })
            patch = {"status": "done", "finished_at": _now(), "model": res.model, "error": None}
            if duration:
                patch["duration_seconds"] = round(duration, 1)
            self.db.update_call(cid, patch)
        except Exception as exc:   # saving failed after a paid Gemini call: say so clearly
            log.error("%s: analysis ok but saving failed: %s", name, str(exc)[:300])
            self._mark_failed(cid, RuntimeError(f"analysis finished but saving failed: {exc}"))
            return "failed"
        log.info("%s: done (%s, key ...%s, %d fields, %d transcript turns)", name, res.model, res.key_tail,
                 len(row.evidence), len(row.transcript))
        return "done"

    def _mark_failed(self, call_id: str, exc: Exception) -> None:
        try:
            self.db.update_call(call_id, {"status": "failed", "finished_at": _now(), "error": str(exc)[:1000]})
        except Exception:
            log.exception("could not record the failure for call %s", call_id)

    # ---- loops ----------------------------------------------------------------------------------
    def _loop(self, once: bool) -> None:
        while not self._stop.is_set():
            if time.monotonic() < self._pause_until:
                if once:
                    return
                self._stop.wait(1)
                continue
            try:
                call = self.db.claim_next()
            except Exception as exc:
                log.error("cannot reach Supabase: %s", str(exc)[:200])
                if once:
                    raise
                self._stop.wait(self.s.poll_seconds * 3)
                continue
            if call is None:
                if once:
                    return
                self._stop.wait(self.s.poll_seconds)
                continue
            log.info("picked up %s (attempt %s)", call["file_name"], call.get("attempts"))
            self.process(call)

    def run(self, once: bool = False) -> None:
        try:
            n = self.db.requeue_stale(self.s.stale_minutes)
            if n:
                log.warning("%d call(s) stuck in 'processing' were put back in the queue", n)
        except Exception as exc:
            log.error("could not requeue stale calls: %s", str(exc)[:200])
        threads = [threading.Thread(target=self._loop, args=(once,), daemon=True, name=f"worker-{i}")
                   for i in range(max(self.s.workers, 1))]
        for t in threads:
            t.start()
        try:
            last_stale = time.monotonic()
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(timeout=1)
                if not once and time.monotonic() - last_stale > 300:
                    last_stale = time.monotonic()
                    try:
                        self.db.requeue_stale(self.s.stale_minutes)
                    except Exception as exc:
                        log.error("could not requeue stale calls: %s", str(exc)[:200])
        except KeyboardInterrupt:
            log.info("stopping: finishing the calls in progress (Ctrl+C again to force)")
            self._stop.set()
            for t in threads:
                t.join()
