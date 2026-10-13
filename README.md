# Capption

Live captions for **one app's audio** on Windows. Pick Chrome, Discord, VLC or a game, and
Capption shows what's being said in a translucent always-on-top overlay. Everything runs
locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No cloud and no
account, and no audio leaves your PC.

## Why this exists

I wanted live captions (and translation) for audio from a single app. The existing options
didn't work for that:

- **Windows Live Captions / live translation** only listens to the **default output device**.
  The usual workaround is to send one app's audio to a virtual device like
  [VB-Audio Cable](https://vb-audio.com/Cable/) and caption that. It doesn't work, because Live
  Captions ignores any device that isn't the default. You can make the cable the default, but
  then every app plays into it and you can't hear anything without more routing.
- **[Buzz](https://github.com/chidiwilliams/buzz)** is great for transcribing files. Its live
  mode, though, feels clunky and dated. It wasn't something I wanted on screen all day.

Capption uses Windows' **process loopback** capture (the API behind per-app recording). It
records the audio of the app you choose, including its child processes, straight from that
app. It doesn't matter which device the app plays on. You keep hearing everything normally,
with no virtual cables, no changing the default device and no routing.

## Features

- Captures a single application (and its child processes, such as Chrome's audio service).
- Streaming captions: words appear grey while they may still change, then turn white once
  confirmed. They are typically under a second behind the speech.
- Translation to English (Whisper's translate mode) for any language Whisper supports.
- GPU-accelerated with NVIDIA CUDA (float16), with automatic fallback to CPU, including if the
  GPU runs out of memory mid-session.
- Overlay: frameless, draggable, resizable, snaps to screen edges, and remembers its position
  per monitor. Click-through mode lets you click the window underneath.
- Reattaches automatically when the captioned app restarts, and on launch auto-starts with the
  app you used last.
- Global hotkeys, a tray icon, and optional `.txt` / `.srt` transcripts for each session.
- Model manager: download, delete, or add any CTranslate2 Whisper model from Hugging Face.
  Downloads show percentage, speed and time left.

## Requirements

- **Windows 10 build 20348+ or Windows 11** (process loopback). If it's unavailable, Capption
  says so and lets you pick an input device instead, e.g. VB-Cable "CABLE Output".
- **NVIDIA GPU recommended** (driver 570+ for RTX 50-series). CPU works with smaller models.
  `large-v3-turbo` uses about 1 GB of VRAM and runs about 12x faster than real time on an
  RTX 5070.
- About 1 GB of disk for the app, plus the model you choose (75 MB to 1.6 GB).

## Install

Download `Capption-<version>-win64.zip` from
[Releases](https://github.com/tomwright0/capption/releases), unzip it anywhere, and run
`Capption.exe`. Builds from `main` are also available as artifacts on the
[Actions](https://github.com/tomwright0/capption/actions) tab.

On first start, open **Models** and download one:

| Model | Size | Notes |
|---|---|---|
| `large-v3-turbo` | 1.6 GB | Best accuracy/speed on a GPU. Weak at translation. |
| `distil-large-v3` | 1.5 GB | English only, very fast. |
| `medium` | 1.5 GB | Multilingual, good for translation. |
| `small` | 484 MB | Fine on a CPU. |
| `tiny` | 76 MB | Fastest, lowest accuracy. |

Models are stored in `%LOCALAPPDATA%\Capption\models`. Settings are in `%APPDATA%\Capption`.

## Usage

1. Start playing something in the app you want captioned.
2. In **Captions**, pick it from **Application**. Apps currently making sound are listed first.
3. Press **Start captions**. Drag the overlay where you want it.

Default hotkeys (change them under **Hotkeys**):

| Action | Hotkey |
|---|---|
| Start / stop captions | `Ctrl+Alt+C` |
| Toggle click-through | `Ctrl+Alt+T` |
| Show / hide overlay | `Ctrl+Alt+H` |

Closing the window keeps Capption running in the tray. To exit, use **Quit** from the tray menu.

## Build from source

Needs Python 3.12 and Visual Studio Build Tools (C++ workload, which includes CMake).

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-windows.txt -r requirements-dev.txt

# Native capture helper (from a Developer PowerShell, or use the cmake bundled with Build Tools)
cmake -S native/loopback -B native/loopback/build -A x64
cmake --build native/loopback/build --config Release

.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m capption                 # run the app
.venv\Scripts\pyinstaller capption.spec --noconfirm   # -> dist\Capption\Capption.exe
```

Console tools for testing without the UI:

```powershell
python -m capption.cli record --pid <PID> --out test.wav --seconds 10
python -m capption.cli transcribe --pid <PID> --model large-v3-turbo
python -m capption.cli transcribe --file talk.mp4 --model small
```

### How it works

- `native/loopback/` is a small C++ helper (`capption-loopback.exe`). It opens a WASAPI
  process-loopback stream for one process tree and writes float32 PCM to stdout. Keeping COM
  audio in a separate process means a driver hiccup can't take down the UI.
- `capption/asr/` holds the processing pipeline:
  - Audio is resampled to 16 kHz.
  - Silero VAD splits it into speech segments.
  - Whisper re-transcribes a rolling buffer about every 0.5 s.
  - LocalAgreement-2 confirms words once two passes agree.
- `capption/ui/` is the PySide6 interface (settings window, overlay and tray).

## Troubleshooting

- **"Process loopback unavailable"**: your Windows build is too old. Pick an input device
  instead (e.g. VB-Cable "CABLE Output") and route the app's audio to "CABLE Input".
- **An app isn't listed**: it only appears once it has opened an audio stream. Play something,
  then press the refresh button.
- **Runs on CPU even though you have an NVIDIA GPU**: update the driver (570+ for RTX 50-series).
  The reason for the fallback is shown in the status line and in
  `%LOCALAPPDATA%\Capption\logs\capption.log`.
- **Odd phrases like "Captions by …" appear briefly**: this is a known Whisper hallucination on
  silence or cut-off audio. It usually disappears before the words are confirmed. Setting the
  language explicitly instead of Auto-detect helps.
- **A hotkey doesn't work**: another program already uses that combination. Pick a different
  one under **Hotkeys**.
