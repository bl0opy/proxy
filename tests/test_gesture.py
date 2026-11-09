import unittest
from types import SimpleNamespace

from proxy.gesture import Detector, Hand, hand_from_landmarks

FPS = 30
PINCHED, RELEASED = 0.1, 1.0


def run(detector: Detector, path, t0: float = 0.0) -> tuple[list[str], float]:
    events, t = [], t0
    for hand in path:
        events += detector.update(t, hand)
        t += 1 / FPS
    return events, t


def hold(x, y, seconds, open_=True, gap=RELEASED):
    return [Hand(x, y, 0.15, open_, gap)] * int(seconds * FPS)


def move(x0, y0, x1, y1, seconds, open_=False, gap=PINCHED):
    n = int(seconds * FPS)
    return [Hand(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, 0.15, open_, gap) for i in range(n + 1)]


def pinch(x, y, seconds=0.2):
    return hold(x, y, seconds, False, PINCHED)


def release(x, y, seconds=0.2):
    return hold(x, y, seconds, False)


def gone(seconds):
    return [None] * int(seconds * FPS)


class PalmTest(unittest.TestCase):
    def test_hold_starts_and_lowering_ends(self):
        d = Detector()
        events, t = run(d, hold(0.5, 0.4, 0.8))
        self.assertEqual(events, ["palm_start"])
        events, _ = run(d, move(0.5, 0.4, 0.5, 0.95, 0.2, True, RELEASED) + gone(0.5), t)
        self.assertEqual(events, ["palm_end"])

    def test_small_background_hand_is_ignored(self):
        events, _ = run(Detector(), [Hand(0.5, 0.4, 0.03, True)] * 30)
        self.assertEqual(events, [])

    def test_pinch_drag_up_while_listening_swipes_without_palm_end(self):
        d = Detector()
        events, t = run(d, hold(0.5, 0.4, 0.8))
        self.assertEqual(events, ["palm_start"])
        events, _ = run(d, pinch(0.5, 0.4, 0.4) + move(0.5, 0.4, 0.5, 0.2, 0.2), t)
        self.assertEqual(events, ["swipe_up"])

    def test_open_hand_after_undragged_pinch_does_not_listen(self):
        events, _ = run(Detector(), pinch(0.5, 0.5, 0.5) + hold(0.5, 0.5, 1.0))
        self.assertEqual(events, [])

    def test_no_accidental_listen_after_swipe_until_hand_rests(self):
        d = Detector()
        events, t = run(d, pinch(0.5, 0.5) + move(0.5, 0.5, 0.8, 0.5, 0.2) + hold(0.8, 0.5, 1.0))
        self.assertEqual(events, ["swipe_right"])
        events, _ = run(d, gone(0.5) + hold(0.8, 0.5, 0.8), t)
        self.assertEqual(events, ["palm_start"])


class DragTest(unittest.TestCase):
    def test_four_directions(self):
        for end, expected in [((0.8, 0.5), "swipe_right"), ((0.2, 0.5), "swipe_left"),
                              ((0.5, 0.2), "swipe_up"), ((0.5, 0.8), "swipe_down")]:
            events, _ = run(Detector(), pinch(0.5, 0.5) + move(0.5, 0.5, *end, 0.3))
            self.assertEqual(events, [expected], expected)

    def test_one_swipe_per_pinch(self):
        path = pinch(0.2, 0.5) + move(0.2, 0.5, 0.8, 0.5, 0.5) + move(0.8, 0.5, 0.2, 0.5, 0.5)
        events, _ = run(Detector(), path)
        self.assertEqual(events, ["swipe_right"])

    def test_moving_back_released_does_nothing_and_next_pinch_works(self):
        path = (pinch(0.3, 0.5) + move(0.3, 0.5, 0.6, 0.5, 0.2) + release(0.6, 0.5)
                + move(0.6, 0.5, 0.3, 0.5, 0.2, False, RELEASED) + pinch(0.3, 0.5)
                + move(0.3, 0.5, 0.6, 0.5, 0.2))
        events, _ = run(Detector(), path)
        self.assertEqual(events, ["swipe_right", "swipe_right"])

    def test_big_move_without_pinch_does_nothing(self):
        path = release(0.2, 0.5) + move(0.2, 0.5, 0.8, 0.5, 0.2, False, RELEASED)
        events, _ = run(Detector(), path)
        self.assertEqual(events, [])

    def test_short_drag_does_nothing(self):
        events, _ = run(Detector(), pinch(0.5, 0.5) + move(0.5, 0.5, 0.58, 0.5, 0.2) + release(0.58, 0.5))
        self.assertEqual(events, [])

    def test_diagonal_does_nothing(self):
        events, _ = run(Detector(), pinch(0.5, 0.5) + move(0.5, 0.5, 0.65, 0.65, 0.2) + release(0.65, 0.65))
        self.assertEqual(events, [])

    def test_single_pinch_frame_does_not_start(self):
        path = release(0.3, 0.5) + [Hand(0.3, 0.5, 0.15, False, PINCHED)] + move(0.3, 0.5, 0.7, 0.5, 0.2, False, RELEASED)
        events, _ = run(Detector(), path)
        self.assertEqual(events, [])

    def test_gap_between_thresholds_keeps_pinch(self):
        path = pinch(0.3, 0.5) + move(0.3, 0.5, 0.6, 0.5, 0.2, False, 0.4)
        events, _ = run(Detector(), path)
        self.assertEqual(events, ["swipe_right"])

    def test_brief_tracking_dropout_keeps_pinch(self):
        path = pinch(0.3, 0.5) + gone(0.1) + move(0.3, 0.5, 0.6, 0.5, 0.2)
        events, _ = run(Detector(), path)
        self.assertEqual(events, ["swipe_right"])

    def test_brief_gap_spike_mid_drag_keeps_pinch(self):
        spike = [Hand(0.4, 0.5, 0.15, False, 0.65)] * 2
        path = pinch(0.3, 0.5) + move(0.3, 0.5, 0.4, 0.5, 0.1) + spike + move(0.4, 0.5, 0.6, 0.5, 0.1)
        events, _ = run(Detector(), path)
        self.assertEqual(events, ["swipe_right"])

    def test_losing_hand_ends_pinch(self):
        d = Detector()
        run(d, pinch(0.3, 0.5) + gone(0.5))
        self.assertFalse(d.pinching)


class LandmarksTest(unittest.TestCase):
    def points(self, thumb_x, tip_y=0.3):
        points = [SimpleNamespace(x=0.5, y=0.8, z=0.0) for _ in range(21)]
        points[9] = SimpleNamespace(x=0.5, y=0.6, z=0.0)
        points[4] = SimpleNamespace(x=thumb_x, y=0.4, z=0.0)
        points[8] = SimpleNamespace(x=0.5, y=0.4, z=0.0)
        points[12] = SimpleNamespace(x=0.5, y=tip_y, z=0.0)
        return points

    def test_gap_is_relative_to_hand_size(self):
        self.assertAlmostEqual(hand_from_landmarks(self.points(0.52)).gap, 0.1)
        self.assertAlmostEqual(hand_from_landmarks(self.points(0.7)).gap, 1.0)

    def test_finger_tips_do_not_move_the_tracked_point(self):
        self.assertEqual(hand_from_landmarks(self.points(0.5, 0.3)).y, hand_from_landmarks(self.points(0.5, 0.7)).y)


if __name__ == "__main__":
    unittest.main()
