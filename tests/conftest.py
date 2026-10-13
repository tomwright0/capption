import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="Windows-only")
    for item in items:
        if "windows" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def speech_wav() -> Path:
    return FIXTURES / "speech.wav"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    # Never touch the real %APPDATA% / Library during tests.
    monkeypatch.setenv("CAPPTION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CAPPTION_DATA_DIR", str(tmp_path / "data"))
