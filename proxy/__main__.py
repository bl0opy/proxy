import argparse
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from . import mac
from .actions import perform
from .env import load_env
from .hotkey import KEYS, listen_access, request_listen_access
from .router import Router


def handle(router: Router, transcript: str, args) -> None:
    ctx = mac.capture_context()
    if args.app:
        ctx.app = args.app
    if args.selection:
        ctx.selection = args.selection
    r = router.route(transcript, ctx.app, ctx.selection)
    outcome = perform(r, transcript, ctx, dry_run=args.dry_run)
    slots = f" {r.slots}" if r.slots else ""
    print(f"  {r.intent}{slots}  conf {r.confidence:.2f}  {r.source} {r.ms:.0f} ms  [{ctx.app}]")
    print(f"  {'✓' if outcome.done else '·'} {outcome.message}"
          + (f"  ({outcome.ms:.0f} ms)" if outcome.ms else ""))


def read_wav(path: str):
    import numpy as np
    from .stt import SAMPLE_RATE
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "in.wav"
        subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", path, str(out)],
                       check=True)
        with wave.open(str(out)) as w:
            pcm = w.readframes(w.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_file(router: Router, path: str, args) -> None:
    from .stt import Transcriber
    from .voice import Utterance, handle_utterance
    from PyObjCTools import AppHelper
    transcriber = Transcriber()
    start = time.perf_counter()
    transcriber.load()
    print(f"  model loaded in {(time.perf_counter() - start) * 1000:.0f} ms")
    ctx = mac.capture_context()
    ctx.app = args.app or ctx.app
    ctx.selection = args.selection or ctx.selection
    AppHelper.callAfter = lambda fn: fn()
    handle_utterance(transcriber, router, Utterance(read_wav(path), ctx, time.perf_counter()), args.dry_run)


def main():
    parser = argparse.ArgumentParser(prog="proxy")
    parser.add_argument("transcript", nargs="?")
    parser.add_argument("--app", default="", help="override the frontmost app")
    parser.add_argument("--selection", default="", help="override the selected text")
    parser.add_argument("--dry-run", action="store_true", help="route and plan, don't act")
    parser.add_argument("--delay", type=float, default=0,
                        help="seconds to wait before acting, to switch to the target app")
    parser.add_argument("--request-access", action="store_true",
                        help="show the macOS Accessibility and Input Monitoring prompts")
    parser.add_argument("--listen", action="store_true", help="push-to-talk voice mode")
    parser.add_argument("--key", default="right_option", choices=sorted(KEYS),
                        help="push-to-talk key (default right_option)")
    parser.add_argument("--wav", help="transcribe an audio file instead of the mic")
    parser.add_argument("--menu-bar", action="store_true", help="show a menu bar item (on in Proxy.app)")
    args = parser.parse_args()
    in_app = os.environ.get("PROXY_APP") == "1"

    if args.request_access:
        mac.request_accessibility()
        request_listen_access()
        return
    if in_app and not mac.accessibility_trusted():
        mac.request_accessibility()
    if not mac.accessibility_trusted():
        print("note: no Accessibility permission — typing, windows, media keys and selection "
              "won't work. Run with --request-access.")

    load_env()
    router = Router()
    router.warm()
    if args.listen:
        if in_app and not listen_access():
            request_listen_access()
        if not listen_access():
            print("note: no Input Monitoring permission — the hotkey can't be heard. "
                  "Run with --request-access.")
        from .voice import Listener
        label = {"right_option": "right ⌥", "right_command": "right ⌘",
                 "right_control": "right ⌃", "fn": "fn"}[args.key]
        Listener(router, args.key, args.dry_run).run(label, menu_bar=in_app or args.menu_bar)
        return
    if args.wav:
        transcribe_file(router, args.wav, args)
        return
    if args.transcript:
        time.sleep(args.delay)
        handle(router, args.transcript, args)
        return
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line:
            time.sleep(args.delay)
            handle(router, line, args)


if __name__ == "__main__":
    main()
