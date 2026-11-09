#!/usr/bin/env python3
"""Resolve the NDK revision declared by an Android Gradle project."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from ndk_versions import resolve_ndk_revision

EXCLUDED_DIRS = {".git", ".gradle", ".idea", ".kotlin", "build", "node_modules"}
GRADLE_NAMES = {"build.gradle", "build.gradle.kts", "gradle.properties"}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def project_files(root: Path) -> list[Path]:
    found = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        for name in names:
            if name in GRADLE_NAMES or name.endswith(".versions.toml"):
                found.append(Path(current) / name)
    return found


def version_catalogs(files: list[Path]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in files:
        if not path.name.endswith(".versions.toml"):
            continue
        content = read_text(path)
        section = re.search(r"(?ms)^\s*\[versions\]\s*(.*?)(?=^\s*\[|\Z)", content)
        if not section:
            continue
        for match in re.finditer(
            r"""(?m)^\s*([A-Za-z0-9_.-]+)\s*=\s*["']([^"']+)["']""",
            section.group(1),
        ):
            versions[match.group(1)] = match.group(2)
    return versions


def collect_variables(files: list[Path], catalog: dict[str, str]) -> dict[str, str]:
    variables = dict(catalog)
    assignment = re.compile(
        r"""(?m)^\s*(?:(?:ext\.)|(?:val\s+)|(?:def\s+))?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*["']([^"']+)["']"""
    )
    property_line = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*$")
    for path in files:
        content = read_text(path)
        for match in assignment.finditer(content):
            key, value = match.groups()
            variables[key] = value.strip()
            variables[key.rsplit(".", 1)[-1]] = value.strip()
        if path.name == "gradle.properties":
            for line in content.splitlines():
                match = property_line.match(line)
                if match:
                    key, value = match.groups()
                    variables[key] = value.strip().strip("'\"")
                    variables[key.rsplit(".", 1)[-1]] = value.strip().strip("'\"")
    return variables


def resolve_expression(expression: str, variables: dict[str, str]) -> str:
    value = expression.strip().rstrip(";,}").strip()
    literal = re.fullmatch(r"""["']([^"']+)["']""", value)
    if literal:
        return literal.group(1)

    catalog_ref = re.fullmatch(
        r"""libs\.versions\.([A-Za-z0-9_-]+)(?:\.get\(\))?(?:\.toString\(\))?""",
        value,
    )
    if catalog_ref and catalog_ref.group(1) in variables:
        return variables[catalog_ref.group(1)]

    property_ref = re.fullmatch(
        r"""(?:rootProject\.)?(?:project\.)?(?:ext\.)?([A-Za-z_][A-Za-z0-9_.-]*)""",
        value,
    )
    if property_ref and property_ref.group(1) in variables:
        return variables[property_ref.group(1)]

    provider_ref = re.fullmatch(
        r"""(?:providers\.gradleProperty|project\.property)\(["']([^"']+)["']\)(?:\.get\(\))?""",
        value,
    )
    if provider_ref and provider_ref.group(1) in variables:
        return variables[provider_ref.group(1)]

    variable_ref = re.fullmatch(r"""\$\{?([A-Za-z_][A-Za-z0-9_.-]*)}?""", value)
    if variable_ref and variable_ref.group(1) in variables:
        return variables[variable_ref.group(1)]
    return ""


def detect_ndk_versions(root: Path) -> tuple[list[str], list[str]]:
    files = project_files(root)
    variables = collect_variables(files, version_catalogs(files))
    declarations: list[str] = []
    unresolved: list[str] = []
    pattern = re.compile(r"(?m)\bndkVersion\s*(?:=\s*)?([^\r\n;]+)")
    for path in files:
        if path.name == "gradle.properties":
            continue
        for match in pattern.finditer(read_text(path)):
            expression = match.group(1).strip()
            value = resolve_expression(expression, variables)
            if value:
                declarations.append(value)
            else:
                unresolved.append(f"{path.relative_to(root)}: {expression}")
    return sorted(set(declarations)), unresolved


def write_outputs(values: dict[str, str]) -> None:
    lines = [f"{key}={value.replace(chr(10), ' ').replace(chr(13), ' ')}" for key, value in values.items()]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requested", default="auto", help="auto, an alias, or a full SDK revision")
    parser.add_argument("--root", default=".")
    parser.add_argument("--fallback", default="r27d")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1

    requested = args.requested.strip() or "auto"
    source = "manual"
    detected: list[str] = []
    if requested == "auto":
        detected, unresolved = detect_ndk_versions(root)
        if unresolved:
            details = "; ".join(unresolved[:8])
            print(
                "::error::Found ndkVersion declarations that could not be resolved: "
                + details
                + ". Use a literal version or select ndk_version manually.",
                file=sys.stderr,
            )
            return 1
        if len(detected) > 1:
            print(
                "::error::Conflicting ndkVersion declarations were found: "
                + ", ".join(detected)
                + ". Select ndk_version manually so one NDK can be installed for this workflow.",
                file=sys.stderr,
            )
            return 1
        if detected:
            selected = detected[0]
            source = "project ndkVersion"
        else:
            selected = args.fallback
            source = "built-in fallback"
    else:
        selected = requested

    try:
        revision = resolve_ndk_revision(selected)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    write_outputs({
        "resolved_ndk_version": selected,
        "resolved_ndk_revision": revision,
        "ndk_version_source": source,
        "ndk_detection_status": "detected" if detected else ("not-present" if requested == "auto" else "manual"),
        "detected_ndk_versions": ",".join(detected) if detected else "none",
    })
    print(f"Resolved NDK: {selected} -> {revision} ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
