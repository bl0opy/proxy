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
PINCH_ON = 0.3
PINCH_OFF = 0.5
PINCH_FRAMES = 2
DRAG_DISTANCE = 0.12
AXIS_RATIO = 1.6
HOLD_SECONDS = 0.35
HOLD_DRIFT = 0.035
STILL_WINDOW = 0.2
LOST_SECONDS = 0.25
IDLE_AFTER = 2.0
IDLE_EVERY = 5

FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_KNUCKLE = 0, 4, 8, 9
PALM = (0, 5, 9, 13, 17)


@dataclass
class Hand:
    x: float
    y: float
    size: float
    open: bool
    gap: float = 1.0


@dataclass
class Sample:
    t: float
    x: float
    y: float


def distance(points, a: int, b: int, axes: str) -> float:
    return math.dist([getattr(points[a], c) for c in axes], [getattr(points[b], c) for c in axes])


def hand_from_landmarks(points, world=None) -> Hand:
    size = distance(points, WRIST, MIDDLE_KNUCKLE, "xy")
    extended = sum(distance(points, WRIST, tip, "xy") > 1.1 * distance(points, WRIST, pip, "xy")
                   for tip, pip in FINGERS)
    x = sum(points[i].x for i in PALM) / len(PALM)
    y = sum(points[i].y for i in PALM) / len(PALM)
    source, axes = (world, "xyz") if world else (points, "xy")
    span = distance(source, WRIST, MIDDLE_KNUCKLE, axes)
    gap = distance(source, THUMB_TIP, INDEX_TIP, axes) / span if span else 1.0
    return Hand(x, y, size, extended >= 4, gap)


class Detector:
    def __init__(self):
        self.track: deque[Sample] = deque()
        self.palm = False
        self.armed = True
        self.last_seen = -math.inf
        self.last_open = -math.inf
        self.still_since: float | None = None
        self.pinching = False
        self.pinch_frames = 0
        self.anchor: tuple[float, float] | None = None
        self.fired = False
        self.released_at = -math.inf

    def update(self, t: float, hand: Hand | None) -> list[str]:
        visible = hand is not None and hand.size >= MIN_SIZE
        if visible:
            self.last_seen = t
            self.track.append(Sample(t, hand.x, hand.y))
        while self.track and t - self.track[0].t > STILL_WINDOW:
            self.track.popleft()

        self._update_pinch(t, hand if visible else None)
        is_open = visible and hand.open and not self.pinching and hand.gap > PINCH_OFF
        if is_open or (self.palm and self.pinching):
            self.last_open = t

        if visible and self.pinching and not self.fired and (swipe := self._drag(hand)):
            self.fired = True
            self.palm = False
            self.armed = False
            self.still_since = None
            return [swipe]

        if t - self.last_open > LOST_SECONDS:
            events = ["palm_end"] if self.palm else []
            self.palm = False
            self.still_since = None
            if not self.pinching and t - self.released_at > LOST_SECONDS:
                self.armed = True
            return events

        if is_open and self.armed and not self.palm:
            if self._still():
                self.still_since = self.still_since or t
                if t - self.still_since >= HOLD_SECONDS:
                    self.palm = True
                    self.armed = False
                    return ["palm_start"]
            else:
                self.still_since = None
        return []

    def _update_pinch(self, t: float, hand: Hand | None):
        if self.pinching:
            released = hand.gap > PINCH_OFF if hand else t - self.last_seen > LOST_SECONDS
            if released:
                self.pinching = False
                self.pinch_frames = 0
                self.anchor = None
                self.released_at = t
            return
        self.pinch_frames = self.pinch_frames + 1 if hand and hand.gap < PINCH_ON else 0
        if self.pinch_frames >= PINCH_FRAMES:
            self.pinching = True
            self.fired = False
            self.anchor = (hand.x, hand.y)

    def _drag(self, hand: Hand) -> str | None:
        dx, dy = hand.x - self.anchor[0], hand.y - self.anchor[1]
        if abs(dx) >= DRAG_DISTANCE and abs(dx) >= AXIS_RATIO * abs(dy):
            return "swipe_right" if dx > 0 else "swipe_left"
        if abs(dy) >= DRAG_DISTANCE and abs(dy) >= AXIS_RATIO * abs(dx):
            return "swipe_down" if dy > 0 else "swipe_up"
        return None

    def _still(self) -> bool:
        if len(self.track) < 2:
            return False
        last = self.track[-1]
        return all(math.hypot(s.x - last.x, s.y - last.y) < HOLD_DRIFT for s in self.track)


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
                hand = (hand_from_landmarks(result.hand_landmarks[0], result.hand_world_landmarks[0])
                        if result.hand_landmarks else None)
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
                                                             round(hand.size, 4), hand.open, round(hand.gap, 3)]}) + "\n")
        h, w = frame.shape[:2]
        for points in result.hand_landmarks:
            for p in points:
                cv2.circle(frame, (int(p.x * w), int(p.y * h)), 3, (255, 255, 255), -1)
        status = f"{fps:4.1f} fps"
        if hand and detector.anchor:
            ax, ay = detector.anchor
            cv2.line(frame, (int(ax * w), int(ay * h)), (int(hand.x * w), int(hand.y * h)), (0, 200, 255), 3)
            status += f"  drag dx {hand.x - ax:+.2f} dy {hand.y - ay:+.2f} (need {DRAG_DISTANCE})"
        cv2.putText(frame, status, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        if hand:
            color = (0, 200, 255) if detector.pinching else (0, 0, 255) if detector.palm else (
                (0, 200, 0) if hand.open else (160, 160, 160))
            cv2.circle(frame, (int(hand.x * w), int(hand.y * h)), 12, color, 2)
            label = result.gestures[0][0].category_name if result.gestures else ""
            cv2.putText(frame, f"size {hand.size:.2f} gap {hand.gap:.2f} open {hand.open} {label}", (10, 24),
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
