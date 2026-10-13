# PyInstaller spec for the Windows build (onedir, windowed).
#
#   native\loopback build first (CMake), then:
#   .venv\Scripts\pyinstaller capption.spec --noconfirm
#
# Output: dist\Capption\Capption.exe. Builds fine on a GPU-less machine: the CUDA DLLs come
# from the nvidia-*-cu12 wheels and are only loaded at runtime.

import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH)
HELPER = ROOT / "native" / "loopback" / "build" / "Release" / "capption-loopback.exe"
if not HELPER.is_file():
    sys.exit(f"Missing {HELPER}; build native/loopback first.")

# Exe icon rendered from the in-code icon (capption/ui/icon.py); the installer uses it too.
ICON = ROOT / "build" / "capption.ico"
subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py"), str(ICON)], check=True)


def nvidia_dlls():
    """cuBLAS + cudart for ctranslate2, kept at nvidia/<pkg>/bin like the wheels. PyInstaller's
    dependency scan copies cublasLt there anyway, so any other location would duplicate 640 MB.
    asr/engine.py:add_cuda_dll_dirs adds these dirs at runtime. nvrtc is pulled in by the
    cuBLAS wheel but ctranslate2 doesn't use it."""
    import nvidia

    wanted = {"cublas64_12.dll", "cublasLt64_12.dll", "cudart64_12.dll"}
    found = [
        (str(p), f"nvidia/{p.parent.parent.name}/bin")
        for root in nvidia.__path__
        for p in Path(root).glob("*/bin/*.dll")
        if p.name in wanted
    ]
    missing = wanted - {Path(src).name for src, _ in found}
    if missing:
        sys.exit(f"Missing CUDA DLLs {sorted(missing)}; install requirements-windows.txt")
    return found


datas = [
    (str(ROOT / "capption" / "assets"), "capption/assets"),
    *collect_data_files("faster_whisper"),  # silero_vad_v6.onnx
]
binaries = [
    (str(HELPER), "."),
    *nvidia_dlls(),
    *collect_dynamic_libs("ctranslate2"),
]

a = Analysis(
    [str(ROOT / "capption" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["capption.platform.windows", "capption.capture.win_loopback"],
    excludes=["tkinter", "torch", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Capption",
    console=False,
    icon=str(ICON),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Capption", upx=False)
