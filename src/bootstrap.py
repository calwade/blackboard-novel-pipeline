"""Bootstrap — seed the blackboard from a Setting Pack.

Run:
    python -m src.bootstrap --setting <setting-name>

Copies files from `settings/<setting-name>/` into `state/`:
  - outline.json
  - timeline.yaml
  - characters.yaml
  - era.md
  - writing-style-extra.md
  - iron-laws-extra.md
  - setting.yaml  (metadata about the active setting)

Overwrites seed-ish files (idempotent).
Does NOT touch runtime files: chapters/, summaries/, fixes/, issues.jsonl,
debt.jsonl, prompts_log.jsonl. Those accumulate across runs.

Progress is reset to empty on every bootstrap (so switching setting starts clean).

Design rationale — see docs/superpowers/specs/2026-05-09-...
The repo's `src/` has NO knowledge of any specific genre. All domain content
(characters, era facts, style quirks, specialty iron laws) lives under
settings/<name>/ and gets pushed into state/ here.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .blackboard import Blackboard
from . import config


# Files that MUST exist in every Setting Pack.
SETTING_FILES = [
    "setting.yaml",
    "outline.json",
    "timeline.yaml",
    "characters.yaml",
    "era.md",
    "writing-style-extra.md",
    "iron-laws-extra.md",
]


def list_settings() -> list[str]:
    root = config.PROJECT_ROOT / "settings"
    if not root.exists():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "setting.yaml").exists()
    )


def validate_setting(setting_dir: Path) -> list[str]:
    """Return list of missing files. Empty list means setting is valid."""
    return [f for f in SETTING_FILES if not (setting_dir / f).exists()]


def empty_progress() -> dict:
    return {
        "current_chapter": 0,
        "completed_chapters": [],
        "in_flight": None,
        "last_update": None,
        "total_llm_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the blackboard from a Setting Pack"
    )
    parser.add_argument(
        "--setting",
        help="Setting pack name (directory under settings/). "
        "Run with --list to see available settings.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available settings and exit",
    )
    args = parser.parse_args()

    available = list_settings()

    if args.list:
        if not available:
            print("(no settings found under settings/)")
        else:
            for s in available:
                print(s)
        return

    if not args.setting:
        parser.error("--setting is required (or use --list to see available settings)")

    if args.setting == "list":
        # Friendly alias
        for s in available:
            print(s)
        return

    setting_dir = config.PROJECT_ROOT / "settings" / args.setting
    if not setting_dir.exists():
        print(
            f"ERROR: setting '{args.setting}' not found under settings/.\n"
            f"Available: {', '.join(available) or '(none)'}",
            file=sys.stderr,
        )
        sys.exit(2)

    missing = validate_setting(setting_dir)
    if missing:
        print(
            f"ERROR: setting '{args.setting}' is incomplete. Missing files:\n"
            + "\n".join(f"  - {f}" for f in missing),
            file=sys.stderr,
        )
        sys.exit(2)

    bb = Blackboard()
    print(f"Seeding blackboard at {bb.root}/ from settings/{args.setting}/ ...")

    # Copy each SETTING_FILES entry into state/
    for fname in SETTING_FILES:
        src = setting_dir / fname
        dst = bb.root / fname
        shutil.copy2(src, dst)
        size = src.stat().st_size
        print(f"  ✓ {fname}  ({size} B)")

    # Reset progress
    bb.write_json("progress.json", empty_progress())
    print("  ✓ progress.json (reset)")

    # Touch accumulating files (preserve if they exist)
    for f in ("issues.jsonl", "debt.jsonl"):
        p = bb._abs(f)
        if not p.exists():
            p.touch()
            print(f"  ✓ {f} (empty)")
        else:
            print(f"  · {f} (existing, preserved)")

    # Ensure runtime sub-dirs
    for sub in ("chapters", "summaries", "fixes"):
        (bb.root / sub).mkdir(exist_ok=True)

    # Final stamp in progress.json
    prog = bb.read_json("progress.json")
    prog["active_setting"] = args.setting
    prog["bootstrapped_at"] = datetime.now().isoformat(timespec="seconds")
    bb.write_json("progress.json", prog)

    print(f"\n✓ Active setting: {args.setting}")
    print(f"  Next: python -m src.pipeline --chapter 1")


if __name__ == "__main__":
    main()
