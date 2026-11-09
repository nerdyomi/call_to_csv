"""Minimal Supabase client for the worker (REST + Storage, service-role key). No extra dependency: uses httpx."""
from __future__ import annotations

from urllib.parse import quote

import httpx

from .config import Settings


class SupabaseError(RuntimeError):
    pass


class Supa:
    def __init__(self, settings: Settings, timeout: float = 60.0):
        if not settings.supabase_url or not settings.supabase_service_key:
            raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env for the worker.")
        self.base = settings.supabase_url
        key = settings.supabase_service_key
        self.http = httpx.Client(timeout=timeout, headers={"apikey": key, "Authorization": f"Bearer {key}"})

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code >= 400:
            raise SupabaseError(f"{what} failed: HTTP {r.status_code} {r.text[:300]}")
        return r

    # ---- queue ----------------------------------------------------------------------------
    def claim_next(self) -> dict | None:
        r = self._check(self.http.post(f"{self.base}/rest/v1/rpc/claim_next_call", json={}), "claim_next_call")
        rows = r.json()
        return rows[0] if rows else None

    def requeue_stale(self, minutes: int) -> int:
        r = self._check(self.http.post(f"{self.base}/rest/v1/rpc/requeue_stale_calls",
                                       json={"max_minutes": minutes}), "requeue_stale_calls")
        return int(r.json() or 0)

    # ---- data ------------------------------------------------------------------------------
    def update_call(self, call_id: str, patch: dict) -> None:
        self._check(self.http.patch(f"{self.base}/rest/v1/calls?id=eq.{call_id}", json=patch,
                                    headers={"Prefer": "return=minimal"}), "update call")

    def save_result(self, payload: dict) -> None:
        self._check(self.http.post(f"{self.base}/rest/v1/call_results?on_conflict=call_id", json=payload,
                                   headers={"Prefer": "resolution=merge-duplicates,return=minimal"}),
                    "save call_results")

    def download(self, storage_path: str, bucket: str = "recordings") -> bytes:
        url = f"{self.base}/storage/v1/object/{bucket}/{quote(storage_path, safe='/')}"
        return self._check(self.http.get(url), f"download {storage_path}").content
