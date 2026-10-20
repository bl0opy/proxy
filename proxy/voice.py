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
from .router import Router
from .stt import SAMPLE_RATE, Transcriber

MIN_SECONDS = 0.25


@dataclass
class Utterance:
    samples: np.ndarray
    ctx: mac.Context
    released_at: float


def chime(name: str):
    sound = AppKit.NSSound.soundNamed_(name)
    if sound is not None:
        sound.play()


def handle_utterance(transcriber: Transcriber, router: Router, u: Utterance, dry_run: bool) -> None:
    seconds = u.samples.size / SAMPLE_RATE
    start = time.perf_counter()
    text = transcriber.transcribe(u.samples)
    stt_ms = (time.perf_counter() - start) * 1000
    if not text:
        print(f"  (nothing heard, {seconds:.1f} s)")
        return
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
        if not outcome.done:
            chime("Funk")

    AppHelper.callAfter(act)


class Listener:
    def __init__(self, router: Router, key: str = "right_option", dry_run: bool = False, device=None):
        self._router = router
        self._dry_run = dry_run
        self._recorder = Recorder(device)
        self._hotkey = HoldKey(key, self._pressed, self._released)
        self._utterances: queue.Queue[Utterance] = queue.Queue()
        self._ctx = mac.Context()
        self._pressed_at = 0.0
        self._ready = threading.Event()

    def _pressed(self):
        self._pressed_at = time.perf_counter()
        self._recorder.start()
        self._ctx = mac.capture_context()
        chime("Tink")

    def _released(self):
        samples = self._recorder.stop()
        now = time.perf_counter()
        if now - self._pressed_at < MIN_SECONDS:
            return
        self._utterances.put(Utterance(samples, self._ctx, now))

    def _worker(self):
        transcriber = Transcriber()
        transcriber.load()
        self._ready.set()
        while True:
            u = self._utterances.get()
            try:
                handle_utterance(transcriber, self._router, u, self._dry_run)
            except Exception as e:
                print(f"  error: {type(e).__name__}: {e}")

    def run(self, key_label: str):
        threading.Thread(target=self._worker, daemon=True, name="stt").start()
        print("loading speech model…")
        self._ready.wait()
        self._recorder.open()
        self._hotkey.install()
        print(f"ready — hold {key_label} and speak. ctrl-c to quit.")
        try:
            AppHelper.runConsoleEventLoop(installInterrupt=True)
        finally:
            self._recorder.close()
