import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy.env import load_env
from proxy.router import Router

CASES = [
    ("time to write some lyrics", {"Notes"}),
    ("i wanna jot down an idea", {"Notes", "Stickies", "VoiceMemos"}),
    ("let's make a beat", {"Logic Pro", "FL Studio 2025"}),
    ("time to record vocals", {"Logic Pro"}),
    ("i need to email my professor", {"Mail"}),
    ("let me text my mom", {"Messages", "WhatsApp"}),
    ("i wanna work on my code", {"Visual Studio Code", "Xcode"}),
    ("gonna do some 3d modelling", {"Blender"}),
    ("put on some music", {"Spotify", "Music"}),
    ("what's the weather like", {"Weather"}),
    ("check my schedule", {"Calendar"}),
    ("i need to make slides for class", {"Keynote"}),
    ("design a mockup for the app", {"Figma", "Paper"}),
    ("look something up online", {"Safari", "Google Chrome", "Firefox"}),
    ("how's the market doing", {"TradingView", "Stocks"}),
    ("hop on a call with the team", {"zoom.us", "FaceTime", "Slack", "Discord"}),
    ("open slack", {"Slack"}),
    ("uh never mind", {""}),
]


def main():
    load_env()
    router = Router()
    router.warm()
    correct, times = 0, []
    for text, expected in CASES:
        r = router.route(text, "Finder")
        got = r.best_app
        ok = got in expected
        correct += ok
        times.append(r.ms)
        print(f"{'✓' if ok else '✗'} {text:38} → {got or '-':18} {r.suggestion_confidence:.2f}"
              f"  [{r.intent} {r.confidence:.2f}]  {r.ms:.0f} ms")
    print(f"\n{correct}/{len(CASES)} correct · median {statistics.median(times):.0f} ms")


if __name__ == "__main__":
    main()
