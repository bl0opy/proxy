import queue
import threading
import time
from dataclasses import dataclass

import AppKit
import numpy as np
from PyObjCTools import AppHelper

from . import mac
from .actions import perform
from .audio import Recorder
from .hotkey import HoldKey
from .overlay import Overlay
from .router import Router
from .stt import SAMPLE_RATE, Transcriber

MIN_SECONDS = 0.25


@dataclass
class Utterance:
    samples: np.ndarray
    ctx: mac.Context
    released_at: float


def outcome_kind(route, outcome) -> str:
    if outcome.done or outcome.message.startswith("would "):
        return "done"
    if route.intent == "ignore_noise":
        return "muted"
    return "error" if "failed" in outcome.message else "unsure"


def handle_utterance(transcriber: Transcriber, router: Router, u: Utterance, dry_run: bool,
                     overlay: Overlay | None = None) -> None:
    seconds = u.samples.size / SAMPLE_RATE
    start = time.perf_counter()
    text = transcriber.transcribe(u.samples)
    stt_ms = (time.perf_counter() - start) * 1000
    if not text:
        print(f"  (nothing heard, {seconds:.1f} s)")
        if overlay:
            AppHelper.callAfter(overlay.result, "", "nothing heard", "muted")
        return
    if overlay:
        AppHelper.callAfter(overlay.thinking, text)
    route = router.route(text, u.ctx.app, u.ctx.selection)

    def act():
        outcome = perform(route, text, u.ctx, dry_run=dry_run)
        total = (time.perf_counter() - u.released_at) * 1000
        slots = f" {route.slots}" if route.slots else ""
        print(f"» {text}")
        print(f"  {route.intent}{slots}  conf {route.confidence:.2f}  [{u.ctx.app}]")
        print(f"  {'✓' if outcome.done else '·'} {outcome.message}")
        print(f"  {seconds:.1f} s audio · stt {stt_ms:.0f} · {route.source} {route.ms:.0f} · "
              f"act {outcome.ms:.0f} · release→done {total:.0f} ms")
        if overlay:
            where = f" · {u.ctx.app}" if route.intent == "window_management" and u.ctx.app else ""
            overlay.result(text, f"→ {outcome.message}{where} · {total:.0f} ms", outcome_kind(route, outcome))

    AppHelper.callAfter(act)


class Listener:
    def __init__(self, router: Router, key: str = "right_option", dry_run: bool = False, device=None):
        self._router = router
        self._dry_run = dry_run
        self._recorder = Recorder(device)
        self._hotkey = HoldKey(key, self._pressed, self._released)
        self._overlay: Overlay | None = None
        self._utterances: queue.Queue[Utterance] = queue.Queue()
        self._ctx = mac.Context()
        self._pressed_at = 0.0
        self._ready = threading.Event()

    def _pressed(self):
        self._pressed_at = time.perf_counter()
        self._recorder.start()
        self._ctx = mac.capture_context()
        self._overlay.listening()

    def _released(self):
        samples = self._recorder.stop()
        now = time.perf_counter()
        if now - self._pressed_at < MIN_SECONDS:
            self._overlay.result("", "too short", "muted")
            return
        self._overlay.thinking("")
        self._utterances.put(Utterance(samples, self._ctx, now))

    def _worker(self):
        transcriber = Transcriber()
        transcriber.load()
        self._ready.set()
        while True:
            u = self._utterances.get()
            try:
                handle_utterance(transcriber, self._router, u, self._dry_run, self._overlay)
            except Exception as e:
                print(f"  error: {type(e).__name__}: {e}")
                AppHelper.callAfter(self._overlay.result, "", f"error · {type(e).__name__}", "error")

    def run(self, key_label: str):
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        self._overlay = Overlay(lambda: self._recorder.level)
        threading.Thread(target=self._worker, daemon=True, name="stt").start()
        print("loading speech model…")
        self._ready.wait()
        self._recorder.open()
        self._hotkey.install()
        print(f"ready — hold {key_label} and speak. ctrl-c to quit.")
        try:
            AppHelper.runEventLoop(installInterrupt=True)
        finally:
            self._recorder.close()
