"""File + console logging. Log files live under <data dir>/logs."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading

from .config import logs_dir

FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def setup_logging(console_level: int = logging.WARNING) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(console)

    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
        file = logging.handlers.RotatingFileHandler(
            logs_dir() / "capption.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file.setLevel(logging.DEBUG)
        file.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(file)
    except OSError as exc:
        root.warning("File logging unavailable: %s", exc)

    for noisy in ("faster_whisper", "httpx", "urllib3", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.INFO)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("thread").error(
            "Unhandled exception in %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = thread_hook
