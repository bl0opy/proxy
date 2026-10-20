# proxy

A fast, general-purpose voice assistant for macOS. A System One model decides what an
utterance means; code does the rest.

## Router

One [Jev](https://docs.typesafe.ai) request per utterance answers four questions at once:
the intent, which app, which media action, and which window action. A keyword fast path
answers exact commands ("skip", "open slack") without a network call. Answers under 0.7
confidence come back flagged `confident: false` so the caller can ask instead of act.

## Actions

Each confident route becomes one action, run in-process through PyObjC:

| intent | action |
|---|---|
| `open_app` | launch / focus the app (async, ~0.5 ms to return) |
| `type_text` | paste the spoken text into the focused field, then restore the clipboard |
| `web_search` | open a spoken URL ("github dot com") or a Google search |
| `media_control` | system media keys for play/pause/next/previous; volume and mute via AppleScript |
| `window_management` | tile left/right/maximize, minimize, fullscreen, close via the Accessibility API |
| `rewrite_selection`, `calendar_reminder`, `ask_question`, `escalate_complex` | not built yet (System 2) |

Typing, windows, media keys and reading the selection need Accessibility permission for
whatever runs proxy (your terminal): `python -m proxy --request-access`.

```bash
pyenv local 3.11.6 && python -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "JEV_API_KEY=..." > .env
.venv/bin/python -m proxy "open calculator"
.venv/bin/python -m proxy "put this window on the left half" --delay 3   # switch apps first
.venv/bin/python -m proxy --dry-run                                       # interactive, plan only
```

## Benchmarks

`bench/` holds the model comparison that led here (nimble, Laya, Jev) and the router eval.
See [bench/RESULTS.md](bench/RESULTS.md). `laya` in `requirements.txt` is only for that
comparison.
