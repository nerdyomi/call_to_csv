"""Checks that the Supabase project is set up as supabase/schema.sql expects. Prints no secrets.

    python scripts/verify_supabase.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
worker_env = dotenv_values(ROOT / ".env")
web_env = dotenv_values(ROOT / "web" / ".env.local")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def call(method: str, url: str, key: str | None, body=None, extra=None):
    headers = {"Content-Type": "application/json", **(extra or {})}
    if key:
        headers.update({"apikey": key, "Authorization": f"Bearer {key}"})
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:  # network problems
        return 0, str(e)


# ---- 1. values present and consistent between the two env files
url_w, url_web = (worker_env.get("SUPABASE_URL") or "").rstrip("/"), (web_env.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
service, anon = worker_env.get("SUPABASE_SERVICE_ROLE_KEY") or "", web_env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or ""
service_web = web_env.get("SUPABASE_SERVICE_ROLE_KEY") or ""
check("root .env has SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", bool(url_w and service))
check("web/.env.local has URL, anon key, service key", bool(url_web and anon and service_web))
from urllib.parse import urlparse
check("URL is the project root (no /rest/v1 or other path)", urlparse(url_w).path in ("", "/") and urlparse(url_w).netloc.endswith(".supabase.co"),
      f"path is {urlparse(url_w).path!r}" if urlparse(url_w).path not in ("", "/") else "")
check("both env files point to the same project", bool(url_w) and url_w == url_web, url_w.replace("https://", "")[:12] + "...")
check("service-role key is the same in both files", bool(service) and service == service_web)
check("anon key differs from service-role key (not swapped)", bool(anon) and anon != service)
check("ALLOWED_EMAILS is set in web/.env.local", bool((web_env.get("ALLOWED_EMAILS") or "").strip()),
      (web_env.get("ALLOWED_EMAILS") or "").strip())
if not (url_w and service and anon):
    print("\nFill in the missing values first.")
    sys.exit(1)

# ---- 2. service role can read the tables the schema creates
tables = ["allowed_users", "farmers", "calls", "call_results", "chat_messages"]
for t in tables:
    st, body = call("GET", f"{url_w}/rest/v1/{t}?select=*&limit=1", service)
    check(f"table public.{t} exists (service role)", st == 200,
          "" if st == 200 else f"HTTP {st}: {str(body)[:140]}")

st, body = call("GET", f"{url_w}/rest/v1/allowed_users?select=email,role", service)
emails = [r["email"] for r in body] if st == 200 and isinstance(body, list) else []
check("allowed_users has at least one email", bool(emails), ", ".join(emails))
check("allowed_users does not still contain the placeholder", "YOUR_LOGIN_EMAIL" not in emails)
env_emails = {e.strip().lower() for e in (web_env.get("ALLOWED_EMAILS") or "").split(",") if e.strip()}
check("ALLOWED_EMAILS matches the database allow-list", env_emails <= {e.lower() for e in emails},
      f"missing in db: {sorted(env_emails - {e.lower() for e in emails})}" if not env_emails <= {e.lower() for e in emails} else "")

# ---- 3. storage bucket
st, body = call("GET", f"{url_w}/storage/v1/bucket/recordings", service)
check("storage bucket 'recordings' exists", st == 200, "" if st == 200 else f"HTTP {st}")
if st == 200:
    check("bucket 'recordings' is private", body.get("public") is False)

# ---- 4. queue functions exist and are callable by the service role only
st, body = call("POST", f"{url_w}/rest/v1/rpc/requeue_stale_calls", service, {"max_minutes": 15})
check("function requeue_stale_calls works (service role)", st == 200, "" if st == 200 else f"HTTP {st}: {str(body)[:140]}")
st, body = call("POST", f"{url_w}/rest/v1/rpc/claim_next_call", service, {})
check("function claim_next_call works (service role)", st == 200, "" if st == 200 else f"HTTP {st}: {str(body)[:140]}")
st, _ = call("POST", f"{url_w}/rest/v1/rpc/claim_next_call", anon, {})
check("anon key cannot call claim_next_call", st in (401, 403, 404), f"HTTP {st}")

# ---- 5. security: the public anon key must see nothing
for t in ["calls", "call_results", "farmers", "chat_messages", "allowed_users"]:
    st, body = call("GET", f"{url_w}/rest/v1/{t}?select=*&limit=1", anon)
    leaked = st == 200 and isinstance(body, list) and len(body) > 0
    check(f"anon key cannot read {t}", not leaked and st in (200, 401, 403), f"HTTP {st}, rows visible: {len(body) if isinstance(body, list) else 0}")
st, _ = call("POST", f"{url_w}/rest/v1/farmers", anon, {"phone": "0000000000"}, {"Prefer": "return=minimal"})
check("anon key cannot write farmers", st in (401, 403), f"HTTP {st}")

# ---- 6. auth: sign-ups closed, your user exists
st, body = call("GET", f"{url_w}/auth/v1/settings", anon)
if st == 200 and isinstance(body, dict):
    check("public sign-ups are disabled", body.get("disable_signup") is True,
          "" if body.get("disable_signup") else "turn OFF 'Allow new users to sign up'")
    check("email login is enabled", body.get("external", {}).get("email") is True)
else:
    check("auth settings readable", False, f"HTTP {st}")
st, body = call("GET", f"{url_w}/auth/v1/admin/users?per_page=50", service)
users = [u.get("email", "").lower() for u in (body.get("users", []) if st == 200 and isinstance(body, dict) else [])]
check("an auth user exists for each allowed email", bool(users) and all(e in users for e in emails), f"users: {len(users)}")

# ---- 7. write test with cleanup (service role): farmer -> call -> unique index -> delete
phone = "8800000000000"
call("DELETE", f"{url_w}/rest/v1/farmers?phone=eq.{phone}", service)
st, _ = call("POST", f"{url_w}/rest/v1/farmers", service, {"phone": phone}, {"Prefer": "return=minimal"})
ok_farmer = st in (200, 201, 204)
check("can insert a farmer", ok_farmer, "" if ok_farmer else f"HTTP {st}")
if ok_farmer:
    row = {"phone": phone, "call_date": "2026-01-01", "call_seq": 1, "file_name": "t.mp3", "storage_path": "verify/t.mp3"}
    st1, _ = call("POST", f"{url_w}/rest/v1/calls", service, row, {"Prefer": "return=minimal"})
    st2, b2 = call("POST", f"{url_w}/rest/v1/calls", service, {**row, "storage_path": "verify/t2.mp3"}, {"Prefer": "return=minimal"})
    check("can insert a call", st1 in (200, 201, 204), "" if st1 in (200, 201, 204) else f"HTTP {st1}")
    check("duplicate phone+date+seq is rejected (unique index)", st2 == 409, f"HTTP {st2}")
    st3, _ = call("PATCH", f"{url_w}/rest/v1/calls?storage_path=eq.verify/t.mp3", service, {"status": "queued"}, {"Prefer": "return=minimal"})
    st4, claimed = call("POST", f"{url_w}/rest/v1/rpc/claim_next_call", service, {})
    got = isinstance(claimed, list) and claimed and claimed[0].get("storage_path") == "verify/t.mp3" and claimed[0].get("status") == "processing"
    check("queue: claim_next_call takes the queued call and marks it processing", bool(got), "" if got else str(claimed)[:140])
    st5, _ = call("PATCH", f"{url_w}/rest/v1/calls?storage_path=eq.verify/t.mp3", service, {"status": "bogus"}, {"Prefer": "return=minimal"})
    check("invalid status value is rejected", st5 in (400, 409), f"HTTP {st5}")
call("DELETE", f"{url_w}/rest/v1/calls?phone=eq.{phone}", service)
call("DELETE", f"{url_w}/rest/v1/farmers?phone=eq.{phone}", service)

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
