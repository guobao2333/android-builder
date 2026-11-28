#!/usr/bin/env python3
"""Regression tests for Android application module detection and selection."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "module_detection.py"
SPEC = importlib.util.spec_from_file_location("module_detection", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ModuleDetectionTests(unittest.TestCase):
    def test_parse_gradle_projects_preserves_nested_module_paths(self) -> None:
        modules = MODULE.parse_gradle_projects("""
            Root project 'sample'
            +--- Project ':manager'
            +--- Project ':api'
            |    +--- Project ':api:provider'
            +--- Project ':manager'
        """)
        self.assertEqual(modules, [":manager", ":api", ":api:provider"])

    def test_auto_selects_the_only_application_even_when_not_named_app(self) -> None:
        selection = MODULE.select_modules(
            "auto",
            [":manager", ":api", ":core"],
            {
                ":manager": ["assembleDebug", "installDebug", "bundleRelease"],
                ":api": ["assembleDebugAar", "bundleReleaseAar"],
                ":core": [],
            },
        )
        self.assertEqual(selection["mode"], "auto")
        self.assertEqual(selection["selected"], [":manager"])
        self.assertEqual(selection["candidates"], [":manager"])
        self.assertIn("does not need to be 'app'", selection["reason"])

    def test_blank_input_also_uses_auto_detection(self) -> None:
        selection = MODULE.select_modules(
            "",
            [":client"],
            {":client": ["assembleDebug", "installDebug"]},
        )
        self.assertEqual(selection["selected"], [":client"])

    def test_auto_rejects_ambiguous_application_modules(self) -> None:
        with self.assertRaisesRegex(
            MODULE.ModuleSelectionError,
            r"multiple Android Application candidates: :client, :admin.*module=all",
        ):
            MODULE.select_modules(
                "auto",
                [":client", ":admin", ":shared"],
                {
                    ":client": ["assembleDebug", "installDebug"],
                    ":admin": ["assembleDebug", "installDebug"],
                    ":shared": ["bundleReleaseAar"],
                },
            )

    def test_all_selects_every_detected_application(self) -> None:
        selection = MODULE.select_modules(
            "all",
            [":client", ":admin", ":shared"],
            {
                ":client": ["installDebug"],
                ":admin": ["bundleRelease"],
                ":shared": ["bundleReleaseAar"],
            },
        )
        self.assertEqual(selection["mode"], "all")
        self.assertEqual(selection["selected"], [":client", ":admin"])

    def test_explicit_selection_accepts_gradle_path_or_module_name(self) -> None:
        selection = MODULE.select_modules(
            "manager,:admin",
            [":manager", ":admin"],
            {
                ":manager": ["installDebug"],
                ":admin": ["bundleRelease"],
            },
        )
        self.assertEqual(selection["mode"], "explicit")
        self.assertEqual(selection["selected"], [":manager", ":admin"])

    def test_unknown_module_error_lists_available_subprojects(self) -> None:
        with self.assertRaisesRegex(
            MODULE.ModuleSelectionError,
            r"Unknown module\(s\): :app.*:manager, :library",
        ):
            MODULE.select_modules(
                "app",
                [":manager", ":library"],
                {},
            )

    def test_non_application_module_error_includes_detected_tasks(self) -> None:
        with self.assertRaisesRegex(
            MODULE.ModuleSelectionError,
            r":api.*assembleDebugAar.*Select an application module",
        ):
            MODULE.select_modules(
                "api",
                [":api"],
                {":api": ["assembleDebugAar", "bundleReleaseAar"]},
            )

    def test_auto_reports_when_no_application_candidates_exist(self) -> None:
        with self.assertRaisesRegex(
            MODULE.ModuleSelectionError,
            r"no installable Android Application modules.*:api, :core",
        ):
            MODULE.select_modules(
                "auto",
                [":api", ":core"],
                {":api": ["assembleDebugAar"], ":core": []},
            )

    def test_module_request_modes_and_deduplication(self) -> None:
        self.assertEqual(MODULE.parse_module_request("AUTO"), ("auto", []))
        self.assertEqual(MODULE.parse_module_request(""), ("auto", []))
        self.assertEqual(MODULE.parse_module_request("all"), ("all", []))
        self.assertEqual(
            MODULE.parse_module_request(":manager,manager,:api"),
            ("explicit", [":manager", ":api"]),
        )
        with self.assertRaises(MODULE.ModuleSelectionError):
            MODULE.parse_module_request(" , ")

if __name__ == "__main__":
    unittest.main(verbosity=2)
