"""Extraction tally — human-readable "health dashboard" for a genre build.

Produces ``genres/<id>/.build/extraction_tally.md`` at the end of the merge
phase. Pure data aggregation; no LLM call.

Inputs (all read through Blackboard):
    build_status.yaml                      — genre_id + novel_sources + phase state
    extraction_notes/batch-*.yaml          — one per batch

Output:
    Markdown string (caller decides where to write it).

Sections (in order):
    1. 覆盖范围            — novels / chapters / batches / progress
    2. 批次产物            — per-batch table
    3. Iron law 候选频次 Top 10
    4. era_observations confidence 分布
    5. Style marker 频次 Top 10
    6. Resource schema 候选          — omitted if empty
    7. 开放问题池          — up to 10 aggregated questions
    8. 禁用模糊词扫描      — cross-check against schemas._FUZZY_TERMS
    9. 数据健康            — coverage / low-confidence batches / avg rules
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from src.core.blackboard import Blackboard
from src.genre_extractor import schemas


_TOP_N = 10


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_extraction_tally(bb: Blackboard, genre_id: str) -> str:
    """Aggregate batch notes + build_status into an extraction_tally.md string.

    Pure function — does not write to disk. Caller does ``bb.write_text(...)``.
    """
    # ---- Load inputs (graceful on missing pieces) --------------------------
    status: dict[str, Any] = {}
    if bb.exists("build_status.yaml"):
        try:
            status = bb.read_yaml("build_status.yaml") or {}
        except Exception:
            status = {}

    batch_files = bb.list_files("extraction_notes", "batch-*.yaml")
    batches: list[dict[str, Any]] = []
    for p in batch_files:
        try:
            note = bb.read_yaml(f"extraction_notes/{p.name}")
        except Exception:
            continue
        if isinstance(note, dict):
            note.setdefault("_source_file", p.name)
            batches.append(note)

    # ---- Assemble sections --------------------------------------------------
    parts: list[str] = []
    parts.append(f"# Extraction Tally · {genre_id}")
    parts.append("")
    parts.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    parts.append("")

    parts.append(_section_coverage(status, batches))
    parts.append(_section_batch_table(batches))
    parts.append(_section_iron_law_top(batches, top_n=_TOP_N))
    parts.append(_section_era_confidence(batches))
    parts.append(_section_style_markers_top(batches, top_n=_TOP_N))

    resource_section = _section_resource_candidates(batches)
    if resource_section:
        parts.append(resource_section)

    parts.append(_section_open_questions(batches, limit=_TOP_N))
    parts.append(_section_fuzzy_scan(batches))
    parts.append(_section_data_health(batches))

    # Trim trailing blank lines, ensure single newline at EOF
    md = "\n\n".join(p.rstrip() for p in parts if p).rstrip() + "\n"
    return md


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _section_coverage(status: dict, batches: list[dict]) -> str:
    novel_sources = status.get("novel_sources", []) or []
    novels_count = len(novel_sources)
    total_chapters = sum(int(s.get("total_chapters", 0) or 0) for s in novel_sources)

    extract_phase = (status.get("phases", {}) or {}).get("extract", {}) or {}
    batches_total = int(extract_phase.get("batches_total", 0) or 0)
    batches_done = int(extract_phase.get("batches_done", 0) or 0)
    if batches_total == 0:
        # Fall back to what we actually saw on disk
        batches_total = len(batches)
        batches_done = len(batches)

    # Dominant batch size: take the first source's batch_size, or infer
    batch_size_label = "?"
    if novel_sources:
        sizes = {int(s.get("batch_size", 0) or 0) for s in novel_sources}
        sizes.discard(0)
        if len(sizes) == 1:
            batch_size_label = f"{next(iter(sizes))}/batch"
        elif sizes:
            batch_size_label = f"{min(sizes)}–{max(sizes)}/batch"

    pct = (batches_done / batches_total * 100.0) if batches_total > 0 else 0.0

    lines = ["## 覆盖范围", ""]
    lines.append(f"- 已读 **{novels_count} 本小说**，共 **{total_chapters} 章**")
    lines.append(f"- 分 **{batches_total} 批**（档位：{batch_size_label}）")
    lines.append(f"- 当前进度: **{batches_done}/{batches_total} ({pct:.0f}%)**")
    return "\n".join(lines)


def _section_batch_table(batches: list[dict]) -> str:
    lines = ["## 批次产物", ""]
    if not batches:
        lines.append("(no batch notes found)")
        return "\n".join(lines)

    lines.append("| Batch | Chapters | Source | Rules | Era facts | Style markers |")
    lines.append("|-------|----------|--------|-------|-----------|---------------|")
    for note in batches:
        bid = note.get("batch_id", "?")
        cc = note.get("chapters_covered") or []
        if isinstance(cc, list) and len(cc) == 2:
            ch_label = f"{cc[0]}-{cc[1]}"
        else:
            ch_label = "?"
        source = note.get("novel_source", "?") or "?"
        rules = len(note.get("iron_law_candidates", []) or [])
        eras = len(note.get("era_observations", []) or [])
        styles = len(note.get("style_markers", []) or [])
        # batch id padded
        try:
            bid_label = f"{int(bid):03d}"
        except (TypeError, ValueError):
            bid_label = str(bid)
        lines.append(
            f"| {bid_label} | {ch_label} | {source} | {rules} | {eras} | {styles} |"
        )
    return "\n".join(lines)


def _section_iron_law_top(batches: list[dict], *, top_n: int) -> str:
    """Aggregate iron_law_candidates across batches.

    Key: prefer cand_id if present, else the summary string (truncated).
    Value: sum of recurrence_count (fallback 1) across occurrences.
    """
    bucket: dict[str, dict] = {}
    for note in batches:
        for law in note.get("iron_law_candidates", []) or []:
            if not isinstance(law, dict):
                continue
            summary = str(law.get("summary", "")).strip()
            cand_id = law.get("cand_id") or summary[:30] or "(unnamed)"
            rc = law.get("recurrence_count", 1)
            try:
                rc = int(rc)
            except (TypeError, ValueError):
                rc = 1
            slot = bucket.setdefault(
                cand_id,
                {"cand_id": cand_id, "summary": summary, "total": 0},
            )
            slot["total"] += rc
            # Keep the longest summary we've seen (most informative)
            if len(summary) > len(slot["summary"]):
                slot["summary"] = summary

    lines = [f"## Iron law 候选频次 Top {top_n}", ""]
    if not bucket:
        lines.append("(no iron_law_candidates across all batches)")
        return "\n".join(lines)

    ranked = sorted(bucket.values(), key=lambda x: x["total"], reverse=True)[:top_n]
    lines.append("| # | cand_id | statement（节选） | total_recurrence |")
    lines.append("|---|---------|-------------------|------------------|")
    for i, row in enumerate(ranked, start=1):
        snippet = row["summary"][:40] + ("…" if len(row["summary"]) > 40 else "")
        lines.append(f"| {i} | {row['cand_id']} | {snippet} | {row['total']} |")
    return "\n".join(lines)


def _section_era_confidence(batches: list[dict]) -> str:
    counts = Counter()
    for note in batches:
        for era in note.get("era_observations", []) or []:
            if isinstance(era, dict):
                c = era.get("confidence", "unknown")
                counts[c] += 1

    lines = ["## era_observations confidence 分布", ""]
    if sum(counts.values()) == 0:
        lines.append("(no era_observations across all batches)")
        return "\n".join(lines)

    # Stable order: high / medium / low / others
    for key in ("high", "medium", "low"):
        n = counts.get(key, 0)
        suffix = ""
        if key == "low" and n:
            suffix = "（Drafter 将降权或丢弃）"
        lines.append(f"- {key}: **{n}** 条{suffix}".rstrip())
    # Any unexpected buckets
    extras = sorted(k for k in counts if k not in {"high", "medium", "low"})
    for k in extras:
        lines.append(f"- {k}: **{counts[k]}** 条")
    return "\n".join(lines)


def _section_style_markers_top(batches: list[dict], *, top_n: int) -> str:
    """Aggregate style markers by (marker, measurement) pair."""
    bucket: dict[tuple[str, str], dict] = {}
    for note in batches:
        for m in note.get("style_markers", []) or []:
            if not isinstance(m, dict):
                continue
            marker = str(m.get("marker", "")).strip() or "(unnamed)"
            measurement = str(m.get("measurement", "")).strip()
            key = (marker, measurement)
            slot = bucket.setdefault(
                key,
                {"marker": marker, "measurement": measurement, "batches": 0},
            )
            slot["batches"] += 1

    lines = [f"## Style marker 频次 Top {top_n}", ""]
    if not bucket:
        lines.append("(no style_markers across all batches)")
        return "\n".join(lines)

    ranked = sorted(bucket.values(), key=lambda x: x["batches"], reverse=True)[:top_n]
    lines.append("| # | marker | measurement | batches_observed |")
    lines.append("|---|--------|-------------|------------------|")
    for i, row in enumerate(ranked, start=1):
        lines.append(
            f"| {i} | {row['marker']} | {row['measurement'] or '—'} | {row['batches']} 批 |"
        )
    return "\n".join(lines)


def _section_resource_candidates(batches: list[dict]) -> str:
    """Return empty string to signal omission when no resource candidates."""
    bucket: dict[str, dict] = {}
    for note in batches:
        for r in note.get("resource_candidates", []) or []:
            if not isinstance(r, dict):
                continue
            # Try a few common key names for the resource id/name
            rid = (
                r.get("resource_id")
                or r.get("name")
                or r.get("summary")
                or "(unnamed)"
            )
            rid = str(rid).strip() or "(unnamed)"
            display = r.get("display_name") or r.get("label") or ""
            chapters = r.get("evidence_chapters") or []
            slot = bucket.setdefault(
                rid,
                {"id": rid, "display": display, "chapters": set()},
            )
            for c in chapters:
                try:
                    slot["chapters"].add(int(c))
                except (TypeError, ValueError):
                    pass
            if display and not slot["display"]:
                slot["display"] = display

    if not bucket:
        return ""  # sentinel: caller omits section

    lines = ["## Resource schema 候选", ""]
    for rid, info in sorted(bucket.items(), key=lambda kv: -len(kv[1]["chapters"])):
        display_part = f" ({info['display']})" if info["display"] else ""
        chapters = sorted(info["chapters"])
        sample = ", ".join(str(c) for c in chapters[:3])
        more = f" 等 {len(chapters)} 章" if chapters else " (无章节信息)"
        ch_label = f"出现于 ch {sample}{more}" if chapters else "出现章节未标注"
        lines.append(f"- {rid}{display_part}: {ch_label}")
    return "\n".join(lines)


def _section_open_questions(batches: list[dict], *, limit: int) -> str:
    lines = ["## 开放问题池", ""]
    lines.append(f"(从所有批的 open_questions 聚合，最多显示 {limit} 条)")

    collected: list[tuple[int, str]] = []
    for note in batches:
        bid = note.get("batch_id", "?")
        for q in note.get("open_questions", []) or []:
            if isinstance(q, str) and q.strip():
                collected.append((bid, q.strip()))
            elif isinstance(q, dict):
                text = str(q.get("question") or q.get("summary") or "").strip()
                if text:
                    collected.append((bid, text))

    if not collected:
        lines.append("- (no open questions)")
        return "\n".join(lines)

    for bid, q in collected[:limit]:
        try:
            bid_label = f"batch {int(bid):03d}"
        except (TypeError, ValueError):
            bid_label = f"batch {bid}"
        lines.append(f"- [{bid_label}] {q}")
    return "\n".join(lines)


def _section_fuzzy_scan(batches: list[dict]) -> str:
    """Scan every batch's strings against schemas._FUZZY_TERMS."""
    hits: list[tuple[Any, str]] = []  # (batch_id, term)
    for note in batches:
        bid = note.get("batch_id", "?")
        # Reuse the well-tested scanner from schemas
        terms = schemas._scan_fuzzy_terms(note)
        for t in terms:
            hits.append((bid, t))

    lines = ["## 禁用模糊词扫描", ""]
    lines.append(f"- 已扫描全部 batch 笔记中的字符串字段")
    if not hits:
        lines.append(f"- 命中次数: **0 次** ✅")
    else:
        # Group by (batch, term)
        by_batch: dict[Any, list[str]] = {}
        for bid, term in hits:
            by_batch.setdefault(bid, []).append(term)
        lines.append(f"- 命中次数: **{len(hits)} 次** ❌")
        for bid in sorted(by_batch, key=lambda x: (isinstance(x, str), x)):
            try:
                bid_label = f"batch {int(bid):03d}"
            except (TypeError, ValueError):
                bid_label = f"batch {bid}"
            uniq_terms = sorted(set(by_batch[bid]))
            lines.append(f"  - {bid_label}: {', '.join(uniq_terms)}")
    return "\n".join(lines)


def _section_data_health(batches: list[dict]) -> str:
    total = len(batches)

    no_rules = sum(
        1 for n in batches if not (n.get("iron_law_candidates") or [])
    )

    low_heavy = 0
    rule_counts: list[int] = []
    for n in batches:
        eras = n.get("era_observations", []) or []
        if eras:
            lows = sum(
                1 for e in eras
                if isinstance(e, dict) and e.get("confidence") == "low"
            )
            if lows * 2 > len(eras):  # strictly over half
                low_heavy += 1
        rule_counts.append(len(n.get("iron_law_candidates", []) or []))

    avg_rules = (sum(rule_counts) / total) if total else 0.0

    lines = ["## 数据健康", ""]
    lines.append(f"- Batches without rules: {no_rules} / {total}")
    suffix = " ⚠️" if low_heavy else ""
    lines.append(f"- Batches with confidence=low 占比过半: {low_heavy} / {total}{suffix}")
    lines.append(f"- Average iron_law_candidates per batch: {avg_rules:.1f}")
    return "\n".join(lines)
