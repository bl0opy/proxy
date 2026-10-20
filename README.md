# proxy

A fast, general-purpose voice assistant for macOS. A System One model decides what an
utterance means; code does the rest.

## Router

One [Jev](https://docs.typesafe.ai) request per utterance answers four questions at once:
the intent, which app, which media action, and which window action. A keyword fast path
answers exact commands ("skip", "open slack") without a network call. Answers under 0.7
confidence come back flagged `confident: false` so the caller can ask instead of act.

```bash
pyenv local 3.11.6 && python -m venv .venv
echo "JEV_API_KEY=..." > .env
.venv/bin/python -m proxy "put this window on the left half" --app Xcode
.venv/bin/python -m proxy            # interactive
```

## Benchmarks

`bench/` holds the model comparison that led here (nimble, Laya, Jev) and the router eval.
See [bench/RESULTS.md](bench/RESULTS.md). `requirements.txt` is only needed for the Laya
comparison; the router itself is stdlib.
