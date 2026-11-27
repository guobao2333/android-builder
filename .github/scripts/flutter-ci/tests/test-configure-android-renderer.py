#!/usr/bin/env python3
"""Regression tests for temporary Flutter Android renderer configuration."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "configure-android-renderer.py"
SPEC = importlib.util.spec_from_file_location("configure_android_renderer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ConfigureAndroidRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flutter-renderer-ci-")
        self.root = Path(self.temp.name)
        self.manifest = self.root / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
        self.manifest.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self, content: str) -> None:
        self.manifest.write_text(content, encoding="utf-8")

    def test_skia_setting_is_inserted_without_reformatting_other_content(self):
        original = '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n    <application android:label="Aisupass">\n    </application>\n</manifest>\n'
        self.write_manifest(original)
        self.assertTrue(MODULE.configure_renderer(self.root, "skia"))
        updated = self.manifest.read_text(encoding="utf-8")
        self.assertIn('android:name="io.flutter.embedding.android.EnableImpeller" android:value="false"', updated)
        self.assertIn('android:label="Aisupass"', updated)

    def test_existing_renderer_value_is_updated(self):
        self.write_manifest(
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '  <application>\n'
            '    <meta-data android:name="io.flutter.embedding.android.EnableImpeller" android:value="true" />\n'
            '  </application>\n</manifest>\n'
        )
        self.assertTrue(MODULE.configure_renderer(self.root, "skia"))
        updated = self.manifest.read_text(encoding="utf-8")
        self.assertEqual(updated.count("EnableImpeller"), 1)
        self.assertIn('android:value="false"', updated)

    def test_already_selected_renderer_is_idempotent(self):
        original = (
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '  <application>\n'
            '    <meta-data android:name="io.flutter.embedding.android.EnableImpeller" android:value="false" />\n'
            '  </application>\n</manifest>\n'
        )
        self.write_manifest(original)
        self.assertFalse(MODULE.configure_renderer(self.root, "skia"))
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), original)

    def test_missing_application_is_reported(self):
        self.write_manifest('<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n')
        with self.assertRaisesRegex(ValueError, "does not contain an <application>"):
            MODULE.configure_renderer(self.root, "skia")

    def test_invalid_backend_is_rejected(self):
        self.write_manifest('<manifest><application /></manifest>\n')
        with self.assertRaisesRegex(ValueError, "Unsupported Android renderer"):
            MODULE.configure_renderer(self.root, "vulkan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
