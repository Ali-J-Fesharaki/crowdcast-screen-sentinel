"""Unit tests for Sentinel diagnostic evaluation."""

import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.sentinel_core import SentinelManager


class TestSentinelDiagnostics(unittest.TestCase):
    def setUp(self):
        self.mock_bridge = MagicMock()
        self.sentinel = SentinelManager(self.mock_bridge)

    def test_active_blackout_when_focused_app_untracked(self):
        # Setup: focused app is Nautilus, but not in target_apps
        self.mock_bridge.read_config_raw.return_value = '[capture]\ntarget_apps = ["code"]\n'
        self.mock_bridge.read_config.return_value = {
            "capture": {
                "target_apps": ["code"],
                "capture_all": False,
                "blank_video_on_untracked_app": True,
            }
        }
        self.mock_bridge.get_agent_status.return_value = {"running": True, "pid": 1234}
        self.mock_bridge.get_open_windows.return_value = [
            {"window_id": 100, "pid": 500, "wm_class": "org.gnome.Nautilus", "title": "Downloads"},
            {"window_id": 200, "pid": 600, "wm_class": "code", "title": "VS Code"},
        ]
        self.mock_bridge.get_focused_window.return_value = {
            "window_id": 100, "pid": 500, "wm_class": "org.gnome.Nautilus", "title": "Downloads"
        }
        self.sentinel.luma_sampler.sample_latest_frame = MagicMock(return_value={"success": True, "mean": 0.0, "is_black": True})

        state = self.sentinel.get_full_state()
        self.assertTrue(state["has_active_blackout"])

        nautilus_eval = next(w for w in state["windows"] if w["wm_class"] == "org.gnome.Nautilus")
        self.assertEqual(nautilus_eval["blackout_status"], "ACTIVE_BLACKOUT")
        self.assertTrue(nautilus_eval["can_one_click_fix"])

        code_eval = next(w for w in state["windows"] if w["wm_class"] == "code")
        self.assertEqual(code_eval["blackout_status"], "SAFE")

    def test_capture_all_causes_system_wide_blackout(self):
        self.mock_bridge.read_config_raw.return_value = '[capture]\ncapture_all = true\n'
        self.mock_bridge.read_config.return_value = {
            "capture": {
                "target_apps": ["code"],
                "capture_all": True,
            }
        }
        self.mock_bridge.get_agent_status.return_value = {"running": True, "pid": 1234}
        self.mock_bridge.get_open_windows.return_value = [
            {"window_id": 200, "pid": 600, "wm_class": "code", "title": "VS Code"},
        ]
        self.mock_bridge.get_focused_window.return_value = None
        self.sentinel.luma_sampler.sample_latest_frame = MagicMock(return_value={"success": True, "mean": 0.0, "is_black": True})

        state = self.sentinel.get_full_state()
        self.assertTrue(state["has_active_blackout"])
        self.assertEqual(state["windows"][0]["blackout_status"], "ACTIVE_BLACKOUT")


if __name__ == "__main__":
    unittest.main()
