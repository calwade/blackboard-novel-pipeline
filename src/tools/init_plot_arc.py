"""init_plot_arc — 给作品生成 plot_arc.yaml 模板（作者自填）.

行为：
  1. 读 projects/<id>/project.yaml 拿 chapter_count_target（默认 50）
  2. 按 4 卷等分（如 50 章 → 12/13/12/13）写一个骨架 plot_arc.yaml
  3. 文件已存在 → 不覆盖，只 print 警告
  4. 提示作者编辑 ultimate_goal / 各 act.goal / must_close_by_end

不包含交互式向导——模板生成后让作者用编辑器填字段（Oracle 倾向）。

用法:
    python -m src.tools.init_plot_arc <project_id>

完成后:
    python -m src.bootstrap --project <project_id>   # 同步到 state/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .. import config


def _split_chapters(total: int, n_acts: int) -> list[tuple[int, int]]:
    """把 1..total 等分成 n_acts 段（含两端）。多余的余数从前往后多分 1。"""
    base = total // n_acts
    extra = total % n_acts
    ranges: list[tuple[int, int]] = []
    cursor = 1
    for i in range(n_acts):
        size = base + (1 if i < extra else 0)
        ranges.append((cursor, cursor + size - 1))
        cursor += size
    return ranges


def _build_template(total: int) -> dict:
    """4 卷骨架。每卷 name 留作者填，goal/must_close_by_end 给空占位。"""
    n_acts = 4 if total >= 4 else max(1, total)
    splits = _split_chapters(total, n_acts)
    default_names = ["卷一", "卷二", "卷三", "终卷"]
    acts = []
    for i, (s, e) in enumerate(splits):
        acts.append(
            {
                "name": default_names[i] if i < len(default_names) else f"卷{i+1}",
                "range": [s, e],
                "goal": "（TODO: 填本卷主线目标——主角要完成什么 / 解决什么核心冲突）\n",
                "must_open_by_ch": [s] if i == 0 else [],
                "must_close_by_end": [
                    "（TODO: 卷末必须收束的伏笔/真相 1）",
                    "（TODO: 卷末必须收束的伏笔/真相 2）",
                ],
            }
        )
    return {
        "schema_version": 1,
        "total_chapters": total,
        "ultimate_goal": (
            "（TODO: 主角的终极目标 / 故事核心驱动力。1-3 句话。\n"
            "  Planner 每章会把这段当作全书坐标系的灯塔。）\n"
        ),
        "acts": acts,
    }


def _dump_yaml(data: dict) -> str:
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def init_plot_arc(project_id: str, *, force: bool = False) -> Path:
    """Create plot_arc.yaml template under projects/<id>/.

    Returns the file path. Raises FileNotFoundError if project doesn't exist.
    Raises FileExistsError if plot_arc.yaml exists and force=False.
    """
    project_dir = config.PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise FileNotFoundError(f"project not found: {project_dir}")

    project_yaml_path = project_dir / "project.yaml"
    total = 50
    if project_yaml_path.exists():
        try:
            data = yaml.safe_load(project_yaml_path.read_text(encoding="utf-8")) or {}
            t = data.get("chapter_count_target")
            if isinstance(t, int) and t > 0:
                total = t
        except Exception:
            pass

    target = project_dir / "plot_arc.yaml"
    if target.exists() and not force:
        raise FileExistsError(f"plot_arc.yaml already exists: {target}")

    template = _build_template(total)
    body = (
        "# Novelforge 全书坐标系 (Plot Arc) — 作者自填模板\n"
        "# 详见 src/tools/plot_arc.py / AGENTS.md\n"
        "#\n"
        "# 修改本文件后请重新跑：python -m src.bootstrap --project "
        f"{project_id}\n"
        "# 让 state/plot_arc.yaml 同步。\n\n"
    ) + _dump_yaml(template)
    target.write_text(body, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成 plot_arc.yaml 模板（全书坐标系）"
    )
    parser.add_argument("project_id", help="作品 id（projects/<id>/）")
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的 plot_arc.yaml（默认拒绝覆盖）",
    )
    args = parser.parse_args()

    try:
        path = init_plot_arc(args.project_id, force=args.force)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except FileExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("  使用 --force 覆盖已存在文件。", file=sys.stderr)
        sys.exit(2)

    print(f"✓ 已生成 plot_arc.yaml 模板：{path}")
    print()
    print("接下来：")
    print(f"  1. 用编辑器打开 {path}")
    print("     填写 ultimate_goal、各 act 的 name/goal/must_close_by_end")
    print("  2. 重新 bootstrap 让 state/ 同步：")
    print(f"       python -m src.bootstrap --project {args.project_id}")
    print()
    print("Planner 之后每章都会带上全书坐标系上下文。")


if __name__ == "__main__":
    main()
