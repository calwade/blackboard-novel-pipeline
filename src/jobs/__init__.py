"""Jobs 子系统：持久化长运行任务 + cancel token + rotating log."""
from __future__ import annotations

from src.jobs.cancel import (
    CancelToken,
    GenrePipelineAborted,
    NullCancelToken,
    ThreadEventToken,
)
from src.jobs.logger import get_job_logger, read_log_tail
from src.jobs.schema import (
    PHASE_ORDER,
    PHASE_TOTAL,
    TERMINAL_STATES,
    initial_job_record,
    new_job_id,
)
from src.jobs.store import JobStore, get_store

__all__ = [
    "CancelToken",
    "GenrePipelineAborted",
    "JobStore",
    "NullCancelToken",
    "PHASE_ORDER",
    "PHASE_TOTAL",
    "TERMINAL_STATES",
    "ThreadEventToken",
    "get_job_logger",
    "get_store",
    "initial_job_record",
    "new_job_id",
    "read_log_tail",
]
