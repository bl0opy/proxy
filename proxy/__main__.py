import argparse
import time

from . import mac
from .actions import perform
from .env import load_env
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


def main():
    parser = argparse.ArgumentParser(prog="proxy")
    parser.add_argument("transcript", nargs="?")
    parser.add_argument("--app", default="", help="override the frontmost app")
    parser.add_argument("--selection", default="", help="override the selected text")
    parser.add_argument("--dry-run", action="store_true", help="route and plan, don't act")
    parser.add_argument("--delay", type=float, default=0,
                        help="seconds to wait before acting, to switch to the target app")
    parser.add_argument("--request-access", action="store_true",
                        help="show the macOS Accessibility permission prompt")
    args = parser.parse_args()

    if args.request_access:
        mac.request_accessibility()
        return
    if not mac.accessibility_trusted():
        print("note: no Accessibility permission — typing, windows, media keys and selection "
              "won't work. Run with --request-access.")

    load_env()
    router = Router()
    router.warm()
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
