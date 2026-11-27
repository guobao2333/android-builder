#!/usr/bin/env python3
"""Regression tests for preparing Flutter dotenv assets in CI."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "prepare-env.py"
SPEC = importlib.util.spec_from_file_location("prepare_env", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PrepareEnvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flutter-env-ci-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_env_uses_example_without_modification(self):
        original = "API_URL=https://example.invalid\n"
        (self.root / ".env.example").write_text(original, encoding="utf-8")

        source, placeholder_added = MODULE.prepare_env(self.root)

        self.assertEqual(source, ".env.example")
        self.assertFalse(placeholder_added)
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), original)

    def test_missing_env_and_example_creates_nonempty_placeholder(self):
        source, placeholder_added = MODULE.prepare_env(self.root)

        self.assertEqual(source, "CI fallback")
        self.assertTrue(placeholder_added)
        self.assertEqual(
            (self.root / ".env").read_text(encoding="utf-8"),
            MODULE.PLACEHOLDER_ENTRY + "\n",
        )

    def test_empty_env_prefers_populated_example(self):
        (self.root / ".env").write_text("", encoding="utf-8")
        (self.root / ".env.example").write_text("API_URL=\n", encoding="utf-8")

        source, placeholder_added = MODULE.prepare_env(self.root)

        self.assertEqual(source, ".env.example")
        self.assertFalse(placeholder_added)
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), "API_URL=\n")

    def test_comment_only_env_gets_placeholder(self):
        original = "# Optional runtime configuration\n\n"
        (self.root / ".env").write_text(original, encoding="utf-8")

        source, placeholder_added = MODULE.prepare_env(self.root)

        self.assertEqual(source, ".env")
        self.assertTrue(placeholder_added)
        self.assertEqual(
            (self.root / ".env").read_text(encoding="utf-8"),
            original + MODULE.PLACEHOLDER_ENTRY + "\n",
        )

    def test_populated_env_is_preserved(self):
        original = "API_URL=\nOTHER_SETTING=value\n"
        (self.root / ".env").write_text(original, encoding="utf-8")

        source, placeholder_added = MODULE.prepare_env(self.root)

        self.assertEqual(source, ".env")
        self.assertFalse(placeholder_added)
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), original)

    def test_empty_example_gets_placeholder(self):
        (self.root / ".env.example").write_text("# no defaults\n", encoding="utf-8")

        source, placeholder_added = MODULE.prepare_env(self.root)

        self.assertEqual(source, ".env.example")
        self.assertTrue(placeholder_added)
        self.assertIn(MODULE.PLACEHOLDER_ENTRY, (self.root / ".env").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
