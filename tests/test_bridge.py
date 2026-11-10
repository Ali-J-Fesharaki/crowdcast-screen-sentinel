"""Unit tests for config serialization and D-Bus parsing."""

import ast
import re
import sys
from pathlib import Path
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.sentinel_core import (
    update_toml_bool,
    update_toml_int,
    update_toml_target_apps,
)


class TestConfigSerialization(unittest.TestCase):
    def setUp(self):
        self.sample_toml = """[capture]
target_apps = [
  "code",
  "firefox"
]
capture_all = true
blank_video_on_untracked_app = true
idle_timeout_secs = 120

[upload]
delete_after_upload = false
"""

    def test_update_target_apps(self):
        new_apps = ["code", "firefox", "org.gnome.Nautilus"]
        updated = update_toml_target_apps(self.sample_toml, new_apps)
        self.assertIn('"org.gnome.Nautilus"', updated)
        self.assertIn('"code"', updated)
        self.assertIn('"firefox"', updated)
        self.assertIn("[upload]", updated)

    def test_update_bool(self):
        res1 = update_toml_bool(self.sample_toml, "capture_all", False)
        self.assertIn("capture_all = false", res1)

        res2 = update_toml_bool(self.sample_toml, "blank_video_on_untracked_app", False)
        self.assertIn("blank_video_on_untracked_app = false", res2)

    def test_update_int(self):
        res = update_toml_int(self.sample_toml, "idle_timeout_secs", 600)
        self.assertIn("idle_timeout_secs = 600", res)

    def test_dbus_tuple_parser(self):
        raw_dbus = "([(uint64 733822501, 2443, 'org.gnome.Nautilus', 'Downloads'), (uint64 733822544, 22899, 'firefox', 'Mozilla Firefox')],)"
        cleaned = re.sub(r"uint64\s+", "", raw_dbus)
        data = ast.literal_eval(cleaned)
        windows = data[0]
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0][0], 733822501)
        self.assertEqual(windows[0][2], "org.gnome.Nautilus")
        self.assertEqual(windows[1][2], "firefox")


if __name__ == "__main__":
    unittest.main()
