from __future__ import annotations

import os
import time
from pathlib import Path

from spec_test_pilot.memory.gam import GAMMemorySystem
from spec_test_pilot.qa_specialist_agent import QASpecialistAgent


def _touch_stale_tmp(path: Path, *, age_sec: float = 90000.0) -> Path:
    path.write_text("stale", encoding="utf-8")
    old_ts = time.time() - float(age_sec)
    os.utime(path, (old_ts, old_ts))
    return path


def test_gam_save_cleans_stale_atomic_tmp_files(
    tmp_path: Path
) -> None:
    storage_path = tmp_path / "gam_memory_pages.json"
    stale_tmp = _touch_stale_tmp(
        storage_path.with_name(f".{storage_path.name}.tmp.stale")
    )

    memory = GAMMemorySystem(
        use_vector_search=False,
        storage_path=str(storage_path),
        autosave=False,
    )
    memory.save()

    assert storage_path.exists()
    assert not stale_tmp.exists()


def test_qa_specialist_init_cleans_stale_atomic_tmp_files(
    tmp_path: Path
) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        "openapi: 3.0.3\ninfo:\n  title: Temp Cleanup API\n  version: v1\npaths: {}\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "agent_lightning_checkpoint.pt"
    learning_state_path = output_dir / "agent_lightning_checkpoint_learning_state.json"
    gam_storage_path = output_dir / "gam_memory_pages.json"

    stale_ckpt_tmp = _touch_stale_tmp(
        checkpoint_path.with_name(f".{checkpoint_path.name}.tmp.stale")
    )
    stale_state_tmp = _touch_stale_tmp(
        learning_state_path.with_name(f".{learning_state_path.name}.tmp.stale")
    )
    stale_gam_tmp = _touch_stale_tmp(
        gam_storage_path.with_name(f".{gam_storage_path.name}.tmp.stale")
    )

    _ = QASpecialistAgent(
        spec_path=str(spec_path),
        output_dir=str(output_dir),
        rl_checkpoint_path=str(checkpoint_path),
    )

    assert not stale_ckpt_tmp.exists()
    assert not stale_state_tmp.exists()
    assert not stale_gam_tmp.exists()


def test_learning_state_save_cleans_stale_tmp_files(
    tmp_path: Path
) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        "openapi: 3.0.3\ninfo:\n  title: Save Cleanup API\n  version: v1\npaths: {}\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out_save"
    output_dir.mkdir(parents=True, exist_ok=True)

    agent = QASpecialistAgent(
        spec_path=str(spec_path),
        output_dir=str(output_dir),
    )
    target = agent.learning_state_path
    stale_tmp = _touch_stale_tmp(target.with_name(f".{target.name}.tmp.stale"))

    agent._save_learning_state()

    assert target.exists()
    assert not stale_tmp.exists()
