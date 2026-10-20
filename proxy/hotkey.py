from typing import Callable

import Quartz

KEYS = {
    "right_option": (61, Quartz.kCGEventFlagMaskAlternate),
    "right_command": (54, Quartz.kCGEventFlagMaskCommand),
    "right_control": (62, Quartz.kCGEventFlagMaskControl),
    "fn": (63, Quartz.kCGEventFlagMaskSecondaryFn),
}


def listen_access() -> bool:
    return bool(Quartz.CGPreflightListenEventAccess())


def request_listen_access():
    Quartz.CGRequestListenEventAccess()


class HoldKey:
    """Calls on_press / on_release when a modifier key is held and let go.
    Listen-only: the key still reaches every other app."""

    def __init__(self, key: str, on_press: Callable[[], None], on_release: Callable[[], None]):
        self._keycode, self._mask = KEYS[key]
        self._on_press, self._on_release = on_press, on_release
        self._held = False
        self._tap = None

    def _callback(self, proxy, event_type, event, refcon):
        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode) != self._keycode:
            return event
        down = bool(Quartz.CGEventGetFlags(event) & self._mask)
        if down and not self._held:
            self._held = True
            self._on_press()
        elif not down and self._held:
            self._held = False
            self._on_release()
        return event

    def install(self):
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged), self._callback, None)
        if self._tap is None:
            raise RuntimeError("could not create key listener: grant Input Monitoring "
                               "(System Settings → Privacy & Security)")
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
