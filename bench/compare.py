import argparse
import json
import os
import statistics
import string
import time
import sys
import urllib.request
from pathlib import Path

from cases import CASES, INTENTS, make_context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy.env import load_env

INSTRUCTIONS = "What the user wants the voice assistant to do."
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_PRICE_PER_TOKEN = 0.042 / 1_000_000


class Nimble:
    name = "nimble (ollama Q8)"

    def __init__(self):
        import nimble_latency
        self._nl = nimble_latency
        nimble_latency.unload()
        self._codes = dict(zip(string.ascii_uppercase, INTENTS))

    def classify(self, context: str) -> dict:
        r = self._nl.generate(self._nl.build_prompt(context, INTENTS, "trained"))
        return {"intent": self._codes.get(r["response"].strip(), "?"), "confidence": None}


class Laya:
    def __init__(self, repo: str, labels_only: bool = False):
        import laya
        self.name = f"laya {repo.split('/')[-1]}{' labels only' if labels_only else ''} (mps)"
        self._agent = laya.load(repo, device="mps")
        criteria = list(INTENTS) if labels_only else INTENTS
        self._questions = {"intent": {"type": "choice", "instructions": INSTRUCTIONS,
                                      "criteria": criteria}}

    def classify(self, context: str) -> dict:
        answer = self._agent.predict(context, self._questions)["answers"]["intent"]
        return {"intent": answer["choice"],
                "confidence": answer.get("answer_confidence", answer.get("confidence"))}


class Jev:
    def __init__(self, model: str):
        self.name = f"jev {model} (api)"
        self._model = model
        self._key = os.environ["JEV_API_KEY"]
        self.input_tokens = []

    def classify(self, context: str) -> dict:
        payload = {"model": self._model, "state": context, "questions": {
            "intent": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": INTENTS}}}
        req = urllib.request.Request(JEV_URL, json.dumps(payload).encode(), {
            "Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        self.input_tokens.append(data["usage"]["input_tokens"])
        answer = data["answers"]["intent"]
        return {"intent": answer["choice"],
                "confidence": answer["probabilities"][answer["choice"]]}


def timed(backend, context: str) -> dict:
    start = time.perf_counter()
    result = backend.classify(context)
    result["ms"] = (time.perf_counter() - start) * 1000
    return result


def bench(backend, rounds: int) -> dict:
    for i in range(3):
        timed(backend, make_context(f"warmup number {i}", "Finder", ""))
    fresh, repeat, results = [], [], []
    for i in range(rounds):
        for transcript, app, selection, gold in CASES:
            r = timed(backend, make_context(transcript, app, selection))
            (repeat if i else fresh).append(r["ms"])
            if i == 0:
                results.append((transcript, gold, r))
    correct = sum(r["intent"] == gold for _, gold, r in results)
    print(f"\n## {backend.name}")
    print(f"  first-seen median {statistics.median(fresh):7.1f} ms   min {min(fresh):6.1f}   max {max(fresh):7.1f}")
    if repeat:
        print(f"  repeated   median {statistics.median(repeat):7.1f} ms")
    print(f"  accuracy {correct}/{len(CASES)}")
    for transcript, gold, r in results:
        conf = "" if r["confidence"] is None else f"  conf {r['confidence']:.2f}"
        mark = "  " if r["intent"] == gold else "✗ "
        if r["intent"] != gold or r["confidence"] is not None:
            print(f"    {mark}{transcript[:44]:44} -> {r['intent']:18}{conf}"
                  + ("" if r["intent"] == gold else f"  (want {gold})"))
    if isinstance(backend, Jev):
        tokens = statistics.median(backend.input_tokens)
        print(f"  input tokens median {tokens:.0f}  ->  ${tokens * JEV_PRICE_PER_TOKEN:.7f} per decision")
    return {"median_ms": statistics.median(fresh), "correct": correct}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backends", nargs="*",
                        default=["laya", "laya-labels", "laya-td", "nimble", "jev"])
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    load_env()

    factories = {
        "laya": lambda: Laya("convaiinnovations/laya"),
        "laya-labels": lambda: Laya("convaiinnovations/laya", labels_only=True),
        "laya-td": lambda: Laya("convaiinnovations/laya-typed-decisions"),
        "nimble": Nimble,
        "jev": lambda: Jev("jev-1.14.0"),
    }
    for name in args.backends:
        if name == "jev" and "JEV_API_KEY" not in os.environ:
            print("\n## jev: skipped, JEV_API_KEY not set")
            continue
        try:
            bench(factories[name](), args.rounds)
        except Exception as e:
            print(f"\n## {name}: failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
