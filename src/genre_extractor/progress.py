"""Progress callback 协议，供 genre extractor 上报子步骤粒度。

统一签名：

    on_progress(
        phase: str | None = None,           # "extract" | "merge" | "draft" | "validate"
        phase_index: int | None = None,     # 1..4
        sub_steps: dict | None = None,      # {"batch_cur": 3, "batch_total": 12} 等
        progress_text: str | None = None,   # 人类可读的一行描述
    )

web 层 `jobs.py::_run_worker` 实现一个会写 JobStore + JobLogger 的回调；
CLI / 测试可以传 ``null_progress`` 或省略。
"""
from __future__ import annotations

from typing import Callable, Protocol


class ProgressCallback(Protocol):
    def __call__(
        self,
        *,
        phase: str | None = None,
        phase_index: int | None = None,
        sub_steps: dict | None = None,
        progress_text: str | None = None,
    ) -> None: ...


def null_progress(**_: object) -> None:
    """No-op 回调，供不关心进度的调用方使用。"""
    pass


# Phase → phase_index 映射（1-based，与 plan / JobStore schema 对齐）
PHASE_INDEX = {
    "extract": 1,
    "merge": 2,
    "draft": 3,
    "validate": 4,
}
