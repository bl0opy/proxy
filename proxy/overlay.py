import math
import time
from collections import deque
from typing import Callable

import AppKit
import objc
from Foundation import NSMakeRect, NSTimer

WIDTH, HEIGHT = 380, 72
RADIUS = 18
BARS, DOT, GAP, ROWS = 32, 3.0, 2.0, 7
SHOW_SECONDS = {"done": 1.6, "unsure": 2.6, "error": 3.0, "muted": 0.9, "pending": 15.0}


def rgba(r, g, b, a=1.0):
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, a)


BACKGROUND = rgba(11, 11, 12, 0.94)
BORDER = rgba(255, 255, 255, 0.08)
TEXT = rgba(245, 245, 245, 0.94)
MUTED = rgba(245, 245, 245, 0.45)
RED = rgba(255, 59, 48)
AMBER = rgba(255, 176, 32)
GREY = rgba(140, 140, 140)

GLYPH = {"done": TEXT, "unsure": AMBER, "error": RED, "muted": GREY}


def mono(size: float, weight=AppKit.NSFontWeightRegular):
    return AppKit.NSFont.monospacedSystemFontOfSize_weight_(size, weight)


def text_attrs(font, color, kern: float = 0.0) -> dict:
    style = AppKit.NSMutableParagraphStyle.alloc().init()
    style.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    return {AppKit.NSFontAttributeName: font, AppKit.NSForegroundColorAttributeName: color,
            AppKit.NSParagraphStyleAttributeName: style, AppKit.NSKernAttributeName: kern}


TITLE = text_attrs(mono(13, AppKit.NSFontWeightMedium), TEXT)
ARROW = text_attrs(mono(16, AppKit.NSFontWeightSemibold), TEXT)
DETAIL = text_attrs(mono(10), MUTED, 1.2)


def to_level(rms: float) -> float:
    db = 20 * math.log10(max(rms, 1e-6))
    return min(1.0, max(0.0, (db + 60) / 42))


def dot(x: float, y: float, r: float, color):
    color.setFill()
    AppKit.NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - r, y - r, 2 * r, 2 * r)).fill()


class OverlayView(AppKit.NSView):
    def initWithFrame_(self, frame):
        self = objc.super(OverlayView, self).initWithFrame_(frame)
        if self is not None:
            self.state = "hidden"
            self.levels = deque([0.0] * BARS, maxlen=BARS)
            self.title = ""
            self.detail = ""
            self.started = time.monotonic()
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        bounds = NSMakeRect(0.5, 0.5, WIDTH - 1, HEIGHT - 1)
        shape = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, RADIUS, RADIUS)
        BACKGROUND.setFill()
        shape.fill()
        BORDER.setStroke()
        shape.setLineWidth_(1)
        shape.stroke()

        t = time.monotonic() - self.started
        cy = HEIGHT / 2
        if self.state == "listening":
            dot(26, cy, 5, RED.colorWithAlphaComponent_(0.65 + 0.35 * math.sin(t * 6)))
            self._draw_meter(cy)
            elapsed = f"{t:4.1f}s"
            label = AppKit.NSAttributedString.alloc().initWithString_attributes_(f"REC {elapsed}", DETAIL)
            size = label.size()
            label.drawAtPoint_((WIDTH - 20 - size.width, cy - size.height / 2))
            return
        if self.state == "thinking":
            for i in range(3):
                alpha = 0.25 + 0.75 * max(0.0, math.sin(t * 7 - i * 0.9))
                dot(18 + i * 8, cy, 2.5, TEXT.colorWithAlphaComponent_(alpha))
        elif self.state == "pending":
            arrow = AppKit.NSAttributedString.alloc().initWithString_attributes_("↑", ARROW)
            size = arrow.size()
            bob = 2 * math.sin(t * 4)
            arrow.drawAtPoint_((26 - size.width / 2, cy - size.height / 2 + bob))
        else:
            dot(26, cy, 5, GLYPH.get(self.state, GREY))
        self._draw_text()

    def _draw_meter(self, cy: float):
        x = 48.0
        for level in self.levels:
            count = max(1, round(level * ROWS))
            top = cy - (count * (DOT + GAP) - GAP) / 2
            for row in range(count):
                alpha = 0.9 if count > 1 else 0.25
                dot(x + DOT / 2, top + row * (DOT + GAP) + DOT / 2, DOT / 2,
                    TEXT.colorWithAlphaComponent_(alpha))
            x += DOT + GAP + 1

    def _draw_text(self):
        width = WIDTH - 48 - 20
        title = self.title or "…"
        top = 16 if self.detail else (HEIGHT - 18) / 2
        AppKit.NSAttributedString.alloc().initWithString_attributes_(title, TITLE).drawInRect_(
            NSMakeRect(48, top, width, 18))
        if self.detail:
            AppKit.NSAttributedString.alloc().initWithString_attributes_(self.detail.upper(), DETAIL).drawInRect_(
                NSMakeRect(48, 40, width, 14))


class Overlay:
    """A floating, non-activating panel: it never takes focus or clicks, so the
    app you were speaking into stays the key window. Main thread only."""

    def __init__(self, level_source: Callable[[], float] = lambda: 0.0):
        self._level = level_source
        self._view = OverlayView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, AppKit.NSBackingStoreBuffered, False)
        self._panel.setLevel_(AppKit.NSStatusWindowLevel)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._panel.setHasShadow_(True)
        self._panel.setIgnoresMouseEvents_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        self._panel.setContentView_(self._view)
        self._panel.setAlphaValue_(0.0)
        self._timer = None
        self._generation = 0

    def _place(self):
        frame = AppKit.NSScreen.mainScreen().visibleFrame()
        x = frame.origin.x + (frame.size.width - WIDTH) / 2
        y = frame.origin.y + frame.size.height - HEIGHT - 10
        self._panel.setFrameOrigin_((x, y))

    def _fade(self, alpha: float, duration: float = 0.14):
        def animate(context):
            context.setDuration_(duration)
            self._panel.animator().setAlphaValue_(alpha)
        AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(animate, None)

    def _tick(self, timer):
        if self._view.state == "listening":
            self._view.levels.append(to_level(self._level()))
        self._view.setNeedsDisplay_(True)

    def _show(self, state: str):
        self._generation += 1
        if self._view.state in ("hidden",) or state == "listening":
            self._view.started = time.monotonic()
        if self._view.state == "hidden":
            self._place()
            self._panel.orderFrontRegardless()
            self._fade(1.0)
        self._view.state = state
        if self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1 / 30, True, self._tick)
        self._view.setNeedsDisplay_(True)

    def listening(self):
        self._view.levels.extend([0.0] * BARS)
        self._view.title = self._view.detail = ""
        self._show("listening")

    def thinking(self, title: str = ""):
        self._view.title = title
        self._view.detail = ""
        self._show("thinking")

    def result(self, title: str, detail: str, kind: str = "done"):
        self._view.title = title
        self._view.detail = detail
        self._show(kind)
        generation = self._generation
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            SHOW_SECONDS.get(kind, 1.6), False, lambda _: self._hide(generation))

    def _hide(self, generation: int):
        if generation != self._generation:
            return
        self._view.state = "hidden"
        self._fade(0.0, 0.25)
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def snapshot(self, path: str):
        rep = self._view.bitmapImageRepForCachingDisplayInRect_(self._view.bounds())
        self._view.cacheDisplayInRect_toBitmapImageRep_(self._view.bounds(), rep)
        rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(
            path, True)


def demo():
    import random
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    overlay = Overlay(lambda: random.uniform(0.002, 0.08))
    steps = [
        (0.0, overlay.listening),
        (2.0, lambda: overlay.thinking("Put this window on the left half.")),
        (2.4, lambda: overlay.result("Put this window on the left half.", "→ left half · Safari · 352 ms")),
        (4.5, overlay.listening),
        (6.0, lambda: overlay.thinking("Hey Sam, just checking in on the deck for tomorrow.")),
        (6.3, lambda: overlay.result("Hey Sam, just checking in on the deck for tomorrow.",
                                     "unsure · ignore noise 0.52 · not acting", "unsure")),
        (9.0, overlay.listening),
        (10.5, lambda: overlay.thinking("Time to write some lyrics.")),
        (10.8, lambda: overlay.result("Time to write some lyrics.", "↑ swipe up · Notes", "pending")),
        (14.0, AppHelper.stopEventLoop),
    ]
    for delay, step in steps:
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(delay, False, lambda _, s=step: s())
    AppHelper.runEventLoop(installInterrupt=True)


if __name__ == "__main__":
    demo()
