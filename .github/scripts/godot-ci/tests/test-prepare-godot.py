#!/usr/bin/env python3
"""Regression tests for Godot project detection and Android preset preparation."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "prepare-godot.py"
SPEC = importlib.util.spec_from_file_location("prepare_godot", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PrepareGodotTests(unittest.TestCase):
    def write(self, root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_fortunemill_dotnet_project_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "project.godot", 'config/name="Fortune Mill"\nconfig/features=PackedStringArray("4.5", "C#")\n')
            self.write(
                root,
                "FortuneMill.csproj",
                '<Project Sdk="Godot.NET.Sdk/4.5.1"><PropertyGroup><TargetFramework>net80</TargetFramework></PropertyGroup></Project>',
            )
            values = MODULE.detect_project(root, "auto")
            self.assertEqual(values, ("4.5.1", True, "8.0.x", "Fortune Mill"))

    def test_generates_android_arm64_preset_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "project.godot", 'config/name="Fortune Mill"\n')
            name = MODULE.ensure_android_preset(root, "auto", "com.example.fortunemill")
            preset = (root / "export_presets.cfg").read_text(encoding="utf-8")
            self.assertEqual(name, "Android CI")
            self.assertIn('platform="Android"', preset)
            self.assertIn('architectures/arm64-v8a=true', preset)
            self.assertIn('package/unique_name="com.example.fortunemill"', preset)

    def test_reuses_existing_android_preset_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "project.godot", 'config/name="Sample"\n')
            existing = '[preset.0]\nname="Android"\nplatform="Android"\n'
            self.write(root, "export_presets.cfg", existing)
            self.assertEqual(MODULE.ensure_android_preset(root, "auto", "com.example.sample"), "Android")
            self.assertEqual((root / "export_presets.cfg").read_text(encoding="utf-8"), existing)

    def test_explicit_preset_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "project.godot", 'config/name="Sample"\n')
            with self.assertRaises(ValueError):
                MODULE.ensure_android_preset(root, "Missing", "com.example.sample")


if __name__ == "__main__":
    unittest.main(verbosity=2)
