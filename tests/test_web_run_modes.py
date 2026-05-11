"""/api/run accepts all pipeline modes; /api/abort triggers cancel."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from web.app import app, _run_lock
from src import pipeline


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_run_rejects_unknown_mode(client):
    resp = client.post("/api/run", json={"mode": "teleport", "chapter": 1})
    assert resp.status_code == 400


def test_run_range_requires_range_arg(client):
    resp = client.post("/api/run", json={"mode": "range"})
    assert resp.status_code == 400


def test_run_range_rejects_bad_format(client):
    resp = client.post("/api/run", json={"mode": "range", "range": "not-a-range"})
    assert resp.status_code == 400


def test_run_range_rejects_reversed_range(client):
    resp = client.post("/api/run", json={"mode": "range", "range": "5-3"})
    assert resp.status_code == 400


def test_run_plan_only_requires_chapter(client):
    resp = client.post("/api/run", json={"mode": "plan-only"})
    assert resp.status_code == 400


def test_run_packaging_needs_no_chapter(client):
    """Packaging mode should accept bodies without chapter."""
    with patch("src.pipeline.run_packaging") as mock_pkg:
        mock_pkg.return_value = {"ok": True}
        resp = client.post("/api/run", json={"mode": "packaging"})
    assert resp.status_code in (202, 409)


def test_abort_sets_cancel_event(client):
    pipeline.CANCEL_EVENT.clear()
    resp = client.post("/api/abort")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["aborted"] is True
    assert "was_running" in body
    assert pipeline.CANCEL_EVENT.is_set()
    pipeline.CANCEL_EVENT.clear()


def test_backward_compat_chapter_only_body(client):
    """Old UI posted just {"chapter": N}; still works as mode=chapter."""
    with patch("src.pipeline.run_chapter") as mock:
        mock.return_value = {"chapter": 1}
        resp = client.post("/api/run", json={"chapter": 1})
    assert resp.status_code in (202, 409)


def test_run_rejects_mode_without_chapter_when_required(client):
    for mode in ("plan-only", "write-only", "evaluate-only", "fix-only",
                 "audit-only", "bookkeeping-only"):
        resp = client.post("/api/run", json={"mode": mode})
        assert resp.status_code == 400, f"{mode} should require chapter"


def test_run_dispatches_plan_only(client):
    with patch("src.pipeline.run_plan_only") as mock:
        mock.return_value = {"stage": "plan"}
        resp = client.post("/api/run", json={"mode": "plan-only", "chapter": 2})
    assert resp.status_code in (202, 409)


def test_existing_audit_alias_still_works(client):
    """Preserve /api/audit for backward compat with old frontend."""
    with patch("src.pipeline.run_audit_only") as mock:
        mock.return_value = {"chapter": 1}
        resp = client.post("/api/audit", json={"chapter": 1})
    assert resp.status_code in (202, 409)
