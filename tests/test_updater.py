import pytest

from capption import updater


def test_parse_version():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("0.2") == (0, 2, 0)
    assert updater.parse_version("v1.0.0-beta.1") == (1, 0, 0)
    assert updater.parse_version("v0.10.0") > updater.parse_version("v0.9.9")
    with pytest.raises(ValueError):
        updater.parse_version("latest")


def test_parse_release_picks_installer():
    data = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/x/y/releases/tag/v0.2.0",
        "assets": [
            {"name": "Capption-v0.2.0-win64.zip", "browser_download_url": "zip", "size": 1},
            {"name": "Capption-Setup-0.2.0.exe", "browser_download_url": "exe", "size": 42},
        ],
    }
    r = updater.parse_release(data)
    assert r.version == (0, 2, 0)
    assert r.installer_url == "exe" and r.installer_size == 42


def test_parse_release_without_installer():
    r = updater.parse_release({"tag_name": "v0.2.0", "assets": []})
    assert r.installer_url is None
    assert r.page_url == updater.RELEASES_PAGE


def test_newer_release(monkeypatch):
    release = updater.parse_release({"tag_name": "v0.2.0", "assets": []})
    monkeypatch.setattr(updater, "latest_release", lambda: release)
    assert updater.newer_release("0.1.0") is release
    assert updater.newer_release("0.2.0") is None
    assert updater.newer_release("0.3.0") is None
