#!/usr/bin/env python3
"""Regression tests for resolve-ndk.py."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "resolve-ndk.py"
SPEC = importlib.util.spec_from_file_location("resolve_ndk", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
import sys
sys.path.insert(0, str(SCRIPT.parent))
SPEC.loader.exec_module(MODULE)


class ResolveNdkTests(unittest.TestCase):
    def write(self, root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_groovy_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", 'android { ndkVersion "26.1.10909125" }')
            self.assertEqual(MODULE.detect_ndk_versions(root), (["26.1.10909125"], []))

    def test_kotlin_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle.kts", 'android { ndkVersion = "27.3.13750724" }')
            self.assertEqual(MODULE.detect_ndk_versions(root), (["27.3.13750724"], []))

    def test_root_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "build.gradle", 'ext.ndkVersion = "25.2.9519653"')
            self.write(root, "app/build.gradle", "android { ndkVersion rootProject.ext.ndkVersion }")
            self.assertEqual(MODULE.detect_ndk_versions(root), (["25.2.9519653"], []))

    def test_gradle_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "gradle.properties", "android.ndkVersion=24.0.8215888")
            self.write(root, "app/build.gradle", 'android { ndkVersion = project.property("android.ndkVersion") }')
            self.assertEqual(MODULE.detect_ndk_versions(root), (["24.0.8215888"], []))

    def test_version_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "gradle/libs.versions.toml", '[versions]\nndk = "28.2.13676358"\n')
            self.write(root, "app/build.gradle.kts", "android { ndkVersion = libs.versions.ndk.get() }")
            self.assertEqual(MODULE.detect_ndk_versions(root), (["28.2.13676358"], []))

    def test_conflicting_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", 'android { ndkVersion = "25.2.9519653" }')
            self.write(root, "native/build.gradle", 'android { ndkVersion = "26.1.10909125" }')
            versions, unresolved = MODULE.detect_ndk_versions(root)
            self.assertEqual(len(versions), 2)
            self.assertFalse(unresolved)

    def test_unresolved_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", "android { ndkVersion = libs.versions.ndk.get() }")
            versions, unresolved = MODULE.detect_ndk_versions(root)
            self.assertFalse(versions)
            self.assertTrue(unresolved)

    def test_no_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", "android { compileSdk 35 }")
            self.assertEqual(MODULE.detect_ndk_versions(root), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
