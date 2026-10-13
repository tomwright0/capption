"""Console front-end for testing capture and ASR without the UI.

Examples::

    python -m capption.cli transcribe --file speech.mp4 --model small
    python -m capption.cli transcribe --device "MacBook Air Microphone"
    python -m capption.cli record --file speech.mp4 --out test.wav --seconds 10
    python -m capption.cli devices
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import wave

import numpy as np

from .asr.agreement import join_words
from .capture.base import TARGET_RATE, AudioSource, SourceEnd
from .config import models_dir
from .logging_setup import setup_logging

DIM, RESET, CLEAR = "\033[2m", "\033[0m", "\r\033[K"


def _make_source(args: argparse.Namespace) -> AudioSource:
    if args.file:
        from .capture.file_source import FileSource

        return FileSource(args.file, loop=args.loop, realtime=not args.fast)
    if args.pid:
        from .capture import win_loopback

        return win_loopback.LoopbackSource(args.pid)
    from .capture.device_source import DeviceSource

    return DeviceSource(args.device)


def _add_source_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--file", help="audio/video file to play through the pipeline")
    g.add_argument("--device", help="input device name (default input if omitted)")
    g.add_argument("--pid", type=int, help="Windows: capture this process tree via loopback")
    p.add_argument("--loop", action="store_true", help="loop the file")
    p.add_argument("--fast", action="store_true", help="feed the file faster than real time")


def cmd_devices(_args: argparse.Namespace) -> int:
    from .capture.device_source import list_input_devices

    for info in list_input_devices():
        print(info.label)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    source = _make_source(args)
    chunks: list[np.ndarray] = []
    done = threading.Event()
    source.start(chunks.append, lambda reason, detail: done.set())
    done.wait(args.seconds)
    source.stop()
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"Wrote {audio.size / TARGET_RATE:.1f}s to {args.out}")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    from .asr.engine import WhisperEngine
    from .asr.vad import SileroVad, VadSegmenter
    from .asr.worker import AsrWorker

    t0 = time.perf_counter()
    engine = WhisperEngine(
        args.model, device=args.device_type, download_root=str(models_dir()), translate=args.translate
    )
    print(f"Model {engine.info.model} on {engine.info.device}/{engine.info.compute_type} "
          f"in {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    if engine.info.fallback_reason:
        print(f"Note: {engine.info.fallback_reason}", file=sys.stderr)

    lock = threading.Lock()
    started = time.monotonic()

    def on_update(u) -> None:
        with lock:
            stamp = f"[{time.monotonic() - started:6.1f}s]"
            if u.committed:
                sys.stdout.write(f"{CLEAR}{stamp} {join_words(u.committed)}\n")
            if u.partial:
                sys.stdout.write(f"{CLEAR}{DIM}{stamp} … {join_words(u.partial)}{RESET}")
            if u.segment_end:
                sys.stdout.write(CLEAR)
            sys.stdout.flush()

    stats = {"rtf": [], "queue": 0.0}

    def on_metrics(m) -> None:
        if m.rtf:
            stats["rtf"].append(m.rtf)
        stats["queue"] = max(stats["queue"], m.queue_s)

    worker = AsrWorker(
        engine,
        VadSegmenter(SileroVad()),
        on_update,
        on_metrics,
        language=args.language,
        on_oom=lambda reason: (engine.fall_back_to_cpu(reason), True)[1],
    )
    done = threading.Event()

    def on_end(reason: SourceEnd, detail: str) -> None:
        if reason is not SourceEnd.STOPPED:
            print(f"\nSource ended: {reason.value} {detail}", file=sys.stderr)
        done.set()

    worker.start()
    source = _make_source(args)
    source.start(worker.push, on_end)
    try:
        while not done.wait(0.2):
            if args.seconds and time.monotonic() - started > args.seconds:
                break
    except KeyboardInterrupt:
        pass
    source.stop()
    worker.stop(timeout=60)
    rtf = stats["rtf"]
    if rtf:
        print(f"\nRTF mean {np.mean(rtf):.2f} / max {np.max(rtf):.2f}, "
              f"max queue {stats['queue']:.2f}s, dropped {worker.metrics.dropped_s:.1f}s", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capption-cli")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list input devices").set_defaults(fn=cmd_devices)

    rec = sub.add_parser("record", help="capture to a 16 kHz mono WAV")
    _add_source_args(rec)
    rec.add_argument("--out", default="capture.wav")
    rec.add_argument("--seconds", type=float, default=10.0)
    rec.set_defaults(fn=cmd_record)

    tr = sub.add_parser("transcribe", help="stream captions to the console")
    _add_source_args(tr)
    tr.add_argument("--model", default="small")
    tr.add_argument("--device-type", default="auto", choices=["auto", "cuda", "cpu"])
    tr.add_argument("--language", default=None, help="e.g. en; omit to auto-detect")
    tr.add_argument("--translate", action="store_true")
    tr.add_argument("--seconds", type=float, default=0.0, help="stop after N seconds (0 = until EOF/Ctrl+C)")
    tr.set_defaults(fn=cmd_transcribe)

    args = parser.parse_args(argv)
    setup_logging(console_level=logging.DEBUG if args.verbose else logging.WARNING)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
