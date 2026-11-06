import queue
import signal
import threading
import time
from dataclasses import dataclass
from typing import Callable

import AppKit
import numpy as np
from PyObjCTools import AppHelper, MachSignals

from . import mac
from .actions import Outcome, perform
from .audio import Recorder
from .ducking import Ducker
from .gesture import Camera
from .hotkey import HoldKey
from .overlay import Overlay
from .router import Route, Router
from .statusbar import StatusBar
from .stt import SAMPLE_RATE, Transcriber

MIN_SECONDS = 0.25
PENDING_SECONDS = 15


@dataclass
class Utterance:
    samples: np.ndarray
    ctx: mac.Context
    released_at: float
    commit: bool = False


@dataclass
class Pending:
    app: str
    text: str
    expires: float


def outcome_kind(route, outcome) -> str:
    if outcome.done or outcome.message.startswith("would "):
        return "done"
    if route.intent == "ignore_noise":
        return "muted"
    return "error" if "failed" in outcome.message else "unsure"


def open_route(app: str) -> Route:
    return Route("open_app", 1.0, "gesture", 0.0, {"app": app}, slot_confidence={"app": 1.0})


def media_action(route: Route | None) -> str | None:
    return route.slots.get("media_action") if route and route.intent == "media_control" else None


def stageable(route: Route, outcome: Outcome) -> bool:
    return not outcome.done and outcome.ms == 0 and not outcome.message.startswith("would ") \
        and bool(route.best_app)


def handle_utterance(transcriber: Transcriber, router: Router, u: Utterance, dry_run: bool,
                     overlay: Overlay | None = None, ducker: Ducker | None = None,
                     stage: Callable[[str, str], None] | None = None) -> None:
    seconds = u.samples.size / SAMPLE_RATE
    start = time.perf_counter()
    text = transcriber.transcribe(u.samples)
    stt_ms = (time.perf_counter() - start) * 1000
    if not text:
        print(f"  (nothing heard, {seconds:.1f} s)")
        if ducker:
            AppHelper.callAfter(ducker.release)
        if overlay:
            AppHelper.callAfter(overlay.result, "", "nothing heard", "muted")
        return
    if overlay:
        AppHelper.callAfter(overlay.thinking, text)
    try:
        route = router.route(text, u.ctx.app, u.ctx.selection)
    except Exception:
        if ducker:
            AppHelper.callAfter(ducker.release)
        raise

    def act():
        media = media_action(route)
        left_paused = ducker.release(media) if ducker else False
        if left_paused and media == "pause":
            outcome = Outcome(True, "paused")
        elif u.commit and route.best_app:
            outcome = perform(open_route(route.best_app), text, u.ctx, dry_run=dry_run)
        else:
            outcome = perform(route, text, u.ctx, dry_run=dry_run)
        total = (time.perf_counter() - u.released_at) * 1000
        slots = f" {route.slots}" if route.slots else ""
        fit = f"  fit {route.suggestion} {route.suggestion_confidence:.2f}" if route.suggestion else ""
        print(f"» {text}{'  (swipe up)' if u.commit else ''}")
        print(f"  {route.intent}{slots}  conf {route.confidence:.2f}{fit}  [{u.ctx.app}]")
        if stage and not u.commit and stageable(route, outcome):
            print(f"  ↑ staged {route.best_app} — swipe up within {PENDING_SECONDS} s")
            stage(route.best_app, text)
            return
        print(f"  {'✓' if outcome.done else '·'} {outcome.message}")
        print(f"  {seconds:.1f} s audio · stt {stt_ms:.0f} · {route.source} {route.ms:.0f} · "
              f"act {outcome.ms:.0f} · release→done {total:.0f} ms")
        if overlay:
            where = f" · {u.ctx.app}" if route.intent == "window_management" and u.ctx.app else ""
            overlay.result(text, f"→ {outcome.message}{where} · {total:.0f} ms", outcome_kind(route, outcome))

    AppHelper.callAfter(act)


class Listener:
    """Records while the hotkey is held or an open palm is raised, and turns swipes
    into actions. All state changes happen on the main thread."""

    def __init__(self, router: Router, key: str = "right_option", dry_run: bool = False, device=None,
                 gestures: bool = True, camera: int = 0):
        self._router = router
        self._dry_run = dry_run
        self._recorder = Recorder(device)
        self._hotkey = HoldKey(key, lambda: self._start("key"), lambda: self._finish("key"))
        self._camera = Camera(lambda e: AppHelper.callAfter(self._on_gesture, e), camera)
        self._gestures = gestures
        self._overlay: Overlay | None = None
        self._statusbar: StatusBar | None = None
        self._ducker: Ducker | None = None
        self._utterances: queue.Queue[Utterance] = queue.Queue()
        self._ctx = mac.Context()
        self._source: str | None = None
        self._started_at = 0.0
        self._pending: Pending | None = None
        self._ready = threading.Event()

    def _start(self, source: str):
        if self._source:
            return
        self._source = source
        self._started_at = time.perf_counter()
        self._recorder.start()
        self._ctx = mac.capture_context()
        self._ducker.duck()
        self._overlay.listening()
        if self._statusbar:
            self._statusbar.listening(True)

    def _stop(self) -> np.ndarray:
        self._source = None
        if self._statusbar:
            self._statusbar.listening(False)
        return self._recorder.stop()

    def _finish(self, source: str, commit: bool = False):
        if self._source != source:
            return
        samples = self._stop()
        now = time.perf_counter()
        if now - self._started_at < MIN_SECONDS:
            self._ducker.release()
            self._overlay.result("", "too short", "muted")
            return
        self._overlay.thinking("")
        self._utterances.put(Utterance(samples, self._ctx, now, commit))

    def _cancel(self):
        self._stop()
        self._ducker.release()

    def _stage(self, app: str, text: str):
        self._pending = Pending(app, text, time.monotonic() + PENDING_SECONDS)
        self._overlay.result(text, f"swipe up · open {app}", "pending")

    def _take_pending(self) -> Pending | None:
        pending, self._pending = self._pending, None
        return pending if pending and time.monotonic() < pending.expires else None

    def _on_gesture(self, event: str):
        print(f"  gesture: {event}")
        listening_by_palm = self._source == "palm"
        if event == "palm_start":
            self._start("palm")
        elif event == "palm_end":
            self._finish("palm")
        elif event == "swipe_up" and listening_by_palm:
            self._pending = None
            self._finish("palm", commit=True)
        elif event == "swipe_up":
            if pending := self._take_pending():
                self._run(pending.text, open_route(pending.app))
            else:
                self._run("swipe up", None, "mission control", mac.mission_control)
        else:
            if listening_by_palm:
                self._cancel()
            if event in ("swipe_left", "swipe_right"):
                side = event.removeprefix("swipe_")
                self._run(f"swipe {side}", None, f"desktop {side}", lambda: mac.switch_desktop(side), quiet=True)
            elif event == "swipe_down":
                self._run("swipe down", None, "minimize", mac.minimize_window)

    def _run(self, title: str, route: Route | None, label: str = "", action=None, quiet: bool = False):
        ctx = mac.capture_context()
        if route is not None:
            outcome = perform(route, title, ctx, dry_run=self._dry_run)
        elif self._dry_run:
            outcome = Outcome(False, f"would {label}")
        else:
            try:
                action()
                outcome = Outcome(True, label)
            except mac.MacError as e:
                outcome = Outcome(False, f"{label} failed: {e}")
        print(f"  {'✓' if outcome.done else '·'} {outcome.message}")
        if not (quiet and outcome.done):
            kind = "done" if outcome.done or self._dry_run else "error"
            self._overlay.result(title, f"→ {outcome.message}", kind)

    def _worker(self):
        transcriber = Transcriber()
        transcriber.load()
        self._ready.set()
        while True:
            u = self._utterances.get()
            try:
                handle_utterance(transcriber, self._router, u, self._dry_run, self._overlay,
                                 self._ducker, lambda app, text: AppHelper.callAfter(self._stage, app, text))
            except Exception as e:
                print(f"  error: {type(e).__name__}: {e}")
                AppHelper.callAfter(self._overlay.result, "", f"error · {type(e).__name__}", "error")

    def _set_dry_run(self, value: bool):
        self._dry_run = value

    def _set_gestures(self, value: bool):
        self._gestures = value
        if value:
            self._camera.start()
        else:
            if self._source == "palm":
                self._cancel()
                self._overlay.result("", "gestures off", "muted")
            self._camera.stop()

    def _gesture_status(self) -> str:
        if not self._gestures:
            return "off"
        return self._camera.error or ("on" if self._camera.running else "starting")

    def _cleanup(self):
        if self._ducker:
            self._ducker.release()
        self._camera.stop()

    def _quit(self, signum=None):
        self._cleanup()
        AppHelper.stopEventLoop()

    def run(self, key_label: str, menu_bar: bool = False):
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        self._overlay = Overlay(lambda: self._recorder.level)
        self._ducker = Ducker()
        if menu_bar:
            self._statusbar = StatusBar(key_label, lambda: self._dry_run, self._set_dry_run,
                                        lambda: self._gestures, self._set_gestures, self._gesture_status,
                                        self._cleanup)
        AppKit.NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            AppKit.NSApplicationWillTerminateNotification, None, None, lambda _: self._cleanup())
        MachSignals.signal(signal.SIGTERM, self._quit)
        threading.Thread(target=self._worker, daemon=True, name="stt").start()
        print("loading speech model…")
        self._ready.wait()
        self._recorder.open()
        self._hotkey.install()
        if self._gestures:
            self._camera.start()
        hint = " or raise an open palm" if self._gestures else ""
        print(f"ready — hold {key_label}{hint} and speak. ctrl-c to quit.")
        try:
            AppHelper.runEventLoop(installInterrupt=True)
        finally:
            self._cleanup()
            self._recorder.close()
