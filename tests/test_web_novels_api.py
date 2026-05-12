"""Web API: novels/ material library.

Covers the 4 endpoints exposed by web/app.py:
  - GET    /api/novels                    — list .txt files
  - POST   /api/novels/upload             — multipart upload
  - DELETE /api/novels/<name>             — delete one file
  - GET    /api/novels/<name>/preview     — first 2KB

Every test monkey-patches NOVELS_DIR to tmp_path so the real novels/
directory is NEVER written to or deleted. Path-traversal attacks are a
dedicated test class — a regression here would let a Web attacker delete
arbitrary project files.
"""
from __future__ import annotations

import io

import pytest

from web.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def tmp_novels(tmp_path, monkeypatch):
    """Redirect the novels/ sandbox to tmp_path.

    web.app reads _novels_dir() at call time so patching the module attr
    is enough.
    """
    novels = tmp_path / "novels"
    novels.mkdir()
    from web import app as webapp_mod
    monkeypatch.setattr(webapp_mod, "NOVELS_DIR", novels)
    yield novels


# ---------------------------------------------------------------------------
# GET /api/novels
# ---------------------------------------------------------------------------

def test_list_empty(client, tmp_novels):
    resp = client.get("/api/novels")
    assert resp.status_code == 200
    assert resp.get_json() == {"novels": []}


def test_list_two_txt_files(client, tmp_novels):
    (tmp_novels / "a.txt").write_text("第1章 起\n内容\n第2章 承\n内容\n", encoding="utf-8")
    (tmp_novels / "b.txt").write_text("Chapter 1\nhi\nChapter 2\nhi\nChapter 3\nhi\n", encoding="utf-8")
    resp = client.get("/api/novels")
    assert resp.status_code == 200
    data = resp.get_json()
    novels = {n["name"]: n for n in data["novels"]}
    assert set(novels) == {"a.txt", "b.txt"}
    for n in data["novels"]:
        assert "size_bytes" in n
        assert "size_human" in n
        assert n["encoding_ok"] is True
        assert "estimated_chapters" in n
        assert "detected_format" in n
        assert n["path"].startswith("novels/")


def test_list_ignores_non_txt_and_dirs(client, tmp_novels):
    (tmp_novels / "real.txt").write_text("ok", encoding="utf-8")
    (tmp_novels / "README.md").write_text("readme", encoding="utf-8")
    (tmp_novels / ".hidden.txt").write_text("hidden", encoding="utf-8")
    (tmp_novels / "subdir").mkdir()
    (tmp_novels / "subdir" / "nested.txt").write_text("nested", encoding="utf-8")
    resp = client.get("/api/novels")
    names = [n["name"] for n in resp.get_json()["novels"]]
    assert names == ["real.txt"]


def test_list_flags_encoding_failure(client, tmp_novels):
    # Valid UTF-8 header then garbled GBK in the middle
    p = tmp_novels / "gbk.txt"
    p.write_bytes(b"\xc4\xe3\xba\xc3" * 2048)  # "你好" in GBK, repeated
    resp = client.get("/api/novels")
    row = next(n for n in resp.get_json()["novels"] if n["name"] == "gbk.txt")
    assert row["encoding_ok"] is False


def test_list_uses_streaming_for_large_files(client, tmp_novels):
    # Build a >5MB file. We pad chapter markers sparsely so count_chapters
    # running on FULL content would yield 3, but the streaming code path
    # sees only the first slice and might see ≤3. Either way we must NOT
    # OOM or hang — that's the real regression we're guarding against.
    p = tmp_novels / "big.txt"
    padding = ("第1章 起\n" + "正文" * 5000 + "\n") * 300  # ~6MB
    p.write_text(padding, encoding="utf-8")
    # The response should complete promptly and have a valid int chapter count.
    import time as _t
    t0 = _t.time()
    resp = client.get("/api/novels")
    elapsed = _t.time() - t0
    assert resp.status_code == 200
    row = next(n for n in resp.get_json()["novels"] if n["name"] == "big.txt")
    assert isinstance(row["estimated_chapters"], int)
    assert row["estimated_chapters"] >= 1
    assert elapsed < 5.0, f"listing took {elapsed:.2f}s — streaming broken?"


# ---------------------------------------------------------------------------
# POST /api/novels/upload
# ---------------------------------------------------------------------------

def _file_arg(name: str, content: bytes):
    """Shortcut: build a werkzeug FileStorage-compatible (BytesIO, filename)."""
    return (io.BytesIO(content), name)


def test_upload_single_file(client, tmp_novels):
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("hello.txt", "第1章 起\n正文".encode("utf-8"))},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert len(data["uploaded"]) == 1
    assert data["uploaded"][0]["name"] == "hello.txt"
    assert (tmp_novels / "hello.txt").exists()
    assert (tmp_novels / "hello.txt").read_text(encoding="utf-8").startswith("第1章")


def test_upload_multiple_files(client, tmp_novels):
    resp = client.post(
        "/api/novels/upload",
        data={
            "files": [
                _file_arg("one.txt", b"one content"),
                _file_arg("two.txt", b"two content"),
                _file_arg("three.txt", b"three content"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert len(data["uploaded"]) == 3
    for n in ("one.txt", "two.txt", "three.txt"):
        assert (tmp_novels / n).exists()


def test_upload_empty_request(client, tmp_novels):
    resp = client.post("/api/novels/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_upload_rejects_non_txt(client, tmp_novels):
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("cool.pdf", b"fake pdf")},
        content_type="multipart/form-data",
    )
    # Nothing uploaded → 200 (not 201, which is only for "created")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["uploaded"] == []
    assert len(data["skipped"]) == 1
    assert "txt" in data["skipped"][0]["reason"].lower()
    assert not (tmp_novels / "cool.pdf").exists()


def test_upload_rename_on_collision(client, tmp_novels):
    (tmp_novels / "taken.txt").write_text("original", encoding="utf-8")
    # First upload should rename to taken-1.txt
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("taken.txt", b"second")},
        content_type="multipart/form-data",
    )
    data = resp.get_json()
    assert data["uploaded"][0]["name"] == "taken-1.txt"
    assert (tmp_novels / "taken-1.txt").read_text(encoding="utf-8") == "second"
    assert (tmp_novels / "taken.txt").read_text(encoding="utf-8") == "original"

    # Second collision: taken-2.txt
    resp2 = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("taken.txt", b"third")},
        content_type="multipart/form-data",
    )
    data2 = resp2.get_json()
    assert data2["uploaded"][0]["name"] == "taken-2.txt"


def test_upload_path_traversal_is_neutralised(client, tmp_novels, tmp_path):
    """The attacker tries to drop /etc/passwd via a malicious filename.
    After sanitisation the file MUST land inside novels/, NEVER outside.
    """
    # Create a sentinel OUTSIDE novels/ that we'll check is untouched.
    sentinel = tmp_path / "passwd"
    sentinel.write_text("DO NOT OVERWRITE", encoding="utf-8")

    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("../../passwd", b"pwned")},
        content_type="multipart/form-data",
    )
    # 200 (skipped, not a .txt) or 201 (sanitised to novels/passwd.txt would
    # live inside novels/) — both are OK. The invariant under test is the
    # sentinel outside novels/ surviving.
    assert resp.status_code in (200, 201, 400)

    # Sentinel must be intact — this is the core safety assertion
    assert sentinel.read_text(encoding="utf-8") == "DO NOT OVERWRITE"
    # And nothing should have escaped into parent directories.
    for child in tmp_path.iterdir():
        if child.name == "novels":
            continue
        # anything else already existed before the request
        assert child.name in {"passwd"}, f"unexpected file created: {child}"


@pytest.mark.parametrize("bad_name", [
    "../../../etc/passwd",
    "/etc/passwd",
    "..\\..\\Windows\\System32\\evil.txt",
    "foo/bar.txt",
    "..",
    ".",
])
def test_upload_malformed_names_never_escape_novels_dir(client, tmp_novels, bad_name):
    """Sweep of common path-traversal patterns. None may create a file outside novels/."""
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg(bad_name, b"payload")},
        content_type="multipart/form-data",
    )
    # 200 (all skipped) or 201 (sanitised landed inside novels/) or 400
    # (overall rejection). Never a 5xx, and never an escape (asserted below).
    assert resp.status_code in (200, 201, 400)
    # Hard invariant: every file created by this request must live inside
    # tmp_novels. If a traversal worked, something appeared elsewhere.
    # Walk parent — nothing but "novels" should exist.
    import os as _os
    escaped = []
    for p in tmp_novels.parent.rglob("*"):
        if p.is_file() and not str(p).startswith(str(tmp_novels)):
            escaped.append(str(p))
    assert not escaped, f"path traversal escaped: {escaped!r}"


def test_upload_preserves_chinese_filename(client, tmp_novels):
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("某某港综.txt", "第1章\n".encode("utf-8"))},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert len(data["uploaded"]) == 1
    uploaded_name = data["uploaded"][0]["name"]
    # Chinese must be preserved — secure_filename alone would kill it.
    assert "某某港综" in uploaded_name or uploaded_name.endswith("港综.txt"), (
        f"Chinese filename not preserved: {uploaded_name!r}"
    )
    assert (tmp_novels / uploaded_name).exists()


def test_upload_non_utf8_normalised_to_utf8(client, tmp_novels):
    """GBK content is auto-detected and transcoded to UTF-8 on disk.

    (Superseded the old 'flagged but stored' contract once the upload route
    learned to normalise encodings — see test_web_novels_encoding.py for
    the exhaustive per-codec coverage. This test stays as a regression
    guard that the simpler '你好世界 × 500' canary still round-trips.)
    """
    original_text = "你好世界\n" * 500
    gbk_content = original_text.encode("gbk")
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("gbk.txt", gbk_content)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert len(data["uploaded"]) == 1
    u = data["uploaded"][0]
    # New contract: disk is always UTF-8, encoding_ok is always true.
    assert u["encoding_ok"] is True
    assert u["normalized"] is True
    # Round-trip integrity
    assert (tmp_novels / "gbk.txt").read_text("utf-8") == original_text


def test_upload_oversized_file_skipped(client, tmp_novels, monkeypatch):
    """Monkeypatch max size down to 1KB so the test doesn't need to create 50MB."""
    from web import app as webapp_mod
    monkeypatch.setattr(webapp_mod, "NOVEL_MAX_BYTES", 1024)
    big = b"x" * 4096
    resp = client.post(
        "/api/novels/upload",
        data={"files": _file_arg("huge.txt", big)},
        content_type="multipart/form-data",
    )
    # Overall request still succeeds (201/200), single file is skipped with reason.
    assert resp.status_code in (200, 201)
    data = resp.get_json()
    assert data["uploaded"] == []
    assert len(data["skipped"]) == 1
    assert "size" in data["skipped"][0]["reason"].lower() or \
           "large" in data["skipped"][0]["reason"].lower() or \
           "too" in data["skipped"][0]["reason"].lower()
    assert not (tmp_novels / "huge.txt").exists()


def test_upload_atomic_no_tmp_residue(client, tmp_novels):
    """Successful upload should leave only the final file — no .tmp siblings."""
    client.post(
        "/api/novels/upload",
        data={"files": _file_arg("clean.txt", b"content")},
        content_type="multipart/form-data",
    )
    files = [p.name for p in tmp_novels.iterdir()]
    assert files == ["clean.txt"], f"found residue: {files!r}"


# ---------------------------------------------------------------------------
# DELETE /api/novels/<name>
# ---------------------------------------------------------------------------

def test_delete_existing(client, tmp_novels):
    (tmp_novels / "gone.txt").write_text("bye", encoding="utf-8")
    resp = client.delete("/api/novels/gone.txt")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True
    assert not (tmp_novels / "gone.txt").exists()


def test_delete_missing(client, tmp_novels):
    resp = client.delete("/api/novels/ghost.txt")
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_name", [
    "../passwd",
    "../../etc/passwd",
    "foo/bar.txt",
    "..",
])
def test_delete_path_traversal_rejected(client, tmp_novels, tmp_path, bad_name):
    sentinel = tmp_path / "passwd"
    sentinel.write_text("keep me", encoding="utf-8")
    resp = client.delete("/api/novels/" + bad_name)
    # Either 400/403/404 is acceptable — the invariant is the sentinel survived.
    assert resp.status_code in (400, 403, 404)
    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_delete_refuses_dotfile_escape(client, tmp_novels):
    """Flask won't route '/' inside <name>, but %2F encoded could try. We
    treat absolute/relative escapes uniformly."""
    resp = client.delete("/api/novels/" + "%2E%2E%2Fescape.txt")
    assert resp.status_code in (400, 403, 404)


# ---------------------------------------------------------------------------
# GET /api/novels/<name>/preview
# ---------------------------------------------------------------------------

def test_preview_small_file(client, tmp_novels):
    (tmp_novels / "tiny.txt").write_text("第1章\nHello 世界\n", encoding="utf-8")
    resp = client.get("/api/novels/tiny.txt/preview")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "tiny.txt"
    assert "第1章" in data["head"]
    assert data["truncated"] is False


def test_preview_respects_2kb_cap(client, tmp_novels):
    """Large file → head must NOT exceed 2000 chars, and only the head is read."""
    long = "甲" * 5000
    (tmp_novels / "long.txt").write_text(long, encoding="utf-8")
    resp = client.get("/api/novels/long.txt/preview")
    data = resp.get_json()
    assert len(data["head"]) <= 2000
    assert data["truncated"] is True


def test_preview_404_for_missing(client, tmp_novels):
    resp = client.get("/api/novels/nope.txt/preview")
    assert resp.status_code == 404


def test_preview_path_traversal_rejected(client, tmp_novels, tmp_path):
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    resp = client.get("/api/novels/..%2F..%2Fsecret.txt/preview")
    assert resp.status_code in (400, 403, 404)
    body = resp.get_data(as_text=True)
    assert "TOP SECRET" not in body


# ---------------------------------------------------------------------------
# View — /novels page smoke
# ---------------------------------------------------------------------------

def test_novels_view_renders(client):
    resp = client.get("/novels")
    assert resp.status_code == 200
    # page should contain its own title + static asset hooks
    body = resp.get_data(as_text=True)
    assert "novels.js" in body
    assert "素材库" in body or "Novels" in body


def test_novels_view_mentions_supported_encodings(client):
    """Task C: dropzone sub-text tells users they don't have to pre-convert."""
    resp = client.get("/novels")
    body = resp.get_data(as_text=True)
    # Key encodings + a hint that auto-conversion happens
    for needle in ("GB18030", "Big5", "自动转"):
        assert needle in body, f"dropzone hint missing {needle!r}"
