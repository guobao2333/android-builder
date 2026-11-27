#!/usr/bin/env python3
"""Regression tests for Flutter SDK resolution."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
import importlib.util

SPEC = importlib.util.spec_from_file_location("resolve_flutter", SCRIPT_DIR / "resolve-flutter.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ResolveFlutterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flutter-ci-resolver-")
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / "releases.json"
        self.manifest = {
            "releases": [
                {
                    "channel": "stable",
                    "version": "3.50.1",
                    "dart_sdk_version": "3.14.0",
                    "dart_sdk_arch": "x64",
                    "hash": "latest-hash",
                },
                {
                    "channel": "stable",
                    "version": "3.47.8",
                    "dart_sdk_version": "3.13.7",
                    "dart_sdk_arch": "x64",
                    "hash": "737ba8f885dc774b53b442759999a312c9461e4e",
                },
                {
                    "channel": "stable",
                    "version": "3.47.7",
                    "dart_sdk_version": "3.13.5",
                    "dart_sdk_arch": "x64",
                    "hash": "older-hash",
                },
            ]
        }
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def resolve(self, requested: str = "auto") -> dict[str, str]:
        return MODULE.resolve_flutter(self.root, requested, str(self.manifest_path))

    def test_metadata_revision_pins_matching_stable_release(self):
        self.write(
            ".metadata",
            'version:\n  revision: "737ba8f885dc774b53b442759999a312c9461e4e"\n  channel: "stable"\n',
        )
        self.write("pubspec.lock", 'sdks:\n  dart: ">=3.13.7 <4.0.0"\n  flutter: ">=3.47.0"\n')
        result = self.resolve()
        self.assertEqual(result["flutter_channel"], "stable")
        self.assertEqual(result["flutter_version"], "3.47.8")
        self.assertEqual(result["flutter_dart_version"], "3.13.7")
        self.assertEqual(result["flutter_version_source"], ".metadata pinned revision")

    def test_fvm_config_takes_precedence_over_metadata(self):
        self.write(".fvmrc", '{"flutter":"3.47.8"}')
        self.write(".metadata", 'version:\n  revision: "latest-hash"\n  channel: "stable"\n')
        self.write("pubspec.lock", 'sdks:\n  dart: ">=3.13.7 <4.0.0"\n')
        result = self.resolve()
        self.assertEqual(result["flutter_version"], "3.47.8")
        self.assertEqual(result["flutter_version_source"], ".fvmrc")

    def test_exact_pubspec_flutter_version_is_used(self):
        self.write("pubspec.yaml", "environment:\n  sdk: ^3.13.7\n  flutter: 3.47.8\n")
        result = self.resolve()
        self.assertEqual(result["flutter_version"], "3.47.8")
        self.assertEqual(result["flutter_version_source"], "pubspec.yaml environment.flutter")

    def test_unpinned_project_uses_latest_stable(self):
        result = self.resolve()
        self.assertEqual(result["flutter_version"], "3.50.1")
        self.assertEqual(result["flutter_version_source"], "latest stable (no project pin found")

    def test_flutter_release_below_locked_dart_minimum_fails(self):
        self.write(".metadata", 'version:\n  revision: "older-hash"\n  channel: "stable"\n')
        self.write("pubspec.lock", 'sdks:\n  dart: ">=3.13.7 <4.0.0"\n')
        with self.assertRaisesRegex(ValueError, "below the project's locked minimum"):
            self.resolve()

    def test_unknown_metadata_revision_fails_instead_of_using_latest(self):
        self.write(".metadata", 'version:\n  revision: "unknown-revision"\n  channel: "stable"\n')
        with self.assertRaisesRegex(ValueError, "no Linux x64 release matching revision"):
            self.resolve()

    def test_manual_channel_and_exact_version(self):
        channel = self.resolve("stable")
        version = self.resolve("3.47.8")
        self.assertEqual(channel["flutter_version"], "3.50.1")
        self.assertEqual(version["flutter_version"], "3.47.8")
        self.assertEqual(version["flutter_version_source"], "manual version selection")


if __name__ == "__main__":
    unittest.main(verbosity=2)
