"""The API status reporter: what the website's API status page is built from."""
from dataclasses import replace
from datetime import datetime, timezone

from call_pipeline import audio
from call_pipeline.apistatus import StatusReporter, model_rows, quota_day
from call_pipeline.config import load_settings
from call_pipeline.gemini_client import GeminiExtractor


class FakeDb:
    def __init__(self, existing=None):
        self.tables = {"api_key_status": list(existing or [])}
        self.upserts, self.deleted = [], []

    def select(self, table, query):
        return list(self.tables.get(table, []))

    def upsert(self, table, rows, on_conflict):
        self.upserts.append((table, rows))
        if table == "api_key_status":
            by = {(r["slot"], r["model"]): r for r in self.tables["api_key_status"]}
            for r in rows:
                by[(r["slot"], r["model"])] = dict(r)
            self.tables["api_key_status"] = list(by.values())

    def delete(self, table, query):
        self.deleted.append((table, query))

    def patch(self, table, query, body):
        self.patched = getattr(self, "patched", []) + [(table, query, body)]
        return [body]


def _settings(n_keys=2):
    return replace(load_settings(require_key=False), model="m1", fallback_models=("m2",),
                   api_keys=tuple(f"secret-key-{i}" for i in range(n_keys)),
                   api_key_names=tuple(f"GEMINI_API_KEY_{i + 1}" for i in range(n_keys)))


def _rows(db):
    return {(r["slot"], r["model"]): r for r in db.tables["api_key_status"]}


def test_start_publishes_every_key_and_model_without_secrets():
    db = FakeDb()
    rep = StatusReporter(db, _settings())
    rep.start()
    rep.stop()
    rows = _rows(db)
    assert {k for k in rows if k[1] in ("m1", "m2")} == {(1, "m1"), (1, "m2"), (2, "m1"), (2, "m2")}
    assert rows[(1, "m1")]["status"] == "unknown" and rows[(1, "m1")]["key_tail"] == "ey-0"
    assert "secret-key" not in str(db.upserts)
    assert ("api_key_status", "provider=eq.gemini&slot=gt.2") in db.deleted   # keys removed from .env disappear


def test_ok_counts_requests_and_tokens_and_a_failure_sets_the_status():
    db = FakeDb()
    rep = StatusReporter(db, _settings())
    rep.start()
    rep.event(0, "m1", "ok", tokens=1000)
    rep.event(0, "m1", "ok", tokens=500)
    rep.event(1, "m1", "busy", "503 overloaded")
    rep.flush()
    rows = _rows(db)
    assert (rows[(1, "m1")]["status"], rows[(1, "m1")]["requests_today"], rows[(1, "m1")]["tokens_today"]) == ("ok", 2, 1500)
    assert rows[(2, "m1")]["status"] == "busy" and "overloaded" in rows[(2, "m1")]["detail"]
    assert rows[(2, "m1")]["requests_today"] == 0 and rows[(1, "m2")]["status"] == "unknown"


def test_rejected_key_marks_all_its_models():
    db = FakeDb()
    rep = StatusReporter(db, _settings())
    rep.start()
    rep.event(0, "*", "key_rejected", "403")
    rep.flush()
    rows = _rows(db)
    assert rows[(1, "m1")]["status"] == rows[(1, "m2")]["status"] == "key_rejected"
    assert rows[(2, "m1")]["status"] == "unknown"


def test_counters_survive_a_restart_but_not_a_changed_key_or_a_new_day():
    today = quota_day()
    old = [
        {"provider": "gemini", "slot": 1, "model": "m1", "key_tail": "ey-0", "status": "ok", "detail": None,
         "last_ok_at": "2026-01-01T00:00:00+00:00", "last_fail_at": None, "last_seen_at": None, "day": today,
         "requests_today": 7, "tokens_today": 70000},
        {"provider": "gemini", "slot": 2, "model": "m1", "key_tail": "OLD1", "status": "ok", "detail": None,
         "last_ok_at": None, "last_fail_at": None, "last_seen_at": None, "day": today, "requests_today": 9, "tokens_today": 9},
        {"provider": "gemini", "slot": 1, "model": "m2", "key_tail": "ey-0", "status": "quota", "detail": "x",
         "last_ok_at": None, "last_fail_at": None, "last_seen_at": None, "day": "2000-01-01", "requests_today": 20, "tokens_today": 5},
    ]
    db = FakeDb(old)
    rep = StatusReporter(db, _settings())
    rep.start()
    rep.stop()
    rows = _rows(db)
    assert rows[(1, "m1")]["requests_today"] == 7 and rows[(1, "m1")]["tokens_today"] == 70000
    assert rows[(2, "m1")]["requests_today"] == 0                       # another key in that slot now
    assert rows[(1, "m2")]["requests_today"] == 0 and rows[(1, "m2")]["status"] == "quota"   # new day: counters reset


def test_quota_day_follows_pacific_time():
    assert quota_day(datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)) == "2026-11-23"   # still evening in California
    assert quota_day(datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)) == "2026-11-24"


def test_model_rows_come_from_pricing_yaml():
    s = load_settings(require_key=False)
    rows = {r["model"]: r for r in model_rows(s.pricing_path, ["gemini-3.8-flash"])}
    assert rows["gemini-3.8-flash"]["in_chain"] and rows["gemini-3.8-flash"]["output_per_m"] == 3.75
    assert rows["gemini-3.8-flash"]["free_rpd"] == 20 and not rows["gemini-2.5-pro"]["in_chain"]


# ---- the extractor reports what happens ----

class _Resp:
    usage_metadata = None
    text = '{"fields": [], "call_assessment": {}, "notes": "", "eng_notes": "", "warnings": []}'


def _client(fail):
    class Models:
        def generate_content(self, model, contents, config):
            err = fail(model)
            if err:
                raise err
            return _Resp()

    class C:
        models = Models()
    return C()


def test_extractor_emits_busy_then_ok(tmp_path):
    from google.genai import errors
    events = []
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    s = replace(load_settings(require_key=False), requests_per_minute=60000, retry_base_seconds=0, max_retries=0,
                api_keys=("k0", "k1"), model="m1", fallback_models=())
    busy = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    ex = GeminiExtractor(s, "sys", {"type": "object"}, clients=[_client(lambda m: busy), _client(lambda m: None)],
                         on_event=lambda *a: events.append(a))
    ex.extract(audio.Recording(f), "go")
    assert [(e[0], e[2]) for e in events] == [(0, "busy"), (1, "ok")]
    assert "overloaded" in events[0][3]


def test_a_failing_status_callback_never_breaks_extraction(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    s = replace(load_settings(require_key=False), requests_per_minute=60000, api_keys=("k0",), model="m1", fallback_models=())

    def boom(*a):
        raise RuntimeError("status page down")
    ex = GeminiExtractor(s, "sys", {"type": "object"}, clients=[_client(lambda m: None)], on_event=boom)
    assert ex.extract(audio.Recording(f), "go").model == "m1"


# ---- a model picked on the website is used on its own ----

def test_chosen_model_is_used_alone_and_failure_says_so(tmp_path):
    import pytest
    from google.genai import errors
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    s = replace(load_settings(require_key=False), requests_per_minute=60000, retry_base_seconds=0, max_retries=0,
                api_keys=("k0",), model="m1", fallback_models=("m2",))
    seen = []

    def behave(m):
        seen.append(m)
        return None

    ex = GeminiExtractor(s, "sys", {"type": "object"}, clients=[_client(behave)])
    assert ex.extract(audio.Recording(f), "go", models=["m2"]).model == "m2"
    assert seen == ["m2"]                                    # m1 was never tried

    busy = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    ex = GeminiExtractor(s, "sys", {"type": "object"}, clients=[_client(lambda m: busy if m == "m2" else None)])
    with pytest.raises(RuntimeError, match="chosen model .*m2.* Try Auto"):
        ex.extract(audio.Recording(f), "go", models=["m2"])   # does not quietly use m1 instead


# ---- "Check now" ----

def test_probe_records_the_outcome_and_never_raises(monkeypatch):
    from google.genai import errors
    db = FakeDb()
    rep = StatusReporter(db, _settings())
    rep.start()

    class Models:
        def __init__(self, err): self.err = err
        def generate_content(self, **kw):
            if self.err:
                raise self.err
            return _Resp()

    class C:
        def __init__(self, err): self.models = Models(err)

    rep._probe_clients[1] = C(None)
    rep._probe_clients[2] = C(errors.ClientError(403, {"error": {"code": 403, "message": "key blocked", "status": "X"}}))
    assert rep.probe(1, "m1") == ("ok", "")
    status, detail = rep.probe(2, "m1")
    assert status == "key_rejected" and "blocked" in detail
    assert rep.probe(9, "m1")[0] == "error"                       # a key that is not in .env
    rep.flush()
    rows = _rows(db)
    assert rows[(1, "m1")]["status"] == "ok" and rows[(1, "m1")]["requests_today"] == 1
    assert rows[(2, "m1")]["status"] == rows[(2, "m2")]["status"] == "key_rejected"
    rep.stop()


def test_pending_check_requests_are_run_once_and_marked_done():
    db = FakeDb()
    db.tables["api_check_requests"] = [{"id": "r1", "slot": 1, "model": "m1", "status": "pending", "created_at": "x"}]
    db.select_orig = db.select
    db.select = lambda table, query: db.tables.get(table, []) if table == "api_check_requests" else db.select_orig(table, query)
    rep = StatusReporter(db, _settings())
    rep.probe = lambda slot, model: ("busy", "503 overloaded")
    rep._run_checks()
    done = [p for p in db.patched if p[2].get("status") == "done"]
    assert len(done) == 1 and done[0][2]["result"] == "busy" and done[0][2]["detail"] == "503 overloaded"


def test_extractor_reports_trying_and_busy_for_the_progress_bar(tmp_path):
    from google.genai import errors
    seen = []
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    s = replace(load_settings(require_key=False), requests_per_minute=60000, retry_base_seconds=0, max_retries=1,
                api_keys=("k0", "k1"), model="m1", fallback_models=())
    busy = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    ex = GeminiExtractor(s, "sys", {"type": "object"}, clients=[_client(lambda m: busy), _client(lambda m: None)])
    ex.extract(audio.Recording(f), "go", on_status=lambda *a: seen.append(a))
    assert seen == [("trying", 1, "m1", 1), ("busy", 1, "m1", 1), ("trying", 1, "m1", 2), ("busy", 1, "m1", 2),
                    ("trying", 2, "m1", 1)]
