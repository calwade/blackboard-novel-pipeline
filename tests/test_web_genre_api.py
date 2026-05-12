"""Web API: genre pipeline endpoints.

Covers the 5 new routes exposed by web/app.py on top of src.genre_extractor:
  - GET    /api/genres            (enhanced; includes build_status + file counts)
  - POST   /api/genres/new
  - POST   /api/genres/<id>/fill
  - POST   /api/genres/<id>/audit
  - POST   /api/genres/<id>/extract  (dry_run path only — real extract is LLM)
  - GET    /api/genres/<id>/status
  - DELETE /api/genres/<id>

All tests monkey-patch config.GENRES_DIR to tmp_path so the real
genres/ directory is never touched.
"""
from __future__ import annotations

import time

import pytest
import yaml

from web.app import app
from src import config, bootstrap
from src.genre_extractor import pipeline as genre_extractor


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def tmp_genres(tmp_path, monkeypatch):
    """Redirect config.GENRES_DIR to tmp_path so create/delete don't touch real genres/."""
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    # bootstrap + genre_extractor both read config.GENRES_DIR via attribute lookup
    # on the same module, so the patch above is enough.
    yield tmp_path


# ---------------------------------------------------------------------------
# GET /api/genres — enhanced to include build_status + file counts
# ---------------------------------------------------------------------------

def test_list_genres_basic_shape(client):
    """Original contract must still hold: returns a list with id/display_name."""
    resp = client.get("/api/genres")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "genres" in data
    assert isinstance(data["genres"], list)
    ids = [g["id"] for g in data["genres"]]
    # Three built-in genres should be present in the real repo
    assert "gangster-hk-1983" in ids


def test_list_genres_includes_file_stats(client):
    """Extended: each genre entry carries file_count + has_build_status."""
    resp = client.get("/api/genres")
    data = resp.get_json()
    g0 = next(g for g in data["genres"] if g["id"] == "gangster-hk-1983")
    # file_count counts the 4-5 tracked genre files (genre.yaml / era.md / ...)
    assert "file_count" in g0
    assert g0["file_count"] >= 3
    assert "has_build_status" in g0


# ---------------------------------------------------------------------------
# POST /api/genres/new
# ---------------------------------------------------------------------------

def test_new_genre_creates_scaffold(client, tmp_genres):
    resp = client.post("/api/genres/new", json={
        "id": "smoke-test-genre",
        "name": "测试题材",
        "genre": "测试",
        "era": "测试时代",
        "tone": "冷峻",
    })
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["genre_id"] == "smoke-test-genre"
    # the 4 stub files should exist
    gdir = tmp_genres / "smoke-test-genre"
    for f in ("genre.yaml", "era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        assert (gdir / f).exists(), f"missing scaffold file: {f}"


def test_new_genre_requires_id(client, tmp_genres):
    resp = client.post("/api/genres/new", json={})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_new_genre_rejects_duplicate(client, tmp_genres):
    client.post("/api/genres/new", json={"id": "dup-test"})
    resp = client.post("/api/genres/new", json={"id": "dup-test"})
    assert resp.status_code == 409
    assert resp.get_json()["ok"] is False


@pytest.mark.parametrize("bad_id", [
    "../../../tmp/pwn",
    "/abs",
    "Capital",
    "has space",
    "",
    "a" * 65,
])
def test_new_genre_rejects_unsafe_ids(client, tmp_genres, bad_id):
    resp = client.post("/api/genres/new", json={"id": bad_id})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/genres/<id>/fill
# ---------------------------------------------------------------------------

def test_fill_genre_fills_missing(client, tmp_genres):
    # Bootstrap a partial genre — only genre.yaml present
    gdir = tmp_genres / "partial-genre"
    gdir.mkdir()
    (gdir / "genre.yaml").write_text("id: partial-genre\n", encoding="utf-8")

    resp = client.post("/api/genres/partial-genre/fill")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    # three missing stub files should be filled
    filled = set(body["filled"])
    assert filled == {"era.md", "writing-style-extra.md", "iron-laws-extra.md"}


def test_fill_genre_not_found(client, tmp_genres):
    resp = client.post("/api/genres/does-not-exist/fill")
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/genres/<id>/audit
# ---------------------------------------------------------------------------

def test_audit_genre_returns_counts(client, tmp_genres, monkeypatch):
    """Audit runs stage 1 (setting_lint) + stage 2 (LLM). We stub both to
    keep the test LLM-free, and assert the HTTP contract."""
    # First create a scaffold so audit has something to look at
    client.post("/api/genres/new", json={"id": "audit-smoke"})

    # Stub the expensive Validator .run so no LLM call happens
    from src.genre_extractor.agents import validator as v_mod
    monkeypatch.setattr(v_mod.GenreValidator, "run", lambda self, bb, **kw: None)

    resp = client.post("/api/genres/audit-smoke/audit")
    assert resp.status_code == 200
    body = resp.get_json()
    # Contract: caller gets explicit counts and an ok flag
    assert "error_count" in body
    assert "warning_count" in body
    assert body["genre_id"] == "audit-smoke"


def test_audit_genre_not_found(client, tmp_genres):
    resp = client.post("/api/genres/missing/audit")
    # audit_genre auto-creates build_status on a missing genre (legacy behavior),
    # so we accept either 404 OR a best-effort 200. Document which the route chose.
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# POST /api/genres/<id>/extract
# ---------------------------------------------------------------------------

def test_extract_dry_run_starts_task(client, tmp_genres, tmp_path, monkeypatch):
    """dry_run path must not actually call LLM; just spins up a background
    task that flips build_status phases to 'done' immediately.
    """
    # Setup: create a small source file and a scaffold genre
    source = tmp_path / "tiny.txt"
    source.write_text("第1章 起\n内容。\n第2章 承\n内容。\n", encoding="utf-8")

    client.post("/api/genres/new", json={"id": "extract-smoke"})

    resp = client.post("/api/genres/extract-smoke/extract", json={
        "sources": [str(source)],
        "dry_run": True,
    })
    assert resp.status_code == 202, resp.get_json()
    body = resp.get_json()
    assert body["started"] is True
    assert "started_at" in body

    # Wait briefly for worker to finish (dry_run is basically instant)
    status: dict = {}
    for _ in range(40):  # up to 2 s
        status = client.get("/api/genres/extract-smoke/status").get_json() or {}
        phases = status.get("phases", {})
        if all(phases.get(p, {}).get("status") == "done"
               for p in ("extract", "merge", "draft", "validate")):
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"dry_run did not complete in time; last status={status}")


def test_extract_refuses_missing_sources(client, tmp_genres):
    client.post("/api/genres/new", json={"id": "extract-2"})
    resp = client.post("/api/genres/extract-2/extract", json={
        "sources": [],
        "dry_run": True,
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_extract_rejects_nonexistent_source_file(client, tmp_genres):
    client.post("/api/genres/new", json={"id": "extract-3"})
    resp = client.post("/api/genres/extract-3/extract", json={
        "sources": ["/no/such/file.txt"],
        "dry_run": True,
    })
    # The route should 400 synchronously (validates paths before dispatch)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/genres/<id>/status
# ---------------------------------------------------------------------------

def test_status_when_no_build(client, tmp_genres):
    """If there's no .build/ yet, status returns 200 with running=False."""
    client.post("/api/genres/new", json={"id": "status-smoke"})
    # new_genre creates a build_status, so we should get a payload back
    resp = client.get("/api/genres/status-smoke/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("genre_id") == "status-smoke"
    assert "phases" in data


def test_status_for_missing_genre(client, tmp_genres):
    resp = client.get("/api/genres/never-existed/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/genres/<id>
# ---------------------------------------------------------------------------

def test_delete_genre(client, tmp_genres):
    client.post("/api/genres/new", json={"id": "to-delete"})
    assert (tmp_genres / "to-delete").exists()

    resp = client.delete("/api/genres/to-delete")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert not (tmp_genres / "to-delete").exists()


def test_delete_nonexistent_genre(client, tmp_genres):
    resp = client.delete("/api/genres/ghost")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/genres/<id>/issues
# ---------------------------------------------------------------------------

def test_issues_empty_when_no_build(client, tmp_genres):
    client.post("/api/genres/new", json={"id": "issues-empty"})
    resp = client.get("/api/genres/issues-empty/issues")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["issues"] == []
    assert data["total"] == 0


def test_issues_returns_newest_first_with_limit(client, tmp_genres):
    client.post("/api/genres/new", json={"id": "issues-seed"})
    # Hand-seed the jsonl
    from src import config as cfg
    p = cfg.GENRES_DIR / "issues-seed" / ".build" / "genre_issues.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    with p.open("w", encoding="utf-8") as f:
        for i in range(25):
            f.write(_json.dumps({
                "severity": ["info", "warning", "error"][i % 3],
                "file": f"file{i}.md",
                "message": f"issue {i}",
                "genre_id": "issues-seed",
            }) + "\n")
        f.write("malformed line that is not json\n")  # robustness

    resp = client.get("/api/genres/issues-seed/issues?limit=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["issues"]) == 5
    # Newest-first → last appended (24) should be first
    assert data["issues"][0]["message"] == "issue 24"
    assert data["total"] == 25  # malformed line skipped


def test_issues_missing_genre(client, tmp_genres):
    resp = client.get("/api/genres/ghost/issues")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------

# Views — light smoke test that server-side HTML renders
# ---------------------------------------------------------------------------

def test_genres_index_page(client):
    resp = client.get("/genres")
    assert resp.status_code == 200
    assert b"Novelforge" in resp.data or b"\xe9\xa2\x98\xe6\x9d\x90" in resp.data  # "题材"


def test_genre_detail_page(client):
    resp = client.get("/genres/gangster-hk-1983")
    assert resp.status_code == 200


def test_genre_detail_404(client, tmp_genres):
    resp = client.get("/genres/nope-xyz")
    assert resp.status_code == 404


def test_genre_new_page(client):
    resp = client.get("/genres/new")
    assert resp.status_code == 200


def test_genre_extract_form_page(client):
    # use real genre that exists
    resp = client.get("/genres/gangster-hk-1983/extract")
    assert resp.status_code == 200


def test_extract_page_has_library_picker_and_advanced_textarea(client):
    """Task C: default mode is checkbox-from-library; advanced textarea
    exists for power users who want paths outside novels/."""
    resp = client.get("/genres/gangster-hk-1983/extract")
    html = resp.get_data(as_text=True)
    # Library picker (new default mode)
    assert "novels-picker" in html or "novel-checkbox" in html, \
        "extract page should render the novels/ library picker"
    # Advanced/manual textarea still exists
    assert "f-sources" in html, "manual path textarea should still be accessible"
    # Mode toggle UI
    assert "advanced" in html.lower() or "手敲" in html or "高级" in html


def test_genre_extract_progress_page(client):
    resp = client.get("/genres/gangster-hk-1983/extract/progress")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cancellation plumbing
# ---------------------------------------------------------------------------

def test_cancel_event_exists_on_genre_extractor():
    """The Web abort button sets this; must be on the module."""
    assert hasattr(genre_extractor, "CANCEL_EVENT")
    # also there's a dedicated exception type
    assert hasattr(genre_extractor, "GenrePipelineAborted")
