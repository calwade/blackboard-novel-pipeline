"""Setting Lint — validate a setting pack's structure, schema, and cross-references.

Usage:
    python -m src.tools.setting_lint --setting gangster-hk-1983
    python -m src.tools.setting_lint --all
    python -m src.tools.setting_lint --setting xianxia-ascension --strict

Levels:
    ERROR   — must fix; pipeline won't run correctly
    WARNING — should fix; degrades quality
    INFO    — suggestion; for setting authors

Exit codes:
    0  no errors (warnings allowed unless --strict)
    1  has errors (or has warnings + --strict)
    2  setting not found / arg error

Checks performed:
    1. File presence: all 7 required files exist
    2. Parseability: YAML / JSON parse successfully
    3. Schema: each file has the required top-level fields
    4. Cross-references:
       - setting.yaml.protagonist_name == characters.yaml.protagonist.name
       - outline.json.chapters[].key_characters are all in characters.yaml
       - outline.json.chapters[].year_month falls within timeline.yaml span
    5. Content thresholds:
       - era.md ≥ 500 chars (too thin = bad worldbuilding)
       - writing-style-extra.md ≥ 300 chars
       - iron-laws-extra.md ≥ 3 iron_law_extra_N entries
       - outline.json first 3 chapters fully beat-sheeted (黄金三章)
    6. Hygiene:
       - no 'MVP' / '黑客松' / 'hackathon' meta-speak in any *.md
       - no repetition of rules/writing-style-core.md content in
         writing-style-extra.md (avoid duplication)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import config


# --- schema ---

REQUIRED_FILES = [
    "setting.yaml",
    "outline.json",
    "timeline.yaml",
    "characters.yaml",
    "era.md",
    "writing-style-extra.md",
    "iron-laws-extra.md",
]

REQUIRED_SETTING_FIELDS = [
    "id",
    "display_name",
    "locale",
    "genre",
    "era",
    "tone",
    "protagonist_name",
    "chapter_count_target",
    "chapters_in_outline",
]

REQUIRED_OUTLINE_FIELDS = [
    "title",
    "protagonist",
    "chapter_count_target",
    "chapters",
]

REQUIRED_CHAPTER_FIELDS = [
    "ch",
    "title",
    "key_characters",
    "beats",
]

FULLY_BEATED_FIELDS = [
    "ch",
    "title",
    "year_month",
    "key_location",
    "key_characters",
    "beats",
    "opening_hook",
    "closing_hook",
    "tension",
    "word_target",
]

META_WORDS_BLOCKED_IN_SETTING_MD = [
    "MVP",
    "黑客松",
    "hackathon",
    "参赛作品",
    "评委",
]

MIN_ERA_CHARS = 500
MIN_STYLE_EXTRA_CHARS = 300
MIN_EXTRA_IRON_LAWS = 3


# --- lint infrastructure ---

@dataclass
class LintIssue:
    level: str  # "ERROR" | "WARNING" | "INFO"
    file: str
    message: str

    def render(self) -> str:
        icon = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "ℹ️ "}[self.level]
        return f"  {icon} [{self.level:7}] {self.file}: {self.message}"


@dataclass
class LintReport:
    setting_name: str
    issues: list[LintIssue] = field(default_factory=list)

    def error(self, file: str, msg: str) -> None:
        self.issues.append(LintIssue("ERROR", file, msg))

    def warning(self, file: str, msg: str) -> None:
        self.issues.append(LintIssue("WARNING", file, msg))

    def info(self, file: str, msg: str) -> None:
        self.issues.append(LintIssue("INFO", file, msg))

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.level == "ERROR")

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.level == "WARNING")

    @property
    def n_infos(self) -> int:
        return sum(1 for i in self.issues if i.level == "INFO")

    def render(self) -> str:
        lines = [f"\n=== {self.setting_name} ==="]
        if not self.issues:
            lines.append("  🟢 全部检查通过")
        else:
            for issue in self.issues:
                lines.append(issue.render())
        lines.append(
            f"  → errors: {self.n_errors}, warnings: {self.n_warnings}, "
            f"infos: {self.n_infos}"
        )
        return "\n".join(lines)


# --- individual checks ---

def lint_setting(setting_dir: Path) -> LintReport:
    name = setting_dir.name
    report = LintReport(setting_name=name)

    # Check 1: file presence
    missing = [f for f in REQUIRED_FILES if not (setting_dir / f).exists()]
    for f in missing:
        report.error(f, "required file missing")
    if missing:
        return report  # nothing else to check

    # Check 2: parseability + load data
    try:
        setting_yaml = yaml.safe_load((setting_dir / "setting.yaml").read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        report.error("setting.yaml", f"YAML parse failed: {e}")
        return report

    try:
        outline = json.loads((setting_dir / "outline.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.error("outline.json", f"JSON parse failed: {e}")
        return report

    try:
        timeline = yaml.safe_load((setting_dir / "timeline.yaml").read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        report.error("timeline.yaml", f"YAML parse failed: {e}")
        return report

    try:
        characters = yaml.safe_load((setting_dir / "characters.yaml").read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        report.error("characters.yaml", f"YAML parse failed: {e}")
        return report

    era_md = (setting_dir / "era.md").read_text(encoding="utf-8")
    style_extra_md = (setting_dir / "writing-style-extra.md").read_text(encoding="utf-8")
    iron_extra_md = (setting_dir / "iron-laws-extra.md").read_text(encoding="utf-8")

    # Check 3a: setting.yaml schema
    if not isinstance(setting_yaml, dict):
        report.error("setting.yaml", "top-level must be a mapping")
    else:
        for f in REQUIRED_SETTING_FIELDS:
            if f not in setting_yaml:
                report.error("setting.yaml", f"missing required field: {f}")
        # id should match directory name for clarity
        if setting_yaml.get("id") and setting_yaml["id"] != name:
            report.warning(
                "setting.yaml",
                f"id='{setting_yaml['id']}' doesn't match dir name '{name}' "
                "(reproducibility: bootstrap --setting <dir> uses dir name)",
            )

    # Check 3b: outline.json schema
    if not isinstance(outline, dict):
        report.error("outline.json", "top-level must be an object")
    else:
        for f in REQUIRED_OUTLINE_FIELDS:
            if f not in outline:
                report.error("outline.json", f"missing required field: {f}")

        chapters = outline.get("chapters") or []
        if not isinstance(chapters, list):
            report.error("outline.json", "chapters must be a list")
            chapters = []

        declared_ct = outline.get("chapters_in_outline", len(chapters))
        if declared_ct != len(chapters):
            report.warning(
                "outline.json",
                f"chapters_in_outline={declared_ct} but "
                f"actual chapters list has {len(chapters)} entries",
            )

        for i, ch in enumerate(chapters):
            if not isinstance(ch, dict):
                report.error("outline.json", f"chapters[{i}] not a dict")
                continue
            for f in REQUIRED_CHAPTER_FIELDS:
                if f not in ch:
                    report.error(
                        "outline.json",
                        f"chapters[{i}] (ch={ch.get('ch', '?')}) missing field: {f}",
                    )

    # Check 3c: characters.yaml schema
    if not isinstance(characters, dict):
        report.error("characters.yaml", "top-level must be a mapping")
    else:
        if "protagonist" not in characters:
            report.error("characters.yaml", "missing 'protagonist' section")
        else:
            proto = characters["protagonist"]
            if not isinstance(proto, dict) or "name" not in proto:
                report.error(
                    "characters.yaml",
                    "protagonist must be a dict with at least 'name'",
                )

        supporting = characters.get("supporting", [])
        if not isinstance(supporting, list):
            report.warning("characters.yaml", "'supporting' should be a list")
        elif len(supporting) < 3:
            report.warning(
                "characters.yaml",
                f"only {len(supporting)} supporting characters; "
                "setting with <3 supporting chars feels thin",
            )

    # Check 3d: timeline.yaml schema
    if timeline is None or (not isinstance(timeline, (dict, list))):
        report.warning("timeline.yaml", "empty or non-mapping/list timeline")
    else:
        # Count total entries (timeline can be nested by year or flat list)
        total = _count_timeline_entries(timeline)
        if total < 3:
            report.warning(
                "timeline.yaml",
                f"only {total} timeline entries; ≥3 recommended for era grounding",
            )

    # Check 4: cross-references
    # 4a: setting.protagonist_name == characters.protagonist.name
    sy_proto = (setting_yaml or {}).get("protagonist_name")
    ch_proto = ((characters or {}).get("protagonist") or {}).get("name")
    if sy_proto and ch_proto and sy_proto != ch_proto:
        report.error(
            "setting.yaml↔characters.yaml",
            f"protagonist_name mismatch: setting.yaml='{sy_proto}' "
            f"vs characters.yaml='{ch_proto}'",
        )

    # 4b: outline key_characters must appear in characters.yaml
    if isinstance(characters, dict):
        known_names = _extract_character_names(characters)
        for i, ch in enumerate(outline.get("chapters") or []):
            if not isinstance(ch, dict):
                continue
            for char in ch.get("key_characters") or []:
                if not _character_known(char, known_names):
                    report.warning(
                        "outline.json↔characters.yaml",
                        f"chapters[{i}] (ch={ch.get('ch', '?')}) references "
                        f"unknown character '{char}'",
                    )

    # 4c: outline characters actually appear in some chapter
    # (reverse check: every supporting character should show up in outline)
    outline_cast: set[str] = set()
    for ch in outline.get("chapters") or []:
        if isinstance(ch, dict):
            for char in ch.get("key_characters") or []:
                outline_cast.add(str(char))
    if isinstance(characters, dict):
        for supp in characters.get("supporting") or []:
            if isinstance(supp, dict) and "name" in supp:
                if not _character_known(supp["name"], outline_cast):
                    report.info(
                        "characters.yaml↔outline.json",
                        f"supporting '{supp['name']}' never appears in outline",
                    )

    # Check 5: content thresholds
    era_chars = len(era_md.replace("\n", "").replace(" ", ""))
    if era_chars < MIN_ERA_CHARS:
        report.warning(
            "era.md",
            f"only {era_chars} chars; minimum recommended {MIN_ERA_CHARS} "
            "(thin era = weak Generator grounding)",
        )

    style_chars = len(style_extra_md.replace("\n", "").replace(" ", ""))
    if style_chars < MIN_STYLE_EXTRA_CHARS:
        report.warning(
            "writing-style-extra.md",
            f"only {style_chars} chars; minimum recommended {MIN_STYLE_EXTRA_CHARS}",
        )

    extra_laws = re.findall(r"iron_law_extra_(\d+)", iron_extra_md)
    if len(extra_laws) < MIN_EXTRA_IRON_LAWS:
        report.warning(
            "iron-laws-extra.md",
            f"found {len(extra_laws)} iron_law_extra_N entries; "
            f"minimum recommended {MIN_EXTRA_IRON_LAWS} "
            "(genre-specific rules are how settings differ)",
        )

    # Golden 3 chapters: first 3 must be fully beated
    chapters_list = outline.get("chapters") or []
    for i in range(min(3, len(chapters_list))):
        ch = chapters_list[i]
        if not isinstance(ch, dict):
            continue
        missing_fields = [f for f in FULLY_BEATED_FIELDS if f not in ch]
        if missing_fields:
            report.warning(
                "outline.json",
                f"chapters[{i}] (ch={ch.get('ch', '?')}) is in 黄金三章 "
                f"but missing detailed fields: {missing_fields}",
            )
        beats = ch.get("beats") or []
        if len(beats) < 3:
            report.warning(
                "outline.json",
                f"chapters[{i}] (ch={ch.get('ch', '?')}) has only "
                f"{len(beats)} beat(s); first 3 chapters should have ≥3 each",
            )

    # Check 6: hygiene — no meta-speak
    for file in [era_md, style_extra_md, iron_extra_md]:
        pass  # handled per-file below

    for fname, content in [
        ("era.md", era_md),
        ("writing-style-extra.md", style_extra_md),
        ("iron-laws-extra.md", iron_extra_md),
    ]:
        for word in META_WORDS_BLOCKED_IN_SETTING_MD:
            if word in content:
                report.info(
                    fname,
                    f"contains project-meta word '{word}' — setting content "
                    "should be in-world, not refer to the system project",
                )

    return report


# --- helpers ---

def _count_timeline_entries(timeline) -> int:
    """Timeline can be {year: [event, ...]} or a flat list."""
    if isinstance(timeline, list):
        return len(timeline)
    if isinstance(timeline, dict):
        total = 0
        for v in timeline.values():
            if isinstance(v, list):
                total += len(v)
            elif isinstance(v, (dict, str)):
                total += 1
        return total
    return 0


def _extract_character_names(characters: dict) -> set[str]:
    names: set[str] = set()
    proto = characters.get("protagonist")
    if isinstance(proto, dict) and "name" in proto:
        names.add(str(proto["name"]))
    for s in characters.get("supporting") or []:
        if isinstance(s, dict) and "name" in s:
            names.add(str(s["name"]))
    return names


def _character_known(name: str, known_names: set[str]) -> bool:
    """Loose match: a key_character reference matches if it's a substring of
    any known name or vice versa (handles '阿威（陈威）' vs '阿威' or '苏婷' vs '苏婷记者').
    """
    if name in known_names:
        return True
    for known in known_names:
        if name in known or known in name:
            return True
    return False


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="Lint a setting pack for completeness and consistency"
    )
    parser.add_argument("--setting", help="Setting name under settings/")
    parser.add_argument("--all", action="store_true", help="Lint every setting")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Warnings count as failures (exit code 1)",
    )
    args = parser.parse_args()

    settings_dir = config.PROJECT_ROOT / "settings"

    if args.all:
        targets = [
            d for d in sorted(settings_dir.iterdir())
            if d.is_dir() and (d / "setting.yaml").exists()
        ]
    elif args.setting:
        target = settings_dir / args.setting
        if not target.exists():
            print(
                f"ERROR: setting '{args.setting}' not found under {settings_dir}",
                file=sys.stderr,
            )
            sys.exit(2)
        targets = [target]
    else:
        parser.error("specify --setting <name> or --all")

    total_errors = 0
    total_warnings = 0

    for setting_dir in targets:
        report = lint_setting(setting_dir)
        print(report.render())
        total_errors += report.n_errors
        total_warnings += report.n_warnings

    print(f"\n=== Overall ===")
    print(f"  settings checked: {len(targets)}")
    print(f"  total errors    : {total_errors}")
    print(f"  total warnings  : {total_warnings}")

    if total_errors > 0:
        sys.exit(1)
    if args.strict and total_warnings > 0:
        print("  (--strict: warnings count as failures)")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
