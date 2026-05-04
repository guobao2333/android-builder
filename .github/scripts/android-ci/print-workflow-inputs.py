#!/usr/bin/env python3
"""Print resolved Android CI workflow inputs and append a Markdown summary."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from typing import Any


def value(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def display_value(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (list, dict)):
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return str(raw)


def read_ndk_revision_from_env() -> str:
    ndk_home = value("ANDROID_NDK_HOME")
    if not ndk_home:
        return ""
    source_properties = os.path.join(ndk_home, "source.properties")
    try:
        with open(source_properties, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("Pkg.Revision") and "=" in line:
                    return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def load_input_fields() -> list[tuple[str, str]]:
    """Load display fields from one JSON blob produced by the workflow.

    Keeping this as a single JSON input avoids maintaining the same field list
    separately for step env wiring, Markdown output, and console output.
    """

    raw = value("WORKFLOW_INPUTS_JSON")
    if not raw:
        print("::error::WORKFLOW_INPUTS_JSON is required.", file=sys.stderr)
        raise SystemExit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"::error::Unable to parse WORKFLOW_INPUTS_JSON: {exc}", file=sys.stderr)
        raise

    if not isinstance(data, Mapping):
        print("::error::WORKFLOW_INPUTS_JSON must be a JSON object.", file=sys.stderr)
        raise SystemExit(1)

    fields = [(str(key), display_value(field_value)) for key, field_value in data.items()]
    existing = {key for key, _ in fields}

    dynamic_fields = {
        "resolved_ndk_revision": read_ndk_revision_from_env(),
        "android_ndk_home": value("ANDROID_NDK_HOME"),
    }
    for key, field_value in dynamic_fields.items():
        if key not in existing:
            fields.append((key, display_value(field_value)))

    return fields


def load_matrix_entries() -> list[dict[str, Any]]:
    matrix_json = value("RESOLVED_MATRIX", '{"include": []}')
    try:
        data = json.loads(matrix_json)
    except json.JSONDecodeError as exc:
        print(f"::error::Unable to parse resolved matrix: {exc}", file=sys.stderr)
        raise
    entries = data.get("include", [])
    if not isinstance(entries, list):
        print("::error::Resolved matrix include value must be a list.", file=sys.stderr)
        raise SystemExit(1)
    return entries


def build_summary(fields: list[tuple[str, str]], entries: list[dict[str, Any]]) -> str:
    rows = [
        "### Resolved manual workflow inputs",
        "",
        "| Input | Final value used |",
        "| --- | --- |",
    ]
    for key, field in fields:
        rows.append(f"| `{key}` | `{md_escape(field)}` |")

    rows.extend([
        "",
        "### Resolved build matrix",
        "",
        "| # | Module | Flavor | Build type | Artifact | Gradle task | Artifact name |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
    ])
    for index, item in enumerate(entries, start=1):
        rows.append(
            "| {index} | `{module}` | `{flavor}` | `{build_type}` | `{artifact_type}` | `{task}` | `{artifact_name}` |".format(
                index=index,
                module=md_escape(display_value(item.get("module", ""))),
                flavor=md_escape(display_value(item.get("flavor") or "-")),
                build_type=md_escape(display_value(item.get("build_type", ""))),
                artifact_type=md_escape(display_value(item.get("artifact_type", ""))),
                task=md_escape(display_value(item.get("gradle_task", ""))),
                artifact_name=md_escape(display_value(item.get("artifact_name", ""))),
            )
        )
    return "\n".join(rows) + "\n"


def print_console(fields: list[tuple[str, str]], entries: list[dict[str, Any]]) -> None:
    print("Resolved manual workflow inputs:")
    for key, field in fields:
        print(f"  {key}: {field}")
    print("Resolved build matrix:")
    for index, item in enumerate(entries, start=1):
        print(
            f"  {index}. module={display_value(item.get('module', ''))} "
            f"flavor={display_value(item.get('flavor') or '-')} "
            f"build_type={display_value(item.get('build_type', ''))} "
            f"artifact_type={display_value(item.get('artifact_type', ''))} "
            f"gradle_task={display_value(item.get('gradle_task', ''))} "
            f"artifact_name={display_value(item.get('artifact_name', ''))}"
        )


def main() -> int:
    fields = load_input_fields()
    entries = load_matrix_entries()
    summary = build_summary(fields, entries)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(summary)
    print_console(fields, entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
