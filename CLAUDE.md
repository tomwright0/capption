# Capption

Local, real-time speech-to-text captions for audio from ONE selected Windows application
(e.g. chrome.exe), shown in a translucent always-on-top overlay. No cloud APIs.
Python 3.12, PySide6 UI, faster-whisper (CTranslate2) ASR, packaged with PyInstaller.

Originally specified as "Captioner"; renamed **Capption** (package `capption/`, data in
`%APPDATA%\Capption` (config) and `%LOCALAPPDATA%\Capption` (models, logs, transcripts),
env overrides `CAPPTION_CONFIG_DIR` / `CAPPTION_DATA_DIR`).

## Target machine
- Windows IoT Enterprise **LTSC 2024** (build 26100): WASAPI process loopback is supported.
- RTX 5070 (Blackwell, sm_120). Driver must be >= 570.
- Development started on a MacBook (macOS dev implementation exists); work now continues on Windows.
- User is sometimes on a metered/slow connection: state sizes and ask before downloading
  big models (large-v3-turbo ~1.6 GB). `tiny` (~75 MB) is enough for pipeline testing.

## Decisions (agreed with user)
- **Process loopback via a small C++ helper exe** (`native/loopback/`, not yet written), not comtypes.
  It uses `ActivateAudioInterfaceAsync` with `AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` and
  `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`, takes `--pid N`, and writes float32 PCM to
  stdout. Python spawns it and reads the pipe. Reasons: COM completion handlers + IAgileObject +
  PROPVARIANT blobs are fragile in comtypes; process isolation means a COM crash can't kill the UI;
  no Python-ABI coupling. Exit codes report target-exited / unsupported / device-lost.
  Follow Microsoft's ApplicationLoopback sample. Built by CMake/MSVC in CI.
- Don't trust the build number alone: try activation, and on failure fall back to an input device
  (e.g. VB-Cable "CABLE Output") via `DeviceSource`, with a banner in the UI.
- Audio-session enumeration (IAudioSessionManager2) via comtypes in Python (no callbacks needed).
  App icons via Qt `QFileIconProvider` on the exe path; process info via psutil.
- VAD: Silero v6 ONNX file that faster-whisper already bundles, run via onnxruntime (no torch).
- ctranslate2 4.8.2 Windows wheel is built against CUDA 12.8 with `WITH_CUDNN=OFF`, so
  **cuDNN is not needed**; cuBLAS/cudart come from the `nvidia-*-cu12` pip wheels and are loaded
  dynamically (`asr/engine.py:add_cuda_dll_dirs`). INT8 is disabled on sm_120 upstream, so use
  float16 on GPU, int8 on CPU. Whether sm_120 gets native kernels or PTX JIT is unverified.
- Global hotkeys on Windows: `RegisterHotKey` via ctypes + Qt `QAbstractNativeEventFilter` for
  WM_HOTKEY (no extra dependency). Click-through: toggle `WS_EX_TRANSPARENT | WS_EX_LAYERED`.

## Layout
```
capption/
  config/      schema.py (dataclasses, tolerant from_dict), store.py (paths, atomic JSON save)
  capture/     base.py (AudioSource, SourceInfo, SourceEnd), resample.py (soxr -> 16 kHz mono f32),
               file_source.py (PyAV, real-time paced), device_source.py (sounddevice; WASAPI-only on Win)
               win_loopback.py  <-- TODO (spawns helper exe; referenced lazily by cli.py)
  platform/    base.py (Platform, HotkeyManager, CaptureSupport), mac.py (dev: demo apps play a file),
               __init__.py (dispatch; Windows imports only in windows.py)
               windows.py  <-- TODO (imported by platform.current() on win32 -> app won't start until written)
  asr/         vad.py (streaming Silero + VadSegmenter), agreement.py (LocalAgreement-2),
               streamer.py (rolling buffer, trim, per-segment language lock), engine.py (WhisperEngine,
               CUDA->CPU fallback, OOM), worker.py (inference thread, backlog drop, metrics),
               models.py (HF download w/ byte progress, status, delete, custom repo ids)
  transcript/  writer.py (.txt/.srt per session)
  captions.py  CaptionBuffer: confirmed + partial text for display (Qt-free)
  ui/          theme.py, caption_view.py (painter, scroll/fade), overlay.py (frameless, drag, edge
               resize, snap, per-monitor position), controller.py (session orchestration, reattach),
               main_window.py (Captions/Appearance/Models/Hotkeys/Advanced pages), tray.py, icon.py
  app.py       GUI entry (`python -m capption`)
  cli.py       `python -m capption.cli devices|record|transcribe` (console testing)
tests/         unit tests (run anywhere); tests/windows/ for @pytest.mark.windows (skipped off Windows)
```

## Status
- **Stage 1 (shared ASR pipeline): done and verified on macOS.** 34 unit tests pass. The CLI with the
  `tiny` model on `tests/fixtures/speech.wav` streams partials that lock into confirmed text,
  ~0.5-1 s behind the speech, RTF ~0.13 on M-series CPU.
  Real-model test: `CAPPTION_TEST_MODEL=tiny CAPPTION_TEST_MODEL_DIR=<models dir> pytest tests/test_pipeline_real.py`.
- **Stage 2 (UI): written, NOT yet run or visually checked.** Imports cleanly. Launch was blocked on
  the Mac by a Qt issue (PySide6 6.11.2 on macOS 27 (build 26A428): `QDir.entryList()` returned nothing for
  the plugin directory, so no platform plugin loaded). That's probably not relevant on Windows.
  First job on Windows: launch the UI, fix whatever breaks, and screenshot every page plus the overlay.
- **Stage 3 (Windows): not started.**

## Next steps (in order)
1. `capption/platform/windows.py`: session enumeration (comtypes), `find_app` by exe name,
   `capture_support()` (try loopback activation), RegisterHotKey manager, click-through.
   `list_sources` should list processes with active audio sessions first, then WASAPI input devices.
2. `native/loopback/` (CMakeLists.txt + main.cpp) and `capption/capture/win_loopback.py`.
   Test via `python -m capption.cli record --pid <chrome pid> --out test.wav`, then `transcribe --pid`.
3. Run the UI on Windows; fix layout and style issues (theme is Fusion + QSS, dark).
4. `capption.spec` (PyInstaller): include `capption/assets`, the faster_whisper assets (silero ONNX),
   the helper exe and nvidia DLLs. It must build on a GPU-less runner.
5. `.github/workflows/build.yml` on windows-latest: install requirements-windows + dev, pytest,
   build the helper with CMake, build with PyInstaller, upload the artifact on push/tag.
6. README.md (setup, build, troubleshooting) and WINDOWS_TESTING.md (manual checklist: loopback on
   LTSC 2024, CUDA on the 5070, click-through, hotkeys, tray, reattach on app restart, OOM fallback).

## Commands
```
# Windows setup
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-windows.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m capption.cli transcribe --file tests\fixtures\speech.wav --model tiny
.venv\Scripts\python -m capption            # GUI
```
Requirements are split: `requirements-common.txt` (shared pins), `-windows.txt` (onnxruntime 1.31.0,
comtypes, nvidia cublas/cudart cu12), `-mac.txt` (onnxruntime 1.23.2), `-dev.txt` (pytest, pyinstaller).

## Conventions
- Keep Windows-only imports inside `platform/windows.py` / `capture/win_loopback.py`, so the app still
  launches on macOS.
- Typed, small modules. Cross-thread callbacks go back to the GUI via Qt signals (see controller.py).
- Unit-test platform-independent logic with fakes (see tests/test_streamer.py, test_worker.py).
- Never commit model weights (see .gitignore).
