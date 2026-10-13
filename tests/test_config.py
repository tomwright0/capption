import json

from capption.config import AppConfig, ConfigStore


def test_defaults_when_missing(tmp_path):
    cfg = ConfigStore(tmp_path / "config.json").load()
    assert cfg.asr.model == "large-v3-turbo"
    assert cfg.overlay.max_lines == 3


def test_round_trip(tmp_path):
    store = ConfigStore(tmp_path / "c" / "config.json")
    cfg = AppConfig()
    cfg.asr.language = "de"
    cfg.capture.last_exe = "chrome.exe"
    cfg.overlay.positions["DISPLAY1"] = [10, 20]
    store.save(cfg)
    loaded = store.load()
    assert loaded == cfg


def test_unknown_and_bad_typed_keys_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "asr": {"model": "small", "beam_size": "five", "nonsense": 1},
        "overlay": {"font_size": 40, "background_opacity": 1},
        "extra": True,
    }))
    cfg = ConfigStore(path).load()
    assert cfg.asr.model == "small"
    assert cfg.asr.beam_size == 1  # wrong type -> default kept
    assert cfg.overlay.font_size == 40
    assert cfg.overlay.background_opacity == 1  # int accepted for float


def test_corrupt_file_is_preserved(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    cfg = ConfigStore(path).load()
    assert cfg == AppConfig()
    assert (tmp_path / "config.json.bad").exists()
