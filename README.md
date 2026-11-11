# proxy

Hands-free control for macOS. Pinch the air to switch desktops, raise a palm and talk to
open the right app, all from the webcam and mic you already have.

A small "System One" model decides what you meant; plain code does the rest. Everything
runs locally except one short routing request.

```
 webcam ─▶ MediaPipe hand landmarks ─▶ gesture detector ─┐
                                                         ├─▶ action layer ─▶ macOS
 mic ─▶ parakeet STT (on device) ─▶ Jev router ──────────┘   (PyObjC: apps, windows,
                                                               desktops, media, typing)
```

## What it does

**Gestures** (webcam, one hand)

| gesture | does |
|---|---|
| pinch, drag left / right | switch desktop |
| pinch, drag up | open the app staged by your last request → else restore the last minimized window → else Mission Control |
| pinch, drag down | leave Mission Control if it's open → else minimize the front window |
| hold an open palm still ~0.35 s | start listening; lower or close the hand to send |
| pinch, drag up while listening | send, and open the app that best fits what you said |

A drag is thumb and index pinched while the whole hand moves. Each pinch fires once, and
moving back with your fingers apart does nothing, like lifting a finger off a trackpad.

**Voice** (hold right ⌥, or raise a palm)

| say | happens |
|---|---|
| "open slack", "skip", "pause" | runs immediately |
| "put this window on the left half" | tiles the window you were in |
| "github dot com", "search mediapipe docs" | opens the URL or a search |
| "type see you at five" | pastes into the focused field |
| "time to write some lyrics" | stages **Notes** in the pill for 15 s; pinch-drag up opens it |

While you talk, whatever is playing is quieted (volume drops to 10%, or Spotify / Music /
the browser is paused on interfaces without a software volume) and comes back afterwards.

A floating pill at the top of the screen shows state: listening with a level meter, the
transcript while it thinks, then the result and total time. It never takes focus.

## How it works

**Hand tracking.** MediaPipe's hand model gives 21 landmarks per frame (~14 ms). Motion is
measured at the palm centre, so curling fingers doesn't move the cursor point. The pinch
is the 3D thumb–index distance relative to hand size, with hysteresis (on below 0.3, off
above 0.5) and a 3-frame release debounce so motion blur doesn't drop a pinch mid-drag.
When no hand has been seen for 2 s, only every 5th frame is processed.

**Tuning from data.** `python -m proxy.gesture` opens a debug view and records every frame
to `gesture-log.jsonl`. Sessions replay offline through the detector, so threshold changes
are checked against real recordings rather than by feel.

**Speech.** Push-to-talk with a 300 ms pre-roll so the first syllable isn't clipped.
[parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3) (MLX)
transcribes on device in 65–170 ms.

**Routing.** One [Jev](https://docs.typesafe.ai) request per utterance answers five
questions at once: intent, app, media action, window action, and the best-fit app for
fuzzy requests. A keyword fast path answers exact commands with no network call. Answers
under 0.7 confidence are flagged instead of acted on. Release to done is ~200–350 ms.

**Actions.** Everything runs in-process through PyObjC: NSWorkspace for apps, the
Accessibility API for windows, CGEvents for keys and desktops, CoreAudio for ducking.

## Setup

Requires macOS on Apple Silicon and Python 3.11.

```bash
pyenv local 3.11.6 && python -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "JEV_API_KEY=..." > .env
.venv/bin/python -m proxy --request-access     # raises the permission prompts
.venv/bin/python -m proxy --listen
```

The hand model (`models/gesture_recognizer.task`, 8 MB) downloads on first run.

**Permissions** (System Settings → Privacy & Security): Camera (gestures), Microphone
(voice), Input Monitoring (the hotkey), Accessibility (windows, typing, media keys).
Desktop switching needs the Mission Control shortcuts enabled in Keyboard settings.

### Usage

```bash
.venv/bin/python -m proxy --listen                  # voice + gestures
.venv/bin/python -m proxy --listen --no-gestures    # voice only
.venv/bin/python -m proxy "open calculator"         # one command from text
.venv/bin/python -m proxy --dry-run                 # interactive, plan only
.venv/bin/python -m proxy.gesture                   # gesture debug view
.venv/bin/python -m proxy.overlay                   # pill demo
```

### Proxy.app

```bash
./scripts/build_app.sh && open build/Proxy.app
```

A menu bar app with no Dock icon. A tiny C launcher spawns the venv's Python as a child,
so macOS grants permissions to **Proxy** rather than your terminal. Code changes need no
rebuild. Logs go to `~/Library/Logs/Proxy/proxy.log`. Rebuilding re-signs the bundle ad
hoc, which can reset permissions, so only rebuild when `app/` changes.

## Layout

```
proxy/
  gesture.py    camera thread, hand landmarks → pinch/palm detector, debug view
  voice.py      listener: hotkey + palm recording, gesture routing, staging
  router.py     Jev router, fast path, confidence gate, best-fit app
  actions.py    intent → action
  mac.py        PyObjC: apps, windows, desktops, Mission Control, keys
  ducking.py    CoreAudio volume ducking / pause fallback
  stt.py        on-device parakeet transcription
  overlay.py    the floating pill
  statusbar.py  menu bar item
bench/          router and model benchmarks (see bench/RESULTS.md)
tests/          gesture detector and window-stack tests
```

```bash
.venv/bin/python -m unittest discover tests
```

## Roadmap

Moving toward general-purpose hand control:

- A hand cursor with pinch-to-click and snapping, then grabbing and throwing windows
- An in-view indicator so you know when your hand has left the frame
- A learned pose and motion classifier, trained on recorded hand sessions, in place of
  hand-tuned thresholds
- Benchmarking Apple Vision hand pose against MediaPipe
- Per-app mappings, like orbiting 3D models in Blender
