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

## Voice

Hold right ⌥, speak, let go. The mic stays open with a 300 ms pre-roll so the first
syllable isn't clipped; only audio while the key is held is kept. parakeet-tdt-0.6b-v3
(MLX) transcribes on device, then the router and action layer take over. The frontmost
app and selection are captured when the key goes down, so the action lands where you were.
Release to done is ~200–350 ms (stt 65–170, Jev ~130, fast path 0).

A floating pill at the top of the screen shows what's happening: a red dot and a
dot-matrix level meter while you hold the key, the transcript while it thinks, then the
action and total time. White dot = done, amber = unsure or refused (not acted on),
red = failed. It never takes focus or clicks, so the app you spoke into stays active.
`python -m proxy.overlay` plays a short demo.

## Gestures

The webcam watches for one hand (MediaPipe gesture recognizer, ~14 ms a frame, every 5th
frame when no hand has been seen for 2 s).

| gesture | does |
|---|---|
| hold an open palm still ~0.35 s | start listening (same as holding right ⌥); lower the hand or close it to send |
| swipe up while listening | send, and open the app that best fits what you said |
| swipe up | open the app staged by your last fuzzy request; otherwise Mission Control |
| swipe left / right | switch desktop (needs the Mission Control shortcuts on in Keyboard settings) |
| swipe down | minimize the front window |

Clear commands still run as soon as you stop talking. Requests that aren't commands but
point at an app ("time to write some lyrics") are staged instead: the pill shows
`↑ … · open Notes` for 15 s and a swipe up opens it. The best-fit app is one more
question in the same Jev request (`bench/fit_eval.py`: 18/18, ~100 ms).

While you talk, whatever is playing is quieted: the output volume drops to 10% when the
device has a volume control; otherwise (audio interfaces with a hardware knob) Spotify or
Music is paused, or play/pause is sent when a browser is the one playing. It comes back
when the request is routed, unless the request was itself play or pause.

`python -m proxy.gesture` opens a debug view with the hand points and detected events,
for tuning the thresholds at the top of `proxy/gesture.py`. `--no-gestures` turns the
camera off; the menu bar item toggles it. The model (`models/gesture_recognizer.task`,
8 MB) downloads on first run.

## Proxy.app

```bash
./scripts/build_app.sh        # → build/Proxy.app
open build/Proxy.app
```

A menu bar app (no Dock icon, no terminal). The bundle's executable is a tiny C launcher
that spawns the venv's Python as a child, so macOS grants permissions to **Proxy**, not to
Terminal. Python code changes need no rebuild: the app runs the project in place. Output
goes to `~/Library/Logs/Proxy/proxy.log`. The menu bar item shows missing permissions,
toggles dry run, opens the log, restarts, and quits.

Rebuilding re-signs the bundle ad hoc, which can make macOS forget its permissions; only
rebuild when `app/` changes.

## Permissions

Proxy.app (or the terminal, when run from one) needs, in System Settings → Privacy & Security:
**Microphone** (voice), **Camera** (gestures), **Input Monitoring** (the hotkey) and **Accessibility** (typing,
windows, media keys, reading the selection). `python -m proxy --request-access` raises the
prompts.

```bash
pyenv local 3.11.6 && python -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "JEV_API_KEY=..." > .env
.venv/bin/python -m proxy "open calculator"
.venv/bin/python -m proxy "put this window on the left half" --delay 3   # switch apps first
.venv/bin/python -m proxy --dry-run                                       # interactive, plan only
.venv/bin/python -m proxy --listen                                        # push-to-talk
.venv/bin/python -m proxy --wav clip.aiff --dry-run                       # a recording instead of the mic
```

## Benchmarks

`bench/` holds the model comparison that led here (nimble, Laya, Jev) and the router eval.
See [bench/RESULTS.md](bench/RESULTS.md). `laya` in `requirements.txt` is only for that
comparison.
