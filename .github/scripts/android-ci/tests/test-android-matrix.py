#!/usr/bin/env python3
"""Exercise the actual Android workflow matrix script with a deterministic Gradle fixture."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github" / "workflows" / "android.yml"
HELPERS = ROOT / ".github" / "scripts" / "android-ci"
FAKE_GRADLE = """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
remaining = args[2:]
if not remaining:
    raise SystemExit("missing Gradle task")
if remaining[0] == "projects":
    print("Root project 'fixture'")
    for module in json.loads(os.environ["FAKE_GRADLE_PROJECTS"]):
        print("+--- Project '" + module + "'")
else:
    task_path = next((item for item in remaining if item.endswith(":tasks")), "")
    if not task_path:
        raise SystemExit("unknown fixture Gradle command: " + " ".join(remaining))
    module = task_path[:-len(":tasks")]
    tasks = json.loads(os.environ["FAKE_GRADLE_TASKS"]).get(module, [])
    for task in tasks:
        print("    " + task + " - fixture task")
"""


def extract_matrix_script() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    pattern = (
        r"(?ms)^[ \t]*python3 - <<'PY' >> "
        + re.escape('"$GITHUB_OUTPUT"')
        + r"\r?\n(.*?)^[ \t]*PY[ \t]*$"
    )
    match = re.search(pattern, workflow)
    if not match:
        raise AssertionError("Could not locate the Android matrix Python heredoc.")
    return textwrap.dedent(match.group(1))


MATRIX_SCRIPT = extract_matrix_script()


class AndroidMatrixIntegrationTests(unittest.TestCase):
    def run_matrix(
        self,
        module: str,
        projects: list[str],
        tasks: dict[str, list[str]],
    ) -> tuple[subprocess.CompletedProcess[str], str, str]:
        with tempfile.TemporaryDirectory(prefix="android-matrix-") as tmp:
            temp = Path(tmp)
            gradle = temp / "fake-gradle"
            gradle.write_text(FAKE_GRADLE, encoding="utf-8")
            gradle.chmod(0o755)

            script = temp / "matrix.py"
            script.write_text(MATRIX_SCRIPT, encoding="utf-8")
            output = temp / "github-output.txt"
            summary = temp / "github-step-summary.md"

            env = os.environ.copy()
            env.update({
                "CI_HELPERS_DIR": str(HELPERS),
                "GRADLE_COMMAND": str(gradle),
                "GITHUB_REPOSITORY": "fixture/sample",
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
                "INPUT_REPOSITORY": "",
                "INPUT_MODULE": module,
                "INPUT_BUILD_FLAVOR": "",
                "INPUT_BUILD_TYPE": "debug",
                "DATE_LONG": "20261128-000000",
                "FAKE_GRADLE_PROJECTS": json.dumps(projects),
                "FAKE_GRADLE_TASKS": json.dumps(tasks),
            })
            with output.open("w", encoding="utf-8") as stream:
                process = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            output_text = output.read_text(encoding="utf-8")
            summary_text = summary.read_text(encoding="utf-8") if summary.exists() else ""
            return process, output_text, summary_text

    def test_auto_builds_unique_primary_application_not_named_app(self) -> None:
        process, output, summary = self.run_matrix(
            "auto",
            [":manager", ":api", ":core"],
            {
                ":manager": ["assembleDebug", "installDebug", "bundleRelease"],
                ":api": ["assembleDebugAar", "bundleReleaseAar"],
                ":core": [],
            },
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("resolved_modules=:manager", output)
        self.assertIn('"module": ":manager"', output)
        self.assertIn("module_selection_mode=auto", output)
        self.assertIn("Selected application", summary)
        self.assertIn(":manager", summary)
        self.assertIn(":api", summary)
        self.assertIn("No installable application tasks", summary)

    def test_missing_default_app_reports_real_candidates_in_summary(self) -> None:
        process, _, summary = self.run_matrix(
            "app",
            [":manager", ":api"],
            {
                ":manager": ["assembleDebug", "installDebug", "bundleRelease"],
                ":api": ["assembleDebugAar", "bundleReleaseAar"],
            },
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("Unknown module(s): :app", process.stderr)
        self.assertIn("Installable Android Application candidates: :manager", process.stderr)
        self.assertIn("**Status:** failed", summary)
        self.assertIn("**Failure reason:** Unknown module(s): :app", summary)
        self.assertIn("**Application candidates:** :manager", summary)
        self.assertIn("installDebug", summary)

    def test_ambiguous_auto_detection_lists_candidates_in_summary(self) -> None:
        process, _, summary = self.run_matrix(
            "auto",
            [":client", ":admin", ":shared"],
            {
                ":client": ["assembleDebug", "installDebug"],
                ":admin": ["assembleDebug", "installDebug"],
                ":shared": ["bundleReleaseAar"],
            },
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("multiple Android Application candidates: :client, :admin", process.stderr)
        self.assertIn("**Application candidates:** :client, :admin", summary)
        self.assertIn("**Resolved module(s):** none", summary)
        self.assertIn("No installable application tasks", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
