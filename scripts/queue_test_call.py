"""Puts one local recording into Supabase exactly as the website will (farmer + call row + storage file),
queued for the worker. Then verify the outcome with --check.

    python scripts/queue_test_call.py input/recordings/01762709049.mp3 [--date 2026-11-01]
    python -m call_pipeline worker --once
    python scripts/queue_test_call.py --check <call id>
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
env = dotenv_values(ROOT / ".env")
URL, KEY = env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_SERVICE_ROLE_KEY"]


def req(method, path, body=None, headers=None, raw=None):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", **(headers or {})}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if body is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(URL + path, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            t = resp.read().decode()
            return resp.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        return e.code, t


ap = argparse.ArgumentParser()
ap.add_argument("file", nargs="?")
ap.add_argument("--date", help="YYYY-MM-DD; omit for 'none'")
ap.add_argument("--check")
a = ap.parse_args()

if a.check:
    st, calls = req("GET", f"/rest/v1/calls?id=eq.{a.check}&select=*")
    c = calls[0]
    print({k: c[k] for k in ("status", "attempts", "model", "duration_seconds", "error", "queued_at", "started_at", "finished_at")})
    st, res = req("GET", f"/rest/v1/call_results?call_id=eq.{a.check}&select=*")
    if not res:
        print("no result row yet")
        sys.exit(1)
    r = res[0]
    print("fields:", len(r["fields"]), "| evidence:", len(r["evidence"]), "| review items:", len(r["review"]),
          "| transcript turns:", len(r["transcript"]), "| usage:", r["usage"])
    print("sample fields:", {k: r["fields"][k] for k in list(r["fields"])[:6]})
    print("transcript head:\n" + "\n".join(r["transcript_text"].splitlines()[:4]))
    print("notes:", (r["notes"] or "")[:160])
    sys.exit(0 if c["status"] == "done" else 1)

f = Path(a.file)
m = re.search(r"(0?1\d{9})", f.stem)
phone = "88" + (m.group(1) if m.group(1).startswith("0") else "0" + m.group(1))
date = a.date
# next free sequence number for this phone + date
q = f"/rest/v1/calls?phone=eq.{phone}&select=call_seq,call_date"
st, existing = req("GET", q)
seq = 1 + max([c["call_seq"] for c in existing if c["call_date"] == date] or [0])
folder = f"{phone}/{date or 'none'}-{seq}"
storage_path = f"{folder}/{f.name}"
print("phone:", phone, "| date:", date or "none", "| seq:", seq, "| storage:", storage_path)

st, _ = req("POST", "/rest/v1/farmers", {"phone": phone}, {"Prefer": "resolution=ignore-duplicates,return=minimal"})
assert st in (200, 201, 204), f"farmer: {st} {_}"
mime = "audio/mpeg" if f.suffix.lower() in (".mp3", ".mpeg") else "application/octet-stream"
st, out = req("POST", "/storage/v1/object/recordings/" + urllib.parse.quote(storage_path), raw=f.read_bytes(),
              headers={"Content-Type": mime, "x-upsert": "true"})
assert st in (200, 201), f"upload: {st} {out}"
now = datetime.now(timezone.utc).isoformat()
st, rows = req("POST", "/rest/v1/calls", {"phone": phone, "call_date": date, "call_seq": seq, "file_name": f.name,
                                           "storage_path": storage_path, "file_size": f.stat().st_size,
                                           "status": "queued", "queued_at": now},
               {"Prefer": "return=representation"})
assert st in (200, 201), f"call: {st} {rows}"
print("queued. call id:", rows[0]["id"])
