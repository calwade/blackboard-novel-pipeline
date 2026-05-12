"""Setting lint — validate the structural completeness of a preset or project.

Two modes, mutually exclusive:
  --preset <id>   — check presets/<id>/ has genre.yaml + 3 required md files
                    (+ optional resource_schema.yaml, validated if present)
  --project <id>  — check projects/<id>/ has all required files + optional schema

Exit codes:
    0  no errors
    1  has errors
    2  target not found / arg error
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from src import config
from src.bootstrap import REQUIRED_PROJECT_FILES, OPTIONAL_PROJECT_FILES


PRESET_REQUIRED = ("genre.yaml", "era.md", "writing-style-extra.md", "iron-laws-extra.md")
PRESET_OPTIONAL = ("resource_schema.yaml",)


@dataclass
class LintIssue:
    level: Literal["ERROR", "WARNING", "INFO"]
    file: str
    message: str


@dataclass
class LintReport:
    target: str
    kind: Literal["preset", "project"]
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.level == "ERROR")

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.level == "WARNING")


def lint_preset(preset_id: str) -> LintReport:
    preset_dir = config.PRESETS_DIR / preset_id
    if not preset_dir.exists():
        raise FileNotFoundError(f"preset not found: {preset_id}")
    report = LintReport(target=preset_id, kind="preset")
    for fname in PRESET_REQUIRED:
        p = preset_dir / fname
        if not p.exists():
            report.issues.append(LintIssue(
                level="ERROR",
                file=f"presets/{preset_id}/{fname}",
                message=f"missing required file: {fname}",
            ))
    # optional schema — if present, must parse
    schema = preset_dir / "resource_schema.yaml"
    if schema.exists():
        try:
            yaml.safe_load(schema.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            report.issues.append(LintIssue(
                level="ERROR",
                file=f"presets/{preset_id}/resource_schema.yaml",
                message=f"invalid YAML: {exc}",
            ))
    # genre.yaml must parse
    gy = preset_dir / "genre.yaml"
    if gy.exists():
        try:
            data = yaml.safe_load(gy.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "id" not in data:
                report.issues.append(LintIssue(
                    level="ERROR",
                    file=f"presets/{preset_id}/genre.yaml",
                    message="genre.yaml must have an 'id' field",
                ))
        except yaml.YAMLError as exc:
            report.issues.append(LintIssue(
                level="ERROR",
                file=f"presets/{preset_id}/genre.yaml",
                message=f"invalid YAML: {exc}",
            ))
    return report


def lint_project(project_id: str) -> LintReport:
    project_dir = config.PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise FileNotFoundError(f"project not found: {project_id}")
    report = LintReport(target=project_id, kind="project")
    for fname in REQUIRED_PROJECT_FILES:
        p = project_dir / fname
        if not p.exists():
            report.issues.append(LintIssue(
                level="ERROR",
                file=f"projects/{project_id}/{fname}",
                message=f"missing required file: {fname}",
            ))
    # optional schema
    schema = project_dir / "resource_schema.yaml"
    if schema.exists():
        try:
            yaml.safe_load(schema.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            report.issues.append(LintIssue(
                level="ERROR",
                file=f"projects/{project_id}/resource_schema.yaml",
                message=f"invalid YAML: {exc}",
            ))
    # project.yaml must parse and have key fields
    py = project_dir / "project.yaml"
    if py.exists():
        try:
            data = yaml.safe_load(py.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            report.issues.append(LintIssue(
                level="ERROR",
                file=f"projects/{project_id}/project.yaml",
                message=f"invalid YAML: {exc}",
            ))
            data = {}
        for key in ("id", "display_name", "protagonist_name", "chapter_count_target"):
            if key not in data:
                report.issues.append(LintIssue(
                    level="ERROR",
                    file=f"projects/{project_id}/project.yaml",
                    message=f"missing required field: {key}",
                ))
    return report


# Back-compat alias: genre_extractor / legacy callers still import `lint_genre`.
# A "genre" under the new single-layer layout == a preset.
lint_genre = lint_preset


def _print_report(report: LintReport) -> None:
    head = f"=== {report.kind}/{report.target} ==="
    print(head)
    if not report.issues:
        print("  clean")
        return
    for issue in report.issues:
        print(f"  [{issue.level}] {issue.file}: {issue.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Novelforge setting lint")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--preset", metavar="ID")
    grp.add_argument("--project", metavar="ID")
    args = parser.parse_args()
    try:
        if args.preset:
            report = lint_preset(args.preset)
        else:
            report = lint_project(args.project)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_report(report)
    return 1 if report.n_errors else 0


if __name__ == "__main__":
    sys.exit(main())
