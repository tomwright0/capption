import pytest

from capption.asr import models


def _fake_snapshot(root, repo, complete=True):
    snap = root / f"models--{repo.replace('/', '--')}" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    if complete:
        (snap / "model.bin").write_bytes(b"x")
    return snap


def test_repo_ids():
    assert models.repo_id_for("large-v3-turbo") == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
    assert models.repo_id_for("org/custom") == "org/custom"
    with pytest.raises(ValueError):
        models.repo_id_for("nope")


def test_downloaded_requires_complete_snapshot(tmp_path):
    _fake_snapshot(tmp_path, "Systran/faster-whisper-tiny", complete=False)
    assert not models.is_downloaded("tiny", tmp_path)
    assert models.local_path("tiny", tmp_path) is None
    (tmp_path / "models--Systran--faster-whisper-tiny" / "snapshots" / "abc" / "model.bin").write_bytes(b"x")
    assert models.is_downloaded("tiny", tmp_path)
    assert models.local_path("tiny", tmp_path).endswith("abc")


def test_delete(tmp_path):
    _fake_snapshot(tmp_path, "org/custom")
    models.delete("org/custom", tmp_path)
    assert not models.is_downloaded("org/custom", tmp_path)
    models.delete("org/custom", tmp_path)  # idempotent


def test_transfer_rate():
    from capption.asr.models import TransferRate

    r = TransferRate(window_s=2.0)
    assert r.add(0.0, 0) is None
    assert r.add(0.2, 1_000) is None  # too early
    assert r.add(1.0, 10_000) == 10_000
    # Old samples drop out of the window: only the recent 20 kB/s counts.
    r.add(2.0, 20_000)
    r.add(3.0, 40_000)
    assert r.add(4.0, 60_000) == 20_000
    # Restart (resume from scratch) resets the history.
    assert r.add(5.0, 0) is None
