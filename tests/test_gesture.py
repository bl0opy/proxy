import unittest

from proxy.gesture import Detector, Hand

FPS = 30


def run(detector: Detector, path, t0: float = 0.0) -> tuple[list[str], float]:
    events, t = [], t0
    for hand in path:
        events += detector.update(t, hand)
        t += 1 / FPS
    return events, t


def hold(x, y, seconds, open_=True):
    return [Hand(x, y, 0.15, open_)] * int(seconds * FPS)


def move(x0, y0, x1, y1, seconds, open_=True):
    n = int(seconds * FPS)
    return [Hand(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, 0.15, open_) for i in range(n + 1)]


def gone(seconds):
    return [None] * int(seconds * FPS)


class DetectorTest(unittest.TestCase):
    def test_palm_hold_starts_and_lowering_ends(self):
        d = Detector()
        events, t = run(d, hold(0.5, 0.4, 0.8))
        self.assertEqual(events, ["palm_start"])
        events, _ = run(d, move(0.5, 0.4, 0.5, 0.95, 0.2) + gone(0.5), t)
        self.assertEqual(events, ["palm_end"])

    def test_swipes(self):
        for path, expected in [((0.3, 0.4, 0.7, 0.4), "swipe_right"), ((0.7, 0.4, 0.3, 0.4), "swipe_left"),
                               ((0.5, 0.6, 0.5, 0.2), "swipe_up")]:
            d = Detector()
            _, t = run(d, hold(*path[:2], 0.3))
            events, _ = run(d, move(*path, 0.2) + hold(*path[2:], 0.1), t)
            self.assertEqual(events, [expected], expected)

    def test_swipe_down_needs_hand_to_stay(self):
        d = Detector()
        _, t = run(d, hold(0.5, 0.3, 0.3))
        events, _ = run(d, move(0.5, 0.3, 0.5, 0.7, 0.2) + hold(0.5, 0.7, 0.3), t)
        self.assertEqual(events, ["swipe_down"])

        d = Detector()
        _, t = run(d, hold(0.5, 0.3, 0.3))
        events, _ = run(d, move(0.5, 0.3, 0.5, 0.95, 0.2) + gone(0.5), t)
        self.assertEqual(events, [])

    def test_raising_hand_into_frame_is_not_swipe_up(self):
        d = Detector()
        events, _ = run(d, gone(0.5) + move(0.5, 0.95, 0.5, 0.4, 0.15) + hold(0.5, 0.4, 0.1))
        self.assertNotIn("swipe_up", events)

    def test_swipe_during_palm_ends_it_and_needs_rearm(self):
        d = Detector()
        events, t = run(d, hold(0.5, 0.4, 0.8))
        self.assertEqual(events, ["palm_start"])
        events, t = run(d, move(0.5, 0.4, 0.5, 0.1, 0.2) + hold(0.5, 0.1, 1.0), t)
        self.assertEqual(events, ["swipe_up"])
        events, t = run(d, hold(0.5, 0.1, 0.5, open_=False) + hold(0.5, 0.1, 0.8), t)
        self.assertEqual(events, ["palm_start"])

    def test_return_stroke_is_ignored(self):
        d = Detector()
        _, t = run(d, hold(0.3, 0.4, 0.3))
        events, _ = run(d, move(0.3, 0.4, 0.7, 0.4, 0.2) + move(0.7, 0.4, 0.3, 0.4, 0.3) + hold(0.3, 0.4, 0.2), t)
        self.assertEqual(events, ["swipe_right"])

    def test_closed_hand_does_not_swipe_or_listen(self):
        d = Detector()
        events, _ = run(d, hold(0.3, 0.4, 0.8, False) + move(0.3, 0.4, 0.7, 0.4, 0.2, False))
        self.assertEqual(events, [])

    def test_small_background_hand_is_ignored(self):
        d = Detector()
        events, _ = run(d, [Hand(0.5, 0.4, 0.03, True)] * 30)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
