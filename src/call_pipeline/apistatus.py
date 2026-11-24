"""Publishes what is really happening with each API key and model, for the website's "API status" page.

Nothing here calls the AI: it only records the outcome of the calls the worker makes anyway, so it costs no
quota. Per (key, model) it keeps the last result (working / busy / quota used up / key rejected / model not
available), when it was last seen, and how many requests and tokens were served today. The "day" is the Pacific
time day, because that is when Google resets daily quotas. Counts only cover calls made through this worker.

The key itself is never sent anywhere: only its last 4 characters and the .env variable name.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PROVIDER = "gemini"
KINDS = {"ok", "busy", "quota", "key_rejected", "unavailable", "error"}


def quota_day(now: datetime | None = None) -> str:
    """Date (Pacific time) that Gemini's daily quota is counted in."""
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # no tz database on this machine: fixed UTC-8 is off by one hour in summer, which is fine here
        return (now - timedelta(hours=8)).date().isoformat()


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat()


def model_rows(pricing_path: Path, chain: list[str]) -> list[dict]:
    """One row per model from pricing.yaml (prices, free-tier facts) plus any model the worker uses."""
    try:
        cfg = yaml.safe_load(Path(pricing_path).read_text(encoding="utf-8")) or {}
    except Exception:
        log.warning("could not read %s for the API status page", pricing_path)
        cfg = {}
    prices, free = cfg.get("models") or {}, cfg.get("free_tier") or {}
    rows = []
    for name in dict.fromkeys([*chain, *prices.keys(), *free.keys()]):
        p, f = prices.get(name) or {}, free.get(name) or {}
        rows.append({
            "provider": PROVIDER, "model": name,
            "input_per_m": p.get("text_input"), "audio_per_m": p.get("audio_input"), "output_per_m": p.get("output"),
            "free_available": f.get("available"), "free_rpd": f.get("rpd"), "free_rpm": f.get("rpm"), "free_tpm": f.get("tpm"),
            "note": f.get("note"), "in_chain": name in chain,
        })
    return rows


class StatusReporter:
    """Thread-safe. `event()` is called from the extraction threads; a background thread uploads changes."""

    def __init__(self, db, settings, flush_seconds: float = 5.0):
        self.db = db
        self.flush_seconds = flush_seconds
        self._model_rows = model_rows(settings.pricing_path, list(settings.models))
        self.models = [r["model"] for r in self._model_rows]
        names = list(settings.api_key_names) + [f"GEMINI_API_KEY_{i + 1}" for i in range(len(settings.api_key_names), len(settings.api_keys))]
        self.slots = [(i + 1, names[i], settings.api_keys[i][-4:]) for i in range(len(settings.api_keys))]
        self._rows: dict[tuple[int, str], dict] = {}
        self._dirty: set[tuple[int, str]] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._checker: threading.Thread | None = None
        self._api_keys = tuple(settings.api_keys)
        self._probe_clients: dict[int, object] = {}
        self._warned_checks = False
        for slot, env, tail in self.slots:
            for model in self.models:
                self._rows[(slot, model)] = {
                    "provider": PROVIDER, "slot": slot, "model": model, "env_name": env, "key_tail": tail,
                    "status": "unknown", "detail": None, "last_ok_at": None, "last_fail_at": None, "last_seen_at": None,
                    "day": quota_day(), "requests_today": 0, "tokens_today": 0,
                }

    # ---- lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        """Publish the key/model list, restore today's counters, and start the uploader. Never raises."""
        try:
            self.db.upsert("api_models", self._model_rows, "provider,model")
            self.db.delete("api_key_status", f"provider=eq.{PROVIDER}&slot=gt.{len(self.slots)}")  # keys removed from .env
            self._restore()
            with self._lock:
                self._dirty.update(self._rows)
            self.flush()
        except Exception as exc:
            log.warning("API status page: could not publish (%s). Run supabase/migrations/003_api_status.sql if you have not.", str(exc)[:160])
        self._thread = threading.Thread(target=self._loop, name="api-status", daemon=True)
        self._thread.start()
        try:   # old "Check now" requests are of no use any more
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.db.delete("api_check_requests", f"created_at=lt.{cutoff}")
        except Exception:
            log.debug("api_check_requests not available yet", exc_info=True)
        self._checker = threading.Thread(target=self._check_loop, name="api-checks", daemon=True)
        self._checker.start()

    def stop(self) -> None:
        self._stop.set()
        self.flush()

    def _loop(self) -> None:
        while not self._stop.wait(self.flush_seconds):
            self.flush()

    def _restore(self) -> None:
        """Keep today's counters and last results across worker restarts (only for the same key)."""
        today = quota_day()
        for old in self.db.select("api_key_status", f"provider=eq.{PROVIDER}&select=*"):
            row = self._rows.get((old.get("slot"), old.get("model")))
            if not row or old.get("key_tail") != row["key_tail"]:
                continue  # a different key now sits in this slot: start fresh
            for k in ("status", "detail", "last_ok_at", "last_fail_at", "last_seen_at"):
                row[k] = old.get(k)
            if old.get("day") == today:
                row["requests_today"] = old.get("requests_today") or 0
                row["tokens_today"] = old.get("tokens_today") or 0

    # ---- "Check now" -------------------------------------------------------------------------
    def probe(self, slot: int, model: str) -> tuple[str, str]:
        """One tiny real request to this key + model. Counts as one request of the daily quota.
        Records the outcome like any other call and returns (status, detail)."""
        from google import genai
        from google.genai import types
        from .gemini_client import classify

        if not 1 <= slot <= len(self._api_keys):
            return "error", f"there is no api{slot} in .env"
        try:
            client = self._probe_clients.get(slot)
            if client is None:   # its own client with a short timeout: a hung check must not hang for 20 minutes
                client = self._probe_clients[slot] = genai.Client(
                    api_key=self._api_keys[slot - 1], http_options=types.HttpOptions(timeout=30_000))
            resp = client.models.generate_content(
                model=model, contents="Reply with the single word: ok",
                config=types.GenerateContentConfig(max_output_tokens=16, temperature=0))
            tokens = getattr(getattr(resp, "usage_metadata", None), "total_token_count", 0) or 0
            self.event(slot - 1, model, "ok", tokens=int(tokens))
            return "ok", ""
        except Exception as exc:
            kind, _ = classify(exc, 0)
            status = {"retry": "busy", "quota": "quota", "key": "key_rejected", "model": "unavailable"}.get(kind, "error")
            detail = str(exc)[:160].strip()
            self.event(slot - 1, "*" if status == "key_rejected" else model, status, detail)
            return status, detail

    def _check_loop(self) -> None:
        while not self._stop.wait(3.0):
            try:
                self._run_checks()
            except Exception as exc:
                if not self._warned_checks:
                    self._warned_checks = True
                    log.warning("API 'Check now' is not working (run supabase/migrations/005_api_checks.sql?): %s", str(exc)[:160])

    def _run_checks(self) -> None:
        for req in self.db.select("api_check_requests", f"provider=eq.{PROVIDER}&status=eq.pending&order=created_at&limit=10"):
            if not self.db.patch("api_check_requests", f"id=eq.{req['id']}&status=eq.pending", {"status": "running"}):
                continue   # another worker took it
            status, detail = self.probe(int(req["slot"]), req["model"])
            self.flush()   # publish the new key status before the request is marked done
            self.db.patch("api_check_requests", f"id=eq.{req['id']}",
                          {"status": "done", "result": status, "detail": detail or None,
                           "finished_at": datetime.now(timezone.utc).isoformat()})
            log.info("API check: api%s %s -> %s", req["slot"], req["model"], status)

    # ---- events ------------------------------------------------------------------------------
    def event(self, k: int, model: str, kind: str, detail: str = "", tokens: int = 0) -> None:
        """k = index of the key (0-based, same order as settings.api_keys). model "*" = every model of that key."""
        if kind not in KINDS:
            kind = "error"
        now, today = datetime.now(timezone.utc), quota_day()
        slot = next((s for s in self.slots if s[0] == k + 1), None)
        if slot is None:
            return
        with self._lock:
            targets = [key for key in self._rows if key[0] == slot[0] and (model == "*" or key[1] == model)]
            if not targets and model != "*":  # a model that is not in the known list
                self._rows[(slot[0], model)] = {
                    "provider": PROVIDER, "slot": slot[0], "model": model, "env_name": slot[1], "key_tail": slot[2],
                    "status": "unknown", "detail": None, "last_ok_at": None, "last_fail_at": None, "last_seen_at": None,
                    "day": today, "requests_today": 0, "tokens_today": 0,
                }
                targets = [(slot[0], model)]
            for key in targets:
                row = self._rows[key]
                if row["day"] != today:
                    row["day"], row["requests_today"], row["tokens_today"] = today, 0, 0
                row["status"], row["detail"] = kind, (detail or None) if kind != "ok" else None
                row["last_seen_at"] = _iso(now)
                if kind == "ok":
                    row["last_ok_at"] = _iso(now)
                    row["requests_today"] += 1
                    row["tokens_today"] += int(tokens or 0)
                else:
                    row["last_fail_at"] = _iso(now)
                self._dirty.add(key)

    def flush(self) -> None:
        with self._lock:
            keys, self._dirty = list(self._dirty), set()
            rows = [dict(self._rows[k]) for k in keys]
        if not rows:
            return
        try:
            self.db.upsert("api_key_status", rows, "provider,slot,model")
        except Exception as exc:
            with self._lock:
                self._dirty.update(keys)  # try again next time
            log.debug("API status upload failed: %s", exc)
