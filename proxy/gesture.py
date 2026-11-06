import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MODEL = Path(__file__).resolve().parent.parent / "models" / "gesture_recognizer.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
             "gesture_recognizer/float16/latest/gesture_recognizer.task")

MIN_SIZE = 0.07
SWIPE_WINDOW = 0.35
SWIPE_DISTANCE = 0.16
AXIS_RATIO = 1.6
COOLDOWN = 0.7
ENTRY_SETTLE = 0.25
DOWN_CONFIRM = 0.2
EXIT_EDGE = 0.85
HOLD_SECONDS = 0.35
HOLD_DRIFT = 0.035
LOST_SECONDS = 0.25
IDLE_AFTER = 2.0
IDLE_EVERY = 5

FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))
WRIST, MIDDLE_KNUCKLE = 0, 9
PALM = (0, 5, 9, 13, 17)


@dataclass
class Hand:
    x: float
    y: float
    size: float
    open: bool


@dataclass
class Sample:
    t: float
    x: float
    y: float
    open: bool


def hand_from_landmarks(points) -> Hand:
    def dist(a, b):
        return math.hypot(points[a].x - points[b].x, points[a].y - points[b].y)

    extended = sum(dist(WRIST, tip) > 1.1 * dist(WRIST, pip) for tip, pip in FINGERS)
    x = sum(points[i].x for i in PALM) / len(PALM)
    y = sum(points[i].y for i in PALM) / len(PALM)
    return Hand(x, y, dist(WRIST, MIDDLE_KNUCKLE), extended >= 4)


class Detector:
    """Turns a stream of hand positions (mirrored, 0–1, y down) into events:
    palm_start / palm_end for a held open palm, and swipe_left/right/up/down.
    A swipe during a palm hold ends it without a palm_end. Pure logic, no camera."""

    def __init__(self):
        self.track: deque[Sample] = deque()
        self.palm = False
        self.armed = True
        self.cooldown_until = 0.0
        self.appeared_at = 0.0
        self.last_seen = -math.inf
        self.last_open = -math.inf
        self.still_since: float | None = None
        self.pending_down: float | None = None

    def update(self, t: float, hand: Hand | None) -> list[str]:
        events = []
        visible = hand is not None and hand.size >= MIN_SIZE
        if visible:
            if t - self.last_seen > LOST_SECONDS:
                self.appeared_at = t
                self.track.clear()
            self.last_seen = t
            self.track.append(Sample(t, hand.x, hand.y, hand.open))
            if hand.open:
                self.last_open = t
        while self.track and t - self.track[0].t > SWIPE_WINDOW:
            self.track.popleft()

        if self.pending_down is not None:
            if (visible and hand.y >= EXIT_EDGE) or t - self.last_seen > DOWN_CONFIRM:
                self.pending_down = None
            elif visible and t - self.pending_down >= DOWN_CONFIRM:
                self.pending_down = None
                events.append("swipe_down")
                return events

        if swipe := self._swipe(t):
            self.track.clear()
            self.still_since = None
            self.cooldown_until = t + COOLDOWN
            self.armed = False
            if swipe == "swipe_down":
                if self.palm:
                    self.palm = False
                    events.append("palm_end")
                else:
                    self.pending_down = t
                return events
            self.palm = False
            events.append(swipe)
            return events

        if t - self.last_open > LOST_SECONDS:
            if self.palm:
                self.palm = False
                events.append("palm_end")
            self.still_since = None
            self.armed = True
            return events

        if visible and hand.open and self.armed and not self.palm and t >= self.cooldown_until:
            if self._still(t):
                self.still_since = self.still_since or t
                if t - self.still_since >= HOLD_SECONDS:
                    self.palm = True
                    self.armed = False
                    events.append("palm_start")
            else:
                self.still_since = None
        return events

    def _still(self, t: float) -> bool:
        recent = [s for s in self.track if t - s.t <= 0.2]
        if len(recent) < 2:
            return False
        last = recent[-1]
        return all(math.hypot(s.x - last.x, s.y - last.y) < HOLD_DRIFT for s in recent)

    def _swipe(self, t: float) -> str | None:
        if t < self.cooldown_until:
            return None
        since = max(self.appeared_at + ENTRY_SETTLE, self.cooldown_until)
        samples = [s for s in self.track if s.t >= since]
        if len(samples) < 3 or not any(s.open for s in samples[: len(samples) // 2 + 1]):
            return None
        dx = samples[-1].x - samples[0].x
        dy = samples[-1].y - samples[0].y
        if abs(dx) >= SWIPE_DISTANCE and abs(dx) >= AXIS_RATIO * abs(dy):
            return "swipe_right" if dx > 0 else "swipe_left"
        if abs(dy) >= SWIPE_DISTANCE and abs(dy) >= AXIS_RATIO * abs(dx):
            return "swipe_down" if dy > 0 else "swipe_up"
        return None


def ensure_model():
    if MODEL.exists():
        return
    import urllib.request
    print(f"downloading {MODEL.name}…")
    MODEL.parent.mkdir(exist_ok=True)
    partial = MODEL.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, partial)
    partial.rename(MODEL)


def load_recognizer():
    from mediapipe.tasks.python import BaseOptions, vision
    ensure_model()
    options = vision.GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_hands=1)
    return vision.GestureRecognizer.create_from_options(options)


class Camera:
    """Reads the webcam on its own thread, runs MediaPipe on each frame and feeds
    the Detector. Drops to every 5th frame when no hand has been seen for 2 s.
    on_event is called from the camera thread."""

    def __init__(self, on_event: Callable[[str], None], index: int = 0,
                 on_frame: Callable | None = None):
        self._on_event = on_event
        self._on_frame = on_frame
        self._index = index
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="gesture")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        import cv2
        import mediapipe as mp
        try:
            recognizer = load_recognizer()
        except Exception as e:
            self.error = str(e)
            print(f"gestures off: {e}")
            return
        cap = cv2.VideoCapture(self._index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not cap.isOpened():
            self.error = "camera unavailable (grant Camera in System Settings → Privacy & Security)"
            print(f"gestures off: {self.error}")
            return
        detector = Detector()
        start = time.monotonic()
        frame_no = last_ms = 0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                t = time.monotonic()
                frame_no += 1
                if t - detector.last_seen > IDLE_AFTER and frame_no % IDLE_EVERY:
                    continue
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                ms = max(last_ms + 1, int((t - start) * 1000))
                last_ms = ms
                result = recognizer.recognize_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
                hand = hand_from_landmarks(result.hand_landmarks[0]) if result.hand_landmarks else None
                for event in detector.update(t, hand):
                    self._on_event(event)
                if self._on_frame:
                    self._on_frame(frame, result, hand, detector)
        finally:
            cap.release()
            recognizer.close()


def debug():
    import queue

    import cv2

    frames: queue.Queue = queue.Queue(maxsize=1)
    log: deque[str] = deque(maxlen=6)

    def on_event(event: str):
        stamp = time.strftime("%H:%M:%S")
        log.appendleft(f"{stamp} {event}")
        print(f"{stamp} {event}")

    def on_frame(frame, result, hand, detector):
        h, w = frame.shape[:2]
        for points in result.hand_landmarks:
            for p in points:
                cv2.circle(frame, (int(p.x * w), int(p.y * h)), 3, (255, 255, 255), -1)
        if hand:
            color = (0, 0, 255) if detector.palm else (0, 200, 0) if hand.open else (160, 160, 160)
            cv2.circle(frame, (int(hand.x * w), int(hand.y * h)), 10, color, 2)
            label = result.gestures[0][0].category_name if result.gestures else ""
            cv2.putText(frame, f"size {hand.size:.2f} open {hand.open} {label}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if detector.palm:
            cv2.putText(frame, "LISTENING", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        for i, line in enumerate(log):
            cv2.putText(frame, line, (10, h - 16 - i * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if frames.full():
            frames.get_nowait()
        frames.put(frame)

    camera = Camera(on_event, on_frame=on_frame)
    camera.start()
    print("gesture debug — q to quit")
    try:
        while camera.running or not frames.empty():
            try:
                frame = frames.get(timeout=1)
            except queue.Empty:
                continue
            cv2.imshow("proxy gestures", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    debug()
