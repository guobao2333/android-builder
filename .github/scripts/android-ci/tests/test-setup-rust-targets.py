#!/usr/bin/env python3
"""Tests for Android Rust target detection and setup."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "setup-rust-targets.py"
SPEC = importlib.util.spec_from_file_location("setup_rust_targets", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SetupRustTargetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="android-rust-targets-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_detects_explicit_android_target_from_gradle_task(self) -> None:
        self.write("assistant/src/main/jni/vrext/Cargo.toml", "[package]\nname='vrext'\n")
        self.write("assistant/build.gradle", """
            tasks.register('buildNative', Exec) {
                commandLine('cargo', 'build', '--target', 'aarch64-linux-android')
            }
        """)
        result = MODULE.detect_android_targets(self.root)
        self.assertEqual(result["targets"], ["aarch64-linux-android"])
        self.assertEqual(result["manifests"], ["assistant/src/main/jni/vrext/Cargo.toml"])

    def test_detects_target_from_cargo_config(self) -> None:
        self.write("native/Cargo.toml", "[package]\nname='native'\n")
        self.write("native/.cargo/config.toml", """
            [build]
            target = "aarch64-linux-android"
        """)
        result = MODULE.detect_android_targets(self.root)
        self.assertEqual(result["targets"], ["aarch64-linux-android"])

    def test_maps_android_abi_filters_to_rust_targets(self) -> None:
        self.write("native/Cargo.toml", "[package]\nname='native'\n")
        self.write("app/build.gradle", """
            android {
                defaultConfig {
                    ndk {
                        abiFilters 'arm64-v8a', 'x86_64'
                    }
                }
            }
        """)
        result = MODULE.detect_android_targets(self.root)
        self.assertEqual(
            result["targets"],
            ["aarch64-linux-android", "x86_64-linux-android"],
        )

    def test_maps_cargo_ndk_abi_argument(self) -> None:
        self.write("native/Cargo.toml", "[package]\nname='native'\n")
        self.write("build-native.sh", "cargo ndk -t arm64-v8a build\n")
        result = MODULE.detect_android_targets(self.root)
        self.assertEqual(result["targets"], ["aarch64-linux-android"])

    def test_no_cargo_manifest_skips_detection(self) -> None:
        self.write("app/build.gradle", "abiFilters 'arm64-v8a'\n")
        result = MODULE.detect_android_targets(self.root)
        self.assertEqual(result["manifests"], [])
        self.assertEqual(result["targets"], [])

    def test_cargo_without_android_target_does_not_guess(self) -> None:
        self.write("tools/Cargo.toml", "[package]\nname='host-tool'\n")
        result = MODULE.detect_android_targets(self.root)
        self.assertEqual(result["targets"], [])
        self.assertIn("no Android Rust target", result["source"])

    def test_install_targets_adds_missing_target_and_verifies_core(self) -> None:
        manifest = "assistant/native/Cargo.toml"
        self.write(manifest, "[package]\nname='native'\n")
        libdir = self.root / "rustlib" / "aarch64"
        libdir.mkdir(parents=True)
        (libdir / "libcore-test.rlib").write_text("", encoding="utf-8")

        calls: list[tuple[list[str], Path]] = []

        def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            calls.append((command, cwd))
            if command[1:4] == ["target", "list", "--installed"]:
                return subprocess.CompletedProcess(command, 0, "x86_64-unknown-linux-gnu\n", "")
            if command[1:3] == ["target", "add"]:
                return subprocess.CompletedProcess(command, 0, "installed\n", "")
            if command[1:4] == ["--print", "target-libdir", "--target"]:
                return subprocess.CompletedProcess(command, 0, str(libdir) + "\n", "")
            return subprocess.CompletedProcess(command, 1, "", "unexpected command")

        with patch.object(MODULE, "find_rustup", return_value="/fake/rustup"), \
                patch.object(MODULE, "run", side_effect=fake_run):
            result = MODULE.install_targets(self.root, [manifest], ["aarch64-linux-android"])

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["installed"], ["aarch64-linux-android"])
        self.assertTrue(any(call[0][1:3] == ["target", "add"] for call in calls))

    def test_install_targets_does_not_call_rustup_when_no_target_is_needed(self) -> None:
        with patch.object(MODULE, "find_rustup") as find_rustup:
            result = MODULE.install_targets(self.root, [], [])
        find_rustup.assert_not_called()
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
