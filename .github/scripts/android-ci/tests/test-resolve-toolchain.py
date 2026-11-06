#!/usr/bin/env python3
"""Regression tests for automatic AGP/Gradle/JDK detection."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "resolve-toolchain.py"


class ResolveToolchainTest(unittest.TestCase):
    def run_resolver(
        self,
        files: dict[str, str],
        gradle: str = "auto",
        jdk: str = "auto",
    ) -> dict[str, str]:
        with tempfile.TemporaryDirectory(prefix="android-ci-toolchain-") as tmp:
            root = Path(tmp)
            for relative, text in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            output = root / "github-output.txt"
            env = os.environ.copy()
            env["GITHUB_OUTPUT"] = str(output)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--root", str(root),
                    "--gradle-version", gradle,
                    "--jdk-version", jdk,
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            values: dict[str, str] = {}
            for line in output.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    values[key] = value
            return values

    def test_legacy_agp_wrapper_uses_jdk8(self) -> None:
        values = self.run_resolver({
            "build.gradle": """
                buildscript {
                    dependencies {
                        classpath 'com.android.tools.build:gradle:3.0.0-beta5'
                    }
                }
            """,
            "gradle/wrapper/gradle-wrapper.properties":
                "distributionUrl=https\\\\://services.gradle.org/distributions/gradle-4.1-all.zip\\n",
            "gradlew": "#!/bin/sh\\n",
        })
        self.assertEqual(values["agp_version"], "3.0.0-beta5")
        self.assertEqual(values["resolved_gradle_version"], "4.1")
        self.assertEqual(values["resolved_jdk_version"], "8")
        self.assertEqual(values["use_wrapper"], "true")
        self.assertEqual(values["gradle_install_mode"], "legacy-wrapper")

    def test_missing_wrapper_script_uses_properties_version(self) -> None:
        values = self.run_resolver({
            "build.gradle": """
                plugins {
                    id 'com.android.application' version '8.2.0' apply false
                }
            """,
            "gradle/wrapper/gradle-wrapper.properties":
                "distributionUrl=https\\\\://services.gradle.org/distributions/gradle-8.4-bin.zip\\n",
        })
        self.assertEqual(values["agp_version"], "8.2.0")
        self.assertEqual(values["resolved_gradle_version"], "8.4")
        self.assertEqual(values["resolved_jdk_version"], "17")
        self.assertEqual(values["use_wrapper"], "false")
        self.assertEqual(values["gradle_install_mode"], "setup-gradle")

    def test_agp_selects_legacy_cli_when_wrapper_is_absent(self) -> None:
        values = self.run_resolver({
            "build.gradle": """
                buildscript {
                    dependencies {
                        classpath 'com.android.tools.build:gradle:3.0.0'
                    }
                }
            """,
        })
        self.assertEqual(values["resolved_gradle_version"], "4.1")
        self.assertEqual(values["resolved_jdk_version"], "8")
        self.assertEqual(values["gradle_install_mode"], "legacy")
        self.assertEqual(values["use_wrapper"], "false")

    def test_version_catalog_agp_is_detected(self) -> None:
        values = self.run_resolver({
            "settings.gradle.kts": "plugins { alias(libs.plugins.android.application) apply false }",
            "gradle/libs.versions.toml": """
                [versions]
                android-gradle-plugin = "8.2.0"

                [plugins]
                android-application = { id = "com.android.application", version.ref = "android-gradle-plugin" }
            """,
        })
        self.assertEqual(values["agp_version"], "8.2.0")
        self.assertEqual(values["resolved_gradle_version"], "8.2")
        self.assertEqual(values["resolved_jdk_version"], "17")

    def test_builtin_fallback_and_manual_override(self) -> None:
        fallback = self.run_resolver({})
        self.assertEqual(fallback["resolved_gradle_version"], "8.14.3")
        self.assertEqual(fallback["resolved_jdk_version"], "24")

        manual = self.run_resolver({}, gradle="7.6.4", jdk="17")
        self.assertEqual(manual["resolved_gradle_version"], "7.6.4")
        self.assertEqual(manual["resolved_jdk_version"], "17")
        self.assertEqual(manual["gradle_source"], "manual fallback selection")


if __name__ == "__main__":
    unittest.main(verbosity=2)
