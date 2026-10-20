import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy.env import load_env
from proxy.router import Router, build_questions, build_state

CASES = [
    ("open spotify", "Finder", "", "open_app", {}),
    ("open music", "Finder", "", "open_app", {"app": "Music"}),
    ("switch to slack", "Safari", "", "open_app", {"app": "Slack"}),
    ("bring up my notes", "Safari", "", "open_app", {"app": "Notes"}),
    ("pull up the terminal", "Xcode", "", "open_app", {"app": "Terminal"}),
    ("hey sam just checking in on the deck for tomorrow", "Messages", "", "type_text", {}),
    ("type running ten minutes late sorry", "Slack", "", "type_text", {}),
    ("make this sound more professional", "Mail", "yo can u send me the file asap", "rewrite_selection", {}),
    ("translate this to spanish", "Notes", "Meeting moved to Thursday.", "rewrite_selection", {}),
    ("fix the grammar", "Pages", "their going to the store tomorow", "rewrite_selection", {}),
    ("search for m1 max memory bandwidth", "Safari", "", "web_search", {}),
    ("go to github dot com", "Finder", "", "web_search", {}),
    ("skip this song", "Spotify", "", "media_control", {"media_action": "next"}),
    ("turn the volume down", "Safari", "", "media_control", {"media_action": "volume_down"}),
    ("pause the music", "Slack", "", "media_control", {"media_action": "pause"}),
    ("go back a track", "Spotify", "", "media_control", {"media_action": "previous"}),
    ("put this window on the left half", "Xcode", "", "window_management", {"window_action": "left_half"}),
    ("close all finder windows", "Finder", "", "window_management", {"window_action": "close_all"}),
    ("make this full screen", "Safari", "", "window_management", {"window_action": "fullscreen"}),
    ("hide this window", "Mail", "", "window_management", {"window_action": "minimize"}),
    ("remind me at five to call mom", "Slack", "", "calendar_reminder", {}),
    ("set a timer for twenty minutes", "Terminal", "", "calendar_reminder", {}),
    ("whats on my calendar tomorrow", "Finder", "", "calendar_reminder", {}),
    ("how many ounces in a cup", "Safari", "", "ask_question", {}),
    ("whats the capital of australia", "Finder", "", "ask_question", {}),
    ("find the pdf sam sent last week and summarize it into a note", "Mail", "", "escalate_complex", {}),
    ("clean up my downloads folder and sort everything by type", "Finder", "", "escalate_complex", {}),
    ("uh yeah no i was telling him about the thing", "Zoom", "", "ignore_noise", {}),
    ("mhm", "Zoom", "", "ignore_noise", {}),
]


def run(router: Router, use_fastpath: bool) -> list:
    rows = []
    for transcript, app, selection, gold, gold_slots in CASES:
        if use_fastpath:
            r = router.route(transcript, app, selection)
        else:
            r = _jev_only(router, transcript, app, selection)
        ok = r.intent == gold and r.slots == gold_slots
        rows.append((transcript, gold, gold_slots, r, ok))
    return rows


def _jev_only(router: Router, transcript: str, app: str, selection: str):
    import proxy.router as pr
    saved = pr.fast_route
    pr.fast_route = lambda _: None
    try:
        return router.route(transcript, app, selection)
    finally:
        pr.fast_route = saved


def report(name: str, rows: list):
    ms = [r.ms for _, _, _, r, _ in rows]
    jev_ms = [r.ms for _, _, _, r, _ in rows if r.source == "jev"]
    correct = sum(ok for *_, ok in rows)
    acted = [ok for *_, r, ok in rows if r.confident]
    print(f"\n## {name}")
    print(f"  correct {correct}/{len(rows)} (intent + slots)   "
          f"confident {len(acted)}/{len(rows)}, of which wrong {acted.count(False)}")
    print(f"  all     median {statistics.median(ms):6.1f} ms   max {max(ms):6.1f}")
    if jev_ms:
        print(f"  jev     median {statistics.median(jev_ms):6.1f} ms   p90 "
              f"{statistics.quantiles(jev_ms, n=10)[-1] if len(jev_ms) > 2 else max(jev_ms):6.1f}   n={len(jev_ms)}")
    for transcript, gold, gold_slots, r, ok in rows:
        if not ok or r.confidence < 0.8:
            mark = "  " if ok else "✗ "
            want = "" if ok else f"  (want {gold} {gold_slots or ''})"
            print(f"    {mark}{transcript[:44]:44} -> {r.intent} {r.slots or ''}  conf {r.confidence:.2f}{want}")


def token_cost(router: Router):
    state = build_state(*CASES[0][:3])
    full = router._jev.ask(state, build_questions())["usage"]["input_tokens"]
    q = build_questions()
    q.pop("app")
    start = time.perf_counter()
    lean = router._jev.ask(state, q)["usage"]["input_tokens"]
    lean_ms = (time.perf_counter() - start) * 1000
    print(f"\n## request size: with app list {full} tokens (${full * 0.042e-6:.7f}), "
          f"without {lean} tokens ({lean_ms:.0f} ms)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    load_env()
    router = Router()
    router.warm()
    router.route("warm up the connection", "Finder")
    for i in range(args.rounds):
        report(f"jev only, round {i + 1}", run(router, use_fastpath=False))
    report("fast path + jev", run(router, use_fastpath=True))
    token_cost(router)


if __name__ == "__main__":
    main()
