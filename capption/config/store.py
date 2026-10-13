"""Config/data locations and JSON persistence."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from .schema import AppConfig

log = logging.getLogger(__name__)

APP_NAME = "Capption"


def config_dir() -> Path:
    """Roaming settings: %APPDATA%\\Capption on Windows."""
    if override := os.environ.get("CAPPTION_CONFIG_DIR"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    return Path.home() / "Library" / "Application Support" / APP_NAME


def data_dir() -> Path:
    """Machine-local bulk data (models, logs): %LOCALAPPDATA%\\Capption on Windows."""
    if override := os.environ.get("CAPPTION_DATA_DIR"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    return Path.home() / "Library" / "Application Support" / APP_NAME


def models_dir() -> Path:
    return data_dir() / "models"


def logs_dir() -> Path:
    return data_dir() / "logs"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "config.json"

    def load(self) -> AppConfig:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AppConfig()
        except (OSError, ValueError) as exc:
            # Keep the broken file for inspection instead of silently overwriting it.
            log.warning("Config unreadable (%s); using defaults", exc)
            try:
                self.path.replace(self.path.with_suffix(".json.bad"))
            except OSError:
                pass
            return AppConfig()
        return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write never leaves a truncated config.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(config.to_dict(), fh, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
