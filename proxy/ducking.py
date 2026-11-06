import ctypes
import os
import struct
from dataclasses import dataclass
from typing import Callable

import AppKit
import objc

from . import mac

DUCK_TO = 0.1
SYSTEM_OBJECT = 1
PLAYERS = {"com.spotify.client": "Spotify", "com.apple.Music": "Music"}
BROWSERS = ("com.google.Chrome", "com.apple.WebKit", "com.apple.Safari", "company.thebrowser",
            "org.mozilla.firefox", "com.brave.Browser", "com.microsoft.edgemac")

_core_audio = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
_toolbox = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")


class _Address(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


def _address(selector: str, scope: str = "glob") -> _Address:
    code = lambda s: struct.unpack(">I", s.encode())[0]
    return _Address(code(selector), code(scope), 0)


def _get(obj: int, selector: str, ctype, scope: str = "glob", lib=_core_audio):
    value, size = ctype(), ctypes.c_uint32(ctypes.sizeof(ctype))
    err = lib.AudioObjectGetPropertyData if lib is _core_audio else lib.AudioHardwareServiceGetPropertyData
    if err(obj, ctypes.byref(_address(selector, scope)), 0, None, ctypes.byref(size), ctypes.byref(value)):
        return None
    return value.value


def _get_ids(obj: int, selector: str) -> list[int]:
    addr, size = _address(selector), ctypes.c_uint32()
    if _core_audio.AudioObjectGetPropertyDataSize(obj, ctypes.byref(addr), 0, None, ctypes.byref(size)):
        return []
    ids = (ctypes.c_uint32 * (size.value // 4))()
    if _core_audio.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ids):
        return []
    return list(ids)


def output_device() -> int | None:
    return _get(SYSTEM_OBJECT, "dOut", ctypes.c_uint32)


def output_volume(device: int) -> float | None:
    return _get(device, "vmvc", ctypes.c_float, "outp", _toolbox)


def set_output_volume(device: int, volume: float) -> bool:
    value = ctypes.c_float(volume)
    return not _toolbox.AudioHardwareServiceSetPropertyData(
        device, ctypes.byref(_address("vmvc", "outp")), 0, None, ctypes.sizeof(value), ctypes.byref(value))


def output_muted(device: int) -> bool:
    return bool(_get(device, "mute", ctypes.c_uint32, "outp"))


def playing_bundles() -> set[str]:
    """Bundle ids of other processes currently sending audio to an output (macOS 14+)."""
    found = set()
    for process in _get_ids(SYSTEM_OBJECT, "prs#"):
        if _get(process, "ppid", ctypes.c_int32) == os.getpid() or not _get(process, "piro", ctypes.c_uint32):
            continue
        ref = _get(process, "pbid", ctypes.c_void_p)
        found.add(str(objc.objc_object(c_void_p=ref)) if ref else "")
    return found


def _running(bundle_id: str) -> bool:
    return bool(AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id))


def _pause_player(app: str) -> bool:
    script = (f'tell application "{app}"\nif player state is playing then\npause\nreturn "paused"\n'
              f'end if\nend tell\nreturn ""')
    return mac.applescript(script) == "paused"


@dataclass
class Duck:
    kind: str
    undo: Callable[[], None]


class Ducker:
    """Quiets whatever is playing while you talk. Lowers the output volume when the
    device has one; otherwise (audio interfaces with hardware knobs) pauses Spotify or
    Music, or sends play/pause when a browser is the one playing. Main thread only."""

    def __init__(self):
        self._duck: Duck | None = None
        playing_bundles()

    def duck(self):
        self.release()
        try:
            self._duck = self._lower_volume() or self._pause_playback()
        except Exception as e:
            print(f"  duck failed: {type(e).__name__}: {e}")

    def release(self, media_action: str | None = None) -> bool:
        """Returns True when playback was paused by the duck and is left paused, because
        the command itself was play or pause."""
        duck, self._duck = self._duck, None
        if duck is None:
            return False
        if duck.kind == "pause" and media_action in ("play", "pause"):
            return True
        try:
            duck.undo()
        except Exception as e:
            print(f"  unduck failed: {type(e).__name__}: {e}")
        return False

    def _lower_volume(self) -> Duck | None:
        device = output_device()
        volume = None if device is None else output_volume(device)
        if volume is None:
            return None
        if output_muted(device) or volume <= DUCK_TO or not set_output_volume(device, DUCK_TO):
            return Duck("volume", lambda: None)

        def undo():
            if abs((output_volume(device) or 0) - DUCK_TO) < 0.01:
                set_output_volume(device, volume)
        return Duck("volume", undo)

    def _pause_playback(self) -> Duck | None:
        playing = playing_bundles()
        for bundle_id, app in PLAYERS.items():
            if any(b.startswith(bundle_id) for b in playing) and _running(bundle_id) and _pause_player(app):
                return Duck("pause", lambda app=app: mac.applescript(f'tell application "{app}" to play'))
        if any(b.startswith(BROWSERS) for b in playing):
            mac.media_key(mac.NX_PLAY)
            return Duck("pause", lambda: mac.media_key(mac.NX_PLAY))
        return None
