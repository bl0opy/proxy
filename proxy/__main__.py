import argparse
import json
from dataclasses import asdict

from .env import load_env
from .router import Router


def main():
    parser = argparse.ArgumentParser(prog="proxy")
    parser.add_argument("transcript", nargs="?")
    parser.add_argument("--app", default="", help="frontmost app")
    parser.add_argument("--selection", default="", help="selected text")
    args = parser.parse_args()

    load_env()
    router = Router()
    router.warm()
    if args.transcript:
        r = router.route(args.transcript, args.app, args.selection)
        print(json.dumps({**asdict(r), "confident": r.confident}, indent=2))
        return
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line:
            r = router.route(line, args.app, args.selection)
            print(f"  {r.intent} {r.slots or ''}  conf {r.confidence:.2f}{'' if r.confident else ' (unsure)'}  {r.source}  {r.ms:.0f} ms")


if __name__ == "__main__":
    main()
