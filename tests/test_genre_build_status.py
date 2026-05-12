"""build_status 读写 + 断点续跑。"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_update_phase_status(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, update_phase_status

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 100, "batch_size": 25}],
    )
    bb.write_yaml("build_status.yaml", status)

    update_phase_status(bb, phase="extract", status="in_progress")
    s2 = bb.read_yaml("build_status.yaml")
    assert s2["phases"]["extract"]["status"] == "in_progress"


def test_record_batch_done(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, record_batch_done

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 50, "batch_size": 10}],
    )
    bb.write_yaml("build_status.yaml", status)

    record_batch_done(bb, batch_id=1)
    record_batch_done(bb, batch_id=2)
    s = bb.read_yaml("build_status.yaml")
    assert s["phases"]["extract"]["batches_done"] == 2
    assert s["phases"]["extract"]["last_batch_id"] == 2


def test_next_batch_to_run(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, record_batch_done, next_batch_to_run

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 50, "batch_size": 10}],
    )
    bb.write_yaml("build_status.yaml", status)

    assert next_batch_to_run(bb) == 1
    record_batch_done(bb, batch_id=1)
    assert next_batch_to_run(bb) == 2
    record_batch_done(bb, batch_id=2)
    record_batch_done(bb, batch_id=3)
    record_batch_done(bb, batch_id=4)
    record_batch_done(bb, batch_id=5)
    assert next_batch_to_run(bb) is None  # all done


def test_set_in_flight(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, set_in_flight, clear_in_flight

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 100, "batch_size": 25}],
    )
    bb.write_yaml("build_status.yaml", status)

    set_in_flight(bb, agent="genre_extractor", batch_id=3)
    s = bb.read_yaml("build_status.yaml")
    assert s["in_flight"]["agent"] == "genre_extractor"
    assert s["in_flight"]["batch_id"] == 3

    clear_in_flight(bb)
    s = bb.read_yaml("build_status.yaml")
    assert s["in_flight"] is None


def test_update_phase_status_unknown_raises(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, update_phase_status

    bb = Blackboard(root=tmp_path)
    bb.write_yaml("build_status.yaml", make_initial_build_status(
        genre_id="demo", entry="new-genre", novel_sources=[],
    ))
    with pytest.raises(ValueError, match="unknown phase"):
        update_phase_status(bb, phase="nonexistent", status="done")
