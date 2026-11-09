import unittest
from types import SimpleNamespace
from unittest import mock

from proxy import mac


class MinimizedTest(unittest.TestCase):
    def setUp(self):
        mac._minimized.clear()
        self.state = {}
        patches = [
            mock.patch.object(mac, "_ax", lambda w, a: self.state.get(w)),
            mock.patch.object(mac.AX, "AXUIElementSetAttributeValue",
                              lambda w, a, v: self.state.__setitem__(w, v)),
            mock.patch.object(mac.AX, "AXUIElementPerformAction"),
            mock.patch.object(mac.AppKit, "NSRunningApplication"),
            mock.patch.object(mac, "frontmost_app", lambda: SimpleNamespace(processIdentifier=lambda: 7)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def minimize(self, window):
        with mock.patch.object(mac, "_focused_window", lambda: window):
            mac.minimize_window()

    def test_restores_most_recent_first(self):
        self.minimize("a")
        self.minimize("b")
        mac.restore_minimized()
        self.assertEqual(self.state, {"a": True, "b": False})
        mac.restore_minimized()
        self.assertFalse(self.state["a"])
        self.assertFalse(mac.has_minimized())

    def test_skips_windows_already_restored_or_closed(self):
        self.minimize("a")
        self.minimize("b")
        self.minimize("c")
        self.state["c"] = False
        del self.state["b"]
        mac.restore_minimized()
        self.assertFalse(self.state["a"])
        self.assertFalse(mac.has_minimized())

    def test_nothing_to_restore(self):
        self.assertFalse(mac.has_minimized())
        with self.assertRaises(mac.MacError):
            mac.restore_minimized()


class MissionControlTest(unittest.TestCase):
    def check(self, windows):
        with mock.patch.object(mac.Quartz, "CGWindowListCopyWindowInfo", lambda *a: windows):
            return mac.in_mission_control()

    def test_dock_layer_marks_mission_control(self):
        self.assertTrue(self.check([{"kCGWindowOwnerName": "Dock", "kCGWindowLayer": 18}]))
        self.assertFalse(self.check([{"kCGWindowOwnerName": "Dock", "kCGWindowLayer": 20}]))
        self.assertFalse(self.check([{"kCGWindowOwnerName": "Safari", "kCGWindowLayer": 18}]))


if __name__ == "__main__":
    unittest.main()
