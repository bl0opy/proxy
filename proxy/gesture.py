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
SWIPE_WINDOW = 0.45
SWIPE_DISTANCE = 0.16
AXIS_RATIO = 1.6
RETURN_LOOKBACK = 0.6
RETURN_FRACTION = 0.6
COOLDOWN = 0.7
ENTRY_SETTLE = 0.25
DOWN_CONFIRM = 0.2
EXIT_EDGE = 0.85
HOLD_SECONDS = 0.35
HOLD_DRIFT = 0.035
LOST_SECONDS = 0.25
IDLE_AFTER = 2.0
IDLE_EVERY = 5

INDEX, MIDDLE, RING, PINKY = (8, 6), (12, 10), (16, 14), (20, 18)
WRIST, INDEX_KNUCKLE, MIDDLE_KNUCKLE = 0, 5, 9
TWO_SHARE = 2 / 3


@dataclass
class Hand:
    x: float
    y: float
    size: float
    pose: str
    tip_x: float = 0.0
    tip_y: float = 0.0

    @property
    def open(self) -> bool:
        return self.pose == "open"


@dataclass
class Sample:
    t: float
    x: float
    y: float
    pose: str


def hand_from_landmarks(points) -> Hand:
    """Position is the midpoint of the index and middle knuckles, which move with the
    hand but not with curling fingers; tip_x/tip_y is the fingertip midpoint, for display.
    Pose is "open" (four fingers out), "two" (index and middle out, ring and pinky
    curled) or "other"."""
    def dist(a, b):
        return math.hypot(points[a].x - points[b].x, points[a].y - points[b].y)

    def extended(finger):
        tip, pip = finger
        return dist(WRIST, tip) > 1.1 * dist(WRIST, pip)

    index, middle, ring, pinky = map(extended, (INDEX, MIDDLE, RING, PINKY))
    if index and middle and ring and pinky:
        pose = "open"
    elif index and middle and not ring and not pinky:
        pose = "two"
    else:
        pose = "other"
    x = (points[INDEX_KNUCKLE].x + points[MIDDLE_KNUCKLE].x) / 2
    y = (points[INDEX_KNUCKLE].y + points[MIDDLE_KNUCKLE].y) / 2
    tip_x = (points[INDEX[0]].x + points[MIDDLE[0]].x) / 2
    tip_y = (points[INDEX[0]].y + points[MIDDLE[0]].y) / 2
    return Hand(x, y, dist(WRIST, MIDDLE_KNUCKLE), pose, tip_x, tip_y)


class Detector:
    """Turns a stream of hand positions (mirrored, 0–1, y down) into events:
    palm_start / palm_end for a held open palm, and swipe_left/right/up/down for a
    two-finger swipe. A swipe during a palm hold ends it without a palm_end, except
    a downward one, which is read as lowering the hand. Pure logic, no camera."""

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
            self.track.append(Sample(t, hand.x, hand.y, hand.pose))
            if hand.open or (self.palm and hand.pose == "two"):
                self.last_open = t
        while self.track and t - self.track[0].t > SWIPE_WINDOW + RETURN_LOOKBACK:
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
        since = max(self.appeared_at + ENTRY_SETTLE, self.cooldown_until, t - SWIPE_WINDOW)
        window = [s for s in self.track if s.t >= since]
        if len(window) < 3 or sum(s.pose == "two" for s in window) < TWO_SHARE * len(window):
            return None
        dx = window[-1].x - window[0].x
        dy = window[-1].y - window[0].y
        if abs(dx) >= SWIPE_DISTANCE and abs(dx) >= AXIS_RATIO * abs(dy):
            axis, move, swipe = "x", dx, "swipe_right" if dx > 0 else "swipe_left"
        elif abs(dy) >= SWIPE_DISTANCE and abs(dy) >= AXIS_RATIO * abs(dx):
            axis, move, swipe = "y", dy, "swipe_down" if dy > 0 else "swipe_up"
        else:
            return None
        return None if self._returning(window[0], axis, move) else swipe

    def _returning(self, start: Sample, axis: str, move: float) -> bool:
        """True when the hand just travelled the other way: this is the stroke back
        from a swipe that didn't fire, not a new one."""
        before = [s for s in self.track if start.t - RETURN_LOOKBACK <= s.t < start.t]
        if not before:
            return False
        values = [getattr(s, axis) for s in before]
        here = getattr(start, axis)
        back = here - min(values) if move < 0 else max(values) - here
        return back >= RETURN_FRACTION * SWIPE_DISTANCE


def ensure_model():
    if MODEL.exists():
        return
    import urllib.request
    print(f"downloading {MODEL.name}…")
    MODEL.parent.mkdir(exist_ok=True)
    partial = MODEL.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, partial)
    partial.rename(MODEL)


def camera_access(timeout: float = 60) -> bool:
    import AVFoundation as AV
    status = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
    if status == AV.AVAuthorizationStatusAuthorized:
        return True
    if status != AV.AVAuthorizationStatusNotDetermined:
        return False
    answered, granted = threading.Event(), []
    AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AV.AVMediaTypeVideo, lambda ok: (granted.append(ok), answered.set()))
    answered.wait(timeout)
    return bool(granted and granted[0])


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
        if not camera_access():
            self.error = "no camera access (System Settings → Privacy & Security → Camera)"
            print(f"gestures off: {self.error}")
            return
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
    import json
    import queue

    import cv2

    record = Path("gesture-log.jsonl").open("w")
    frames: queue.Queue = queue.Queue(maxsize=1)
    log: deque[str] = deque(maxlen=6)
    flash = {"text": "", "until": 0.0}
    stamps: deque[float] = deque(maxlen=30)

    def on_event(event: str):
        stamp = time.strftime("%H:%M:%S")
        log.appendleft(f"{stamp} {event}")
        flash.update(text=event.replace("_", " ").upper(), until=time.monotonic() + 0.8)
        record.write(json.dumps({"t": time.monotonic(), "event": event}) + "\n")
        print(f"{stamp} {event}", flush=True)

    def on_frame(frame, result, hand, detector):
        now = time.monotonic()
        stamps.append(now)
        fps = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0
        record.write(json.dumps({"t": now, "hand": hand and [round(hand.x, 4), round(hand.y, 4),
                                                             round(hand.size, 4), hand.pose]}) + "\n")
        h, w = frame.shape[:2]
        for points in result.hand_landmarks:
            for p in points:
                cv2.circle(frame, (int(p.x * w), int(p.y * h)), 3, (255, 255, 255), -1)
        track = list(detector.track)
        for a, b in zip(track, track[1:]):
            cv2.line(frame, (int(a.x * w), int(a.y * h)), (int(b.x * w), int(b.y * h)), (0, 200, 255), 2)
        dx = track[-1].x - track[0].x if track else 0
        dy = track[-1].y - track[0].y if track else 0
        cv2.putText(frame, f"{fps:4.1f} fps  window dx {dx:+.2f} dy {dy:+.2f} (need {SWIPE_DISTANCE})",
                    (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        if hand:
            color = (0, 0, 255) if detector.palm else {"open": (0, 200, 0), "two": (255, 160, 0)}.get(
                hand.pose, (160, 160, 160))
            cv2.circle(frame, (int(hand.tip_x * w), int(hand.tip_y * h)), 12, color, 2)
            cv2.circle(frame, (int(hand.x * w), int(hand.y * h)), 4, color, -1)
            label = result.gestures[0][0].category_name if result.gestures else ""
            cv2.putText(frame, f"size {hand.size:.2f} {hand.pose} {label}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if detector.palm:
            cv2.putText(frame, "LISTENING", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        if now < flash["until"]:
            size = cv2.getTextSize(flash["text"], cv2.FONT_HERSHEY_SIMPLEX, 1.6, 4)[0]
            cv2.putText(frame, flash["text"], ((w - size[0]) // 2, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                        (0, 255, 255), 4)
        for i, line in enumerate(log):
            cv2.putText(frame, line, (10, h - 16 - i * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if frames.full():
            frames.get_nowait()
        frames.put(frame)

    camera = Camera(on_event, on_frame=on_frame)
    camera.start()
    print("gesture debug — q to quit · recording to gesture-log.jsonl", flush=True)
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
        record.close()


if __name__ == "__main__":
    debug()
