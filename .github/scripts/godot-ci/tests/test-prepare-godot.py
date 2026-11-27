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

    def test_godot_45_android_export_retargets_net8_to_net9_in_ci_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "project.godot", 'config/name="Fortune Mill"\\nconfig/features=PackedStringArray("4.5", "C#")\\n')
            self.write(
                root,
                "FortuneMill.csproj",
                '<Project Sdk="Godot.NET.Sdk/4.5.1"><PropertyGroup><TargetFramework>net80</TargetFramework></PropertyGroup></Project>',
            )
            version, is_csharp, _, _ = MODULE.detect_project(root, "auto")
            sdk, target, change = MODULE.prepare_dotnet_android(root, version, is_csharp)
            project = (root / "FortuneMill.csproj").read_text(encoding="utf-8")
            self.assertEqual(sdk, "9.0.x")
            self.assertEqual(target, "net9.0")
            self.assertIn("<TargetFramework>net9.0</TargetFramework>", project)
            self.assertIn("CI workspace", change)

    def test_godot_48_android_export_uses_net10(self):
        self.assertEqual(MODULE.required_android_tfm("4.8.0"), "net10.0")

    def test_newer_target_framework_is_not_downgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "project.godot", 'config/name="Sample"\\nconfig/features=PackedStringArray("4.5", "C#")\\n')
            self.write(
                root,
                "Sample.csproj",
                '<Project Sdk="Godot.NET.Sdk/4.5.1"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>',
            )
            sdk, target, change = MODULE.prepare_dotnet_android(root, "4.5.1", True)
            self.assertEqual(sdk, "10.0.x")
            self.assertEqual(target, "net10.0")
            self.assertIn("no automatic retargeting", change)

    def test_global_json_sdk_pin_is_upgraded_only_in_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "Sample.csproj", '<Project Sdk="Godot.NET.Sdk/4.5.1"><PropertyGroup><TargetFramework>net80</TargetFramework></PropertyGroup></Project>')
            self.write(root, "global.json", '{"sdk":{"version":"8.0.100","rollForward":"disable"}}')
            sdk, target, change = MODULE.prepare_dotnet_android(root, "4.5.1", True)
            global_data = __import__("json").loads((root / "global.json").read_text(encoding="utf-8"))
            self.assertEqual(sdk, "9.0.100")
            self.assertEqual(target, "net9.0")
            self.assertEqual(global_data["sdk"]["version"], "9.0.100")
            self.assertEqual(global_data["sdk"]["rollForward"], "latestFeature")
            self.assertIn("global.json", change)

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
