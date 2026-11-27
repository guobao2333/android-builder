#!/usr/bin/env python3
"""Tests for automatic Android project classification."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "detect-project.py"
SPEC = importlib.util.spec_from_file_location("detect_project", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DetectProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="project-router-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_flutter_project_is_detected_before_nested_gradle(self):
        self.write("pubspec.yaml", "name: sample\ndependencies:\n  flutter:\n    sdk: flutter\n")
        self.write("android/settings.gradle", "pluginManagement {}")
        self.write("android/app/build.gradle", "plugins { id 'com.android.application' }")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "flutter")

    def test_godot_project_is_detected(self):
        self.write("project.godot", 'config/name="Sample"\n')
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "godot")

    def test_root_android_application_is_detected(self):
        self.write("settings.gradle", "include ':app'")
        self.write("app/build.gradle", "plugins { id 'com.android.application' }")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "android")

    def test_android_library_is_not_mistaken_for_apk_application(self):
        self.write("settings.gradle", "include ':library'")
        self.write("library/build.gradle", "plugins { id 'com.android.library' }")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "unsupported:android-library")

    def test_react_native_is_not_misrouted_to_plain_gradle(self):
        self.write("package.json", '{"dependencies":{"react-native":"^0.80.0"}}')
        self.write("android/settings.gradle", "include ':app'")
        self.write("android/app/build.gradle", "plugins { id 'com.android.application' }")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "unsupported:react-native")

    def test_capacitor_is_not_misrouted_to_plain_gradle(self):
        self.write("package.json", '{"dependencies":{"@capacitor/android":"^7.0.0"}}')
        self.write("android/settings.gradle", "include ':app'")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "unsupported:capacitor")

    def test_unity_project_is_not_misrouted_to_plain_gradle(self):
        self.write("ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.0.0f1\n")
        self.write("Assets/.keep", "")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "unsupported:unity")

    def test_unknown_project_is_reported(self):
        self.write("README.md", "hello")
        self.assertEqual(MODULE.resolve(self.root)["project_type"], "unknown")

    def test_explicit_adapter_must_match_detected_type(self):
        self.write("project.godot", 'config/name="Sample"\n')
        with self.assertRaisesRegex(ValueError, "Requested adapter 'android'"):
            MODULE.resolve(self.root, "android")


if __name__ == "__main__":
    unittest.main(verbosity=2)
