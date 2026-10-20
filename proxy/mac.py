import os
import subprocess
import time
from dataclasses import dataclass
from functools import cache

import AppKit
import ApplicationServices as AX
import Quartz

KEY_V, KEY_W = 9, 13
NX_PLAY, NX_NEXT, NX_PREVIOUS = 16, 17, 18
CMD = Quartz.kCGEventFlagMaskCommand
OPT = Quartz.kCGEventFlagMaskAlternate


class MacError(RuntimeError):
    pass


@dataclass
class Context:
    app: str = ""
    selection: str = ""


def accessibility_trusted() -> bool:
    return bool(AX.AXIsProcessTrusted())


def request_accessibility():
    AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True})


@cache
def host_app_pid() -> int | None:
    pid = os.getpid()
    while pid > 1:
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None and app.activationPolicy() == AppKit.NSApplicationActivationPolicyRegular:
            return pid
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True)
        pid = int(out.stdout.strip() or 1)
    return None


def frontmost_app():
    return AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()


def _ax(element, attribute):
    err, value = AX.AXUIElementCopyAttributeValue(element, attribute, None)
    return value if err == AX.kAXErrorSuccess else None


def selected_text() -> str:
    if not accessibility_trusted():
        return ""
    focused = _ax(AX.AXUIElementCreateSystemWide(), AX.kAXFocusedUIElementAttribute)
    return (focused and _ax(focused, AX.kAXSelectedTextAttribute)) or ""


def capture_context() -> Context:
    app = frontmost_app()
    return Context(app.localizedName() if app else "", selected_text())


@cache
def _compiled(source: str):
    script = AppKit.NSAppleScript.alloc().initWithSource_(source)
    ok, err = script.compileAndReturnError_(None)
    if not ok:
        raise MacError(f"applescript compile: {err}")
    return script


def applescript(source: str) -> str | None:
    result, err = _compiled(source).executeAndReturnError_(None)
    if err:
        raise MacError(f"applescript: {err.get('NSAppleScriptErrorMessage', err)}")
    return result.stringValue() if result else None


def open_app(path) -> None:
    config = AppKit.NSWorkspaceOpenConfiguration.configuration()
    config.setActivates_(True)
    AppKit.NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(
        AppKit.NSURL.fileURLWithPath_(str(path)), config, None)


def open_url(url: str) -> None:
    if not AppKit.NSWorkspace.sharedWorkspace().openURL_(AppKit.NSURL.URLWithString_(url)):
        raise MacError(f"could not open {url}")


def _require_trust():
    if not accessibility_trusted():
        raise MacError("needs Accessibility permission (System Settings → Privacy & Security)")


def key_combo(keycode: int, flags: int = 0):
    _require_trust()
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        Quartz.CGEventSetFlags(event, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def media_key(key: int):
    _require_trust()
    for down in (True, False):
        state = 0xA if down else 0xB
        event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeSystemDefined, (0, 0), state << 8, 0, 0, None, 8, (key << 16) | (state << 8), -1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event.CGEvent())


def change_volume(delta: int):
    applescript(f"set volume output volume ((output volume of (get volume settings)) + {delta})")


def toggle_mute():
    applescript("set volume output muted (not (output muted of (get volume settings)))")


def _snapshot_pasteboard(pb) -> list:
    return [{t: item.dataForType_(t) for t in item.types()} for item in (pb.pasteboardItems() or [])]


def _restore_pasteboard(pb, saved: list):
    pb.clearContents()
    items = []
    for types in saved:
        item = AppKit.NSPasteboardItem.alloc().init()
        for t, data in types.items():
            if data is not None:
                item.setData_forType_(data, t)
        items.append(item)
    if items:
        pb.writeObjects_(items)


def paste_text(text: str, settle: float = 0.15):
    _require_trust()
    pb = AppKit.NSPasteboard.generalPasteboard()
    saved = _snapshot_pasteboard(pb)
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    key_combo(KEY_V, CMD)
    time.sleep(settle)
    _restore_pasteboard(pb, saved)


def _focused_window():
    _require_trust()
    app = frontmost_app()
    window = _ax(AX.AXUIElementCreateApplication(app.processIdentifier()), AX.kAXFocusedWindowAttribute)
    if window is None:
        raise MacError(f"{app.localizedName()} has no focused window")
    return window


def _visible_frame() -> tuple[float, float, float, float]:
    screen = AppKit.NSScreen.mainScreen()
    full, vis = screen.frame(), screen.visibleFrame()
    top = full.size.height - (vis.origin.y + vis.size.height)
    return vis.origin.x, top, vis.size.width, vis.size.height


def _set_frame(window, x: float, y: float, w: float, h: float):
    position = AX.AXValueCreate(AX.kAXValueCGPointType, Quartz.CGPoint(x, y))
    size = AX.AXValueCreate(AX.kAXValueCGSizeType, Quartz.CGSize(w, h))
    AX.AXUIElementSetAttributeValue(window, AX.kAXPositionAttribute, position)
    AX.AXUIElementSetAttributeValue(window, AX.kAXSizeAttribute, size)


def tile(where: str):
    x, y, w, h = _visible_frame()
    frames = {"left_half": (x, y, w / 2, h), "right_half": (x + w / 2, y, w / 2, h),
              "maximize": (x, y, w, h)}
    _set_frame(_focused_window(), *frames[where])


def minimize_window():
    AX.AXUIElementSetAttributeValue(_focused_window(), AX.kAXMinimizedAttribute, True)


def toggle_fullscreen():
    window = _focused_window()
    AX.AXUIElementSetAttributeValue(window, "AXFullScreen", not _ax(window, "AXFullScreen"))


def close_window():
    button = _ax(_focused_window(), AX.kAXCloseButtonAttribute)
    if button is None:
        raise MacError("window has no close button")
    AX.AXUIElementPerformAction(button, AX.kAXPressAction)


def close_all_windows():
    key_combo(KEY_W, CMD | OPT)
