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
from ndk_versions import resolve_ndk_pkg_revision, resolve_ndk_revision, resolve_preview_download
SPEC.loader.exec_module(MODULE)


class ResolveNdkTests(unittest.TestCase):
    def test_gradle_base_revision_maps_to_beta_pkg_revision(self):
        self.assertEqual(resolve_ndk_revision("29.0.13113456"), "29.0.13113456")
        self.assertEqual(
            resolve_ndk_pkg_revision("29.0.13113456"),
            "29.0.13113456-beta1",
        )

    def test_stable_alias_keeps_stable_pkg_revision(self):
        self.assertEqual(resolve_ndk_revision("r29"), "29.0.14033849")
        self.assertEqual(resolve_ndk_pkg_revision("r29"), "29.0.14033849")

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

    def test_flutter_managed_ndk_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "pubspec.yaml", "name: sample\ndependencies:\n  flutter:\n    sdk: flutter\n")
            self.write(
                root,
                "android/app/build.gradle.kts",
                "android { ndkVersion = flutter.ndkVersion }",
            )
            self.assertEqual(MODULE.detect_ndk_versions(root), ([], []))

    def test_no_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "app/build.gradle", "android { compileSdk 35 }")
            self.assertEqual(MODULE.detect_ndk_versions(root), ([], []))


 
class NdkPreviewMetadataTests(unittest.TestCase):
    def test_linux_preview_archive_uses_official_url_and_sha1(self):
        metadata = resolve_preview_download("29.0.13113456", "linux")
        self.assertEqual(
            metadata,
            {
                "pkg_revision": "29.0.13113456-beta1",
                "url": "https://dl.google.com/android/repository/android-ndk-r29-beta1-linux.zip",
                "sha1": "ec2d8801e42009edf66be853c1bab9ba216378f9",
                "format": "zip",
            },
        )

    def test_macos_preview_archive_uses_official_url_and_sha1(self):
        metadata = resolve_preview_download("29.0.13113456", "darwin")
        self.assertEqual(
            metadata,
            {
                "pkg_revision": "29.0.13113456-beta1",
                "url": "https://dl.google.com/android/repository/android-ndk-r29-beta1-darwin.dmg",
                "sha1": "b3a8e0d8147de981478c8edefe4036440910ee46",
                "format": "dmg",
            },
        )

    def test_stable_ndk_does_not_use_preview_archive(self):
        self.assertIsNone(resolve_preview_download("r29", "linux"))

    def test_preview_archive_rejects_unmapped_platform(self):
        with self.assertRaises(ValueError):
            resolve_preview_download("29.0.13113456", "windows")


if __name__ == "__main__":
    unittest.main(verbosity=2)
