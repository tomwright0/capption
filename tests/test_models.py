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
