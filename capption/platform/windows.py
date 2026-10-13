"""Windows implementation: audio sessions via comtypes, process loopback via the native
helper, global hotkeys via RegisterHotKey, click-through via WS_EX_TRANSPARENT."""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass

import comtypes
import psutil
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

from ..capture.base import AudioSource, SourceInfo
from ..capture.device_source import DeviceSource, list_input_devices
from ..capture.file_source import FileSource
from ..capture import win_loopback
from ..config import AppConfig
from .base import CaptureSupport, HotkeyManager, Platform

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Core Audio interfaces (only the methods we call need correct signatures, but every
# vtable slot before them must be declared in order).


class IAudioSessionControl(IUnknown):
    _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetState", (["out"], ctypes.POINTER(ctypes.c_int), "state")),
        COMMETHOD([], HRESULT, "GetDisplayName", (["out"], ctypes.POINTER(wintypes.LPWSTR), "name")),
        COMMETHOD([], HRESULT, "SetDisplayName", (["in"], wintypes.LPCWSTR), (["in"], ctypes.POINTER(GUID))),
        COMMETHOD([], HRESULT, "GetIconPath", (["out"], ctypes.POINTER(wintypes.LPWSTR))),
        COMMETHOD([], HRESULT, "SetIconPath", (["in"], wintypes.LPCWSTR), (["in"], ctypes.POINTER(GUID))),
        COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], ctypes.POINTER(GUID))),
        COMMETHOD([], HRESULT, "SetGroupingParam", (["in"], ctypes.POINTER(GUID)), (["in"], ctypes.POINTER(GUID))),
        COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (["in"], ctypes.c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (["in"], ctypes.c_void_p)),
    ]


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], ctypes.POINTER(wintypes.LPWSTR))),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (["out"], ctypes.POINTER(wintypes.LPWSTR))),
        COMMETHOD([], HRESULT, "GetProcessId", (["out"], ctypes.POINTER(wintypes.DWORD), "pid")),
        COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
        COMMETHOD([], HRESULT, "SetDuckingPreference", (["in"], wintypes.BOOL)),
    ]


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(ctypes.c_int), "count")),
        COMMETHOD([], HRESULT, "GetSession", (["in"], ctypes.c_int, "index"),
                  (["out"], ctypes.POINTER(ctypes.POINTER(IAudioSessionControl)), "session")),
    ]


class IAudioSessionManager2(IUnknown):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = [
        # IAudioSessionManager
        COMMETHOD([], HRESULT, "GetAudioSessionControl", (["in"], ctypes.c_void_p), (["in"], wintypes.DWORD),
                  (["out"], ctypes.POINTER(ctypes.c_void_p))),
        COMMETHOD([], HRESULT, "GetSimpleAudioVolume", (["in"], ctypes.c_void_p), (["in"], wintypes.DWORD),
                  (["out"], ctypes.POINTER(ctypes.c_void_p))),
        # IAudioSessionManager2
        COMMETHOD([], HRESULT, "GetSessionEnumerator",
                  (["out"], ctypes.POINTER(ctypes.POINTER(IAudioSessionEnumerator)), "enum")),
        COMMETHOD([], HRESULT, "RegisterSessionNotification", (["in"], ctypes.c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterSessionNotification", (["in"], ctypes.c_void_p)),
        COMMETHOD([], HRESULT, "RegisterDuckNotification", (["in"], wintypes.LPCWSTR), (["in"], ctypes.c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterDuckNotification", (["in"], ctypes.c_void_p)),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], ctypes.POINTER(GUID), "iid"), (["in"], wintypes.DWORD, "ctx"),
                  (["in"], ctypes.c_void_p, "params"), (["out"], ctypes.POINTER(ctypes.c_void_p), "iface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], wintypes.DWORD), (["out"], ctypes.POINTER(ctypes.c_void_p))),
        COMMETHOD([], HRESULT, "GetId", (["out"], ctypes.POINTER(wintypes.LPWSTR))),
        COMMETHOD([], HRESULT, "GetState", (["out"], ctypes.POINTER(wintypes.DWORD))),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(ctypes.c_uint), "count")),
        COMMETHOD([], HRESULT, "Item", (["in"], ctypes.c_uint, "index"),
                  (["out"], ctypes.POINTER(ctypes.POINTER(IMMDevice)), "device")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], ctypes.c_int, "flow"), (["in"], wintypes.DWORD, "mask"),
                  (["out"], ctypes.POINTER(ctypes.POINTER(IMMDeviceCollection)), "devices")),
    ]


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
E_RENDER = 0
DEVICE_STATE_ACTIVE = 1
SESSION_STATE_ACTIVE = 1
CLSCTX_ALL = 23


@dataclass(frozen=True)
class AudioSession:
    pid: int
    active: bool
    display_name: str


def enumerate_sessions() -> list[AudioSession]:
    """Audio sessions on every active render endpoint (system sounds excluded)."""
    comtypes.CoInitialize()  # no-op if this thread is already initialized
    enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_ALL)
    devices = enumerator.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE)
    out: list[AudioSession] = []
    for i in range(devices.GetCount()):
        try:
            device = devices.Item(i)
            ptr = device.Activate(ctypes.byref(IAudioSessionManager2._iid_), CLSCTX_ALL, None)
            manager = ctypes.cast(ptr, ctypes.POINTER(IAudioSessionManager2))
            sessions = manager.GetSessionEnumerator()
            for j in range(sessions.GetCount()):
                ctl = sessions.GetSession(j).QueryInterface(IAudioSessionControl2)
                if ctl.IsSystemSoundsSession() == 0:  # S_OK means "is system sounds"
                    continue
                pid = ctl.GetProcessId()
                if not pid:
                    continue
                out.append(AudioSession(pid, ctl.GetState() == SESSION_STATE_ACTIVE, ctl.GetDisplayName() or ""))
        except (OSError, comtypes.COMError):
            log.debug("Skipping render endpoint %d", i, exc_info=True)
    return out


# --------------------------------------------------------------------------------------
# Processes


def _file_description(path: str) -> str | None:
    """FileDescription from the exe's version resource, e.g. "Google Chrome"."""
    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buf):
        return None
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(length)):
        return None
    if length.value < 4:
        return None
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
    key = rf"\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription"
    if not version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)) or length.value <= 1:
        return None
    return ctypes.wstring_at(ptr.value, length.value - 1).strip() or None


def _root_of(proc: psutil.Process) -> psutil.Process:
    """Topmost ancestor with the same exe name (chrome's audio service -> the browser)."""
    name = proc.name().lower()
    root = proc
    try:
        for parent in proc.parents():
            if parent.name().lower() != name:
                break
            root = parent
    except psutil.Error:
        pass
    return root


def _source_for(proc: psutil.Process, session_name: str = "") -> SourceInfo | None:
    try:
        name = proc.name()
        exe = proc.exe()
    except psutil.Error:
        return None
    label = (_file_description(exe) if exe else None) or session_name or os.path.splitext(name)[0]
    return SourceInfo(key=name.lower(), label=label, kind="process", pid=proc.pid, exe_path=exe or None)


def audio_apps() -> list[tuple[SourceInfo, bool]]:
    """One entry per app (process-tree root) with an audio session, and whether it is playing."""
    own = os.getpid()
    by_root: dict[int, tuple[SourceInfo, bool]] = {}
    try:
        sessions = enumerate_sessions()
    except (OSError, comtypes.COMError):
        log.exception("Audio session enumeration failed")
        return []
    for s in sessions:
        if s.pid == own:
            continue
        try:
            root = _root_of(psutil.Process(s.pid))
        except psutil.Error:
            continue
        prev = by_root.get(root.pid)
        if prev is not None:
            by_root[root.pid] = (prev[0], prev[1] or s.active)
            continue
        info = _source_for(root, s.display_name)
        if info is not None:
            by_root[root.pid] = (info, s.active)
    return list(by_root.values())


# --------------------------------------------------------------------------------------
# Hotkeys

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20

_SPECIAL_VK = {
    Qt.Key.Key_Space: 0x20, Qt.Key.Key_Return: 0x0D, Qt.Key.Key_Enter: 0x0D, Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Backspace: 0x08, Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23, Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26, Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Pause: 0x13, Qt.Key.Key_Print: 0x2C,
    Qt.Key.Key_Comma: 0xBC, Qt.Key.Key_Period: 0xBE, Qt.Key.Key_Minus: 0xBD, Qt.Key.Key_Equal: 0xBB,
    Qt.Key.Key_Semicolon: 0xBA, Qt.Key.Key_Slash: 0xBF, Qt.Key.Key_BracketLeft: 0xDB,
    Qt.Key.Key_BracketRight: 0xDD, Qt.Key.Key_Backslash: 0xDC, Qt.Key.Key_Apostrophe: 0xDE,
    Qt.Key.Key_QuoteLeft: 0xC0,
}


def sequence_to_vk(sequence: str) -> tuple[int, int] | None:
    """QKeySequence text -> (MOD_* flags, virtual-key code); None if unmappable."""
    seq = QKeySequence(sequence)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key, mods = combo.key(), combo.keyboardModifiers()
    flags = MOD_NOREPEAT
    if mods & Qt.KeyboardModifier.ControlModifier:
        flags |= MOD_CONTROL
    if mods & Qt.KeyboardModifier.AltModifier:
        flags |= MOD_ALT
    if mods & Qt.KeyboardModifier.ShiftModifier:
        flags |= MOD_SHIFT
    if mods & Qt.KeyboardModifier.MetaModifier:
        flags |= MOD_WIN
    k = key.value if hasattr(key, "value") else int(key)
    if Qt.Key.Key_A.value <= k <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= k <= Qt.Key.Key_9.value:
        return flags, k  # Qt uses ASCII codes here, same as the VK codes
    if Qt.Key.Key_F1.value <= k <= Qt.Key.Key_F24.value:
        return flags, 0x70 + k - Qt.Key.Key_F1.value
    vk = _SPECIAL_VK.get(key)
    return (flags, vk) if vk is not None else None


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._on_hotkey(int(msg.wParam))
                return True, 0
        return False, 0


class WinHotkeys(HotkeyManager):
    """System-wide hotkeys. RegisterHotKey with no window posts WM_HOTKEY to the GUI
    thread's queue, which Qt hands to native event filters."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._actions: dict[int, str] = {}
        self._next_id = 1
        self._filter = _HotkeyFilter(self._fire)
        QCoreApplication.instance().installNativeEventFilter(self._filter)

    def _fire(self, hotkey_id: int) -> None:
        action = self._actions.get(hotkey_id)
        if action:
            self.activated.emit(action)

    def register(self, action: str, sequence: str) -> bool:
        mapped = sequence_to_vk(sequence) if sequence else None
        if mapped is None:
            return False
        hotkey_id = self._next_id
        self._next_id += 1
        if not user32.RegisterHotKey(None, hotkey_id, *mapped):
            log.warning("RegisterHotKey failed for %s (%s): error %d", action, sequence, ctypes.get_last_error())
            return False
        self._actions[hotkey_id] = action
        return True

    def unregister_all(self) -> None:
        for hotkey_id in self._actions:
            user32.UnregisterHotKey(None, hotkey_id)
        self._actions.clear()


# --------------------------------------------------------------------------------------


class WindowsPlatform(Platform):
    name = "windows"

    def capture_support(self) -> CaptureSupport:
        ok, message = win_loopback.probe()
        if not ok:
            message += " Pick an input device instead (e.g. VB-Cable \"CABLE Output\")."
        return CaptureSupport(ok, message)

    def list_sources(self, config: AppConfig) -> list[SourceInfo]:
        apps = audio_apps() if self.capture_support().process_loopback else []
        apps.sort(key=lambda a: (not a[1], a[0].label.lower()))
        return [info for info, _ in apps] + list_input_devices()

    def find_app(self, key: str) -> SourceInfo | None:
        key = key.lower()
        candidates = [info for info, _ in audio_apps() if info.key == key]
        if candidates:
            return candidates[0]
        # Not producing audio yet: attach to the root of a running instance anyway.
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == key:
                info = _source_for(_root_of(proc))
                if info is not None:
                    return info
        return None

    def create_source(self, info: SourceInfo, config: AppConfig) -> AudioSource:
        if info.kind == "device":
            return DeviceSource(info.key.removeprefix("device:"))
        if info.kind == "file":
            return FileSource(info.key.removeprefix("file:"), loop=True)
        if info.pid is None:
            raise ValueError(f"No process id for {info.label}")
        return win_loopback.LoopbackSource(info.pid)

    def set_click_through(self, widget: QWidget, enabled: bool) -> None:
        hwnd = int(widget.winId())
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def create_hotkeys(self, parent: QObject) -> HotkeyManager:
        return WinHotkeys(parent)
