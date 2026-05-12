"""Streaming chapter iterator over novel files.

For large novels (>= STREAMING_THRESHOLD_BYTES, default 5MB) we avoid
loading the entire file into memory. Instead we:

  1. Index phase: scan the file once in binary mode, collecting byte
     offsets of every '第N章' marker. The in-memory footprint is only
     ~O(total_chapters * 32 bytes) = a few KB even for 1000-chapter novels.

  2. Read phase: `read_batch(start, end)` seeks to `chapter_refs[start-1]
     .byte_offset`, reads just the bytes through the end of chapter `end`,
     and decodes them (UTF-8). This means peak RAM per batch is roughly
     the size of one batch (~300KB-1MB), not the whole file.

For small files (< threshold) we use the existing fast path: read the
whole text into memory and slice by chapter offsets. Behaviour matches
the pre-streaming implementation.

NOTE: This module intentionally ships with a small, self-contained chapter
detector ("第N章" regex). Once src.tools.chapter_detector lands, this
should delegate to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


# Files smaller than this are loaded fully into memory. Above, streaming.
# 5 MB is the documented threshold; see AGENTS.md perf notes.
STREAMING_THRESHOLD_BYTES = 5 * 1024 * 1024


# Must compile on bytes (for streaming pass) and on str (for in-memory pass).
# "第 <arabic or CJK numeral> 章" at line start or after whitespace.
_CHAPTER_MARKER_PATTERN_STR = re.compile(r"第[0-9零一二三四五六七八九十百千]+章")
_CHAPTER_MARKER_PATTERN_BYTES = re.compile(
    "第[0-9零一二三四五六七八九十百千]+章".encode("utf-8")
)


@dataclass
class ChapterRef:
    """Location of one chapter inside its source file (byte coordinates)."""
    source_path: str
    chapter_index: int  # 1-based
    byte_offset: int    # start byte in file (inclusive, UTF-8 safe: landed at '第')
    byte_length: int    # number of bytes in this chapter (to next marker or EOF)


class ChapterStream:
    """Streaming chapter iterator over one novel file.

    Usage:
        stream = ChapterStream("path/to/novel.txt")
        n = stream.total_chapters
        chunk = stream.read_batch(1, 25)   # read chapters 1..25 inclusive
    """

    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"source novel not found: {p}")
        self._path: Path = p
        size = p.stat().st_size
        self._file_size: int = size
        self._is_streaming: bool = size >= STREAMING_THRESHOLD_BYTES

        # chapter_refs always uses byte coordinates so read_batch has a
        # single code path. For the small-file fast path we still hold the
        # decoded text around so we can slice str directly.
        self._full_text: str | None = None
        self._chapter_refs: list[ChapterRef] = []

        if self._is_streaming:
            self._chapter_refs = self._build_index_streaming()
        else:
            self._full_text = p.read_text(encoding="utf-8")
            self._chapter_refs = self._build_index_from_text(self._full_text)

    # ---- public API -------------------------------------------------------

    @property
    def total_chapters(self) -> int:
        return max(len(self._chapter_refs), 1)

    @property
    def is_streaming(self) -> bool:
        return self._is_streaming

    @property
    def chapter_refs(self) -> list[ChapterRef]:
        return list(self._chapter_refs)

    def read_batch(self, start_ch: int, end_ch: int) -> str:
        """Return chapters [start_ch, end_ch] inclusive (1-indexed).

        Streaming path: seek + read exactly the bytes in question.
        Small-file path: slice the cached full text.
        """
        self._validate_range(start_ch, end_ch)

        # No markers at all: treat whole file as one chapter.
        if not self._chapter_refs:
            if self._full_text is not None:
                return self._full_text
            return self._path.read_text(encoding="utf-8")

        start_ref = self._chapter_refs[start_ch - 1]
        end_ref = self._chapter_refs[end_ch - 1]

        if not self._is_streaming and self._full_text is not None:
            # We have offsets in bytes; translate to str indices by decoding
            # the prefix. Cheaper: since we cached str, use a str-level scan.
            # We rebuilt indexes on str in that branch, so use those directly.
            # See _build_index_from_text: byte_offset is actually char index
            # in the small-file branch. Keep that invariant.
            start_char = start_ref.byte_offset
            end_char = end_ref.byte_offset + end_ref.byte_length
            return self._full_text[start_char:end_char]

        # Streaming path: single seek + single read.
        read_start = start_ref.byte_offset
        read_end = end_ref.byte_offset + end_ref.byte_length
        read_len = read_end - read_start
        with self._path.open("rb") as f:
            f.seek(read_start)
            raw = f.read(read_len)
        # Offsets were aligned to '第' (ASCII-safe leading byte of that CJK
        # sequence) so decode is clean. Still use 'replace' as a safety net.
        return raw.decode("utf-8", errors="replace")

    # ---- internal ---------------------------------------------------------

    def _validate_range(self, start_ch: int, end_ch: int) -> None:
        if start_ch < 1:
            raise ValueError(f"start_ch must be >= 1, got {start_ch}")
        if end_ch < start_ch:
            raise ValueError(
                f"end_ch ({end_ch}) must be >= start_ch ({start_ch})"
            )
        total = len(self._chapter_refs) if self._chapter_refs else 1
        if end_ch > total:
            raise ValueError(
                f"end_ch ({end_ch}) exceeds total_chapters ({total})"
            )

    def _build_index_from_text(self, text: str) -> list[ChapterRef]:
        """Small-file path: index by **character** offsets in the decoded
        str. We store them in ChapterRef.byte_offset/byte_length anyway —
        in this branch those fields are string char indices, and
        read_batch() handles the branching. Keeping the same field names
        avoids a second dataclass just for the fast path."""
        refs: list[ChapterRef] = []
        matches = list(_CHAPTER_MARKER_PATTERN_STR.finditer(text))
        if not matches:
            return []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            refs.append(ChapterRef(
                source_path=str(self._path),
                chapter_index=i + 1,
                byte_offset=start,
                byte_length=end - start,
            ))
        return refs

    def _build_index_streaming(self) -> list[ChapterRef]:
        """Large-file path: scan the file in binary, record byte offsets of
        every '第N章' marker. We read in large blocks with a tail-overlap
        so markers that straddle block boundaries are still matched once."""
        refs: list[ChapterRef] = []
        marker_bytes = "第".encode("utf-8")  # 3 bytes
        # Worst case: "第" + longest numeric CJK + "章". Keep overlap
        # comfortably larger than any possible marker.
        overlap = 64

        offsets: list[int] = []
        block_size = 1 << 20  # 1 MB
        with self._path.open("rb") as f:
            pos = 0
            tail = b""
            tail_start = 0
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                buf = tail + chunk
                # buf starts at file offset tail_start
                for m in _CHAPTER_MARKER_PATTERN_BYTES.finditer(buf):
                    abs_off = tail_start + m.start()
                    if offsets and abs_off <= offsets[-1]:
                        continue  # dedup across overlap
                    offsets.append(abs_off)
                # Preserve tail overlap so cross-boundary markers still match
                if len(buf) > overlap:
                    tail = buf[-overlap:]
                    tail_start = tail_start + len(buf) - overlap
                else:
                    tail = buf
                    # tail_start unchanged
                pos += len(chunk)

        if not offsets:
            return []

        file_size = self._file_size
        for i, off in enumerate(offsets):
            end = offsets[i + 1] if i + 1 < len(offsets) else file_size
            refs.append(ChapterRef(
                source_path=str(self._path),
                chapter_index=i + 1,
                byte_offset=off,
                byte_length=end - off,
            ))
        # Sanity: offsets land on '第' which begins with 0xE7; decode safety
        # is therefore guaranteed.
        return refs
