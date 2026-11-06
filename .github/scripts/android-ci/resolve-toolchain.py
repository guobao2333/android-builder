#!/usr/bin/env python3
"""Resolve AGP, Gradle and JDK compatibility before running Gradle."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

DEFAULT_GRADLE_VERSION = "8.14.3"
BUILTIN_GRADLE_VERSIONS = (
    "2.10", "2.14.1", "3.3", "3.5", "4.1", "4.10.3",
    "5.6.4", "6.9.4", "7.0", "7.6.4", "8.0", "8.2",
    "8.4", "8.6", "8.7", "8.9", "8.11.1", "8.14.3",
    "9.1.0", "9.4.0", "9.6.0",
)
AGP_GRADLE_REQUIREMENTS = (
    ((9, 4), "9.6.0"), ((9, 3), "9.5.0"), ((9, 2), "9.4.1"),
    ((9, 1), "9.3.1"), ((9, 0), "9.1.0"),
    ((8, 13), "8.13"), ((8, 12), "8.13"), ((8, 11), "8.13"),
    ((8, 10), "8.11.1"), ((8, 9), "8.11.1"), ((8, 8), "8.10.2"),
    ((8, 7), "8.9"), ((8, 6), "8.7"), ((8, 5), "8.7"),
    ((8, 4), "8.6"), ((8, 3), "8.4"), ((8, 2), "8.2"),
    ((8, 1), "8.0"), ((8, 0), "8.0"),
    ((7, 4), "7.5"), ((7, 3), "7.4"), ((7, 2), "7.3.3"),
    ((7, 1), "7.2"), ((7, 0), "7.0"),
    ((4, 2), "6.7.1"), ((4, 1), "6.5"), ((4, 0), "6.1.1"),
    ((3, 6), "5.6.4"), ((3, 5), "5.4.1"), ((3, 4), "5.1.1"),
    ((3, 3), "4.10.1"), ((3, 2), "4.6"), ((3, 1), "4.4"),
    ((3, 0), "4.1"), ((2, 3), "3.3"), ((2, 1, 3), "2.14.1"),
    ((2, 0), "2.10"), ((1, 5), "2.2.1"), ((1, 2), "2.2.1"),
    ((1, 0), "2.2.1"),
)
PROJECT_FILE_NAMES = {
    "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", "gradle.properties",
}


def version_tuple(raw: str) -> tuple[int, ...] | None:
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", raw or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def padded(value: tuple[int, ...], size: int = 4) -> tuple[int, ...]:
    return value + (0,) * max(0, size - len(value))


def compare_versions(left: str, right: str) -> int:
    a, b = version_tuple(left), version_tuple(right)
    if a is None or b is None:
        raise ValueError(f"Invalid version comparison: {left!r}, {right!r}")
    return (padded(a) > padded(b)) - (padded(a) < padded(b))


def at_least(actual: str, required: str) -> bool:
    return compare_versions(actual, required) >= 0


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def find_wrapper_version(root: Path) -> str:
    path = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    match = re.search(
        r"(?m)^\s*distributionUrl\s*=\s*.*?gradle-([0-9][A-Za-z0-9.+_-]*)-(?:bin|all)\.zip",
        read_text(path),
    )
    return match.group(1) if match else ""


def project_files(root: Path) -> list[Path]:
    excluded = {".git", ".gradle", "build", "node_modules", ".idea", ".kotlin"}
    found: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in names:
            if name in PROJECT_FILE_NAMES or name.endswith(".versions.toml"):
                found.append(Path(current) / name)
                if len(found) >= 1000:
                    return found
    return found


def parse_variables(files: list[Path]) -> dict[str, str]:
    values: dict[str, str] = {}
    property_re = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*$")
    patterns = (
        re.compile(r"(?m)\b(?:ext\.)?([A-Za-z0-9_]*(?:agp|androidGradlePlugin)[A-Za-z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]", re.I),
        re.compile(r"(?m)\b(?:val|def)\s+([A-Za-z0-9_]*(?:agp|androidGradlePlugin)[A-Za-z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]", re.I),
    )
    for path in files:
        text = read_text(path)
        if path.name == "gradle.properties":
            for line in text.splitlines():
                match = property_re.match(line)
                if match:
                    key, value = match.groups()
                    value = value.strip().strip("'\"")
                    values[key] = value
                    values[key.lower()] = value
        for pattern in patterns:
            for match in pattern.finditer(text):
                key, value = match.groups()
                values[key] = value
                values[key.lower()] = value
    return values


def resolve_variable(raw: str, variables: dict[str, str]) -> str:
    value = raw.strip().strip("'\"")
    for _ in range(4):
        match = re.fullmatch(r"\$(?:\{([A-Za-z0-9_.-]+)\}|([A-Za-z0-9_.-]+))", value)
        if not match:
            break
        name = match.group(1) or match.group(2)
        next_value = variables.get(name, variables.get(name.lower(), ""))
        if not next_value or next_value == value:
            break
        value = next_value.strip().strip("'\"")
    return value


def catalog_agp_versions(text: str) -> list[str]:
    version_section = re.search(r"(?ms)^\[versions\]\s*(.*?)(?=^\[|\Z)", text)
    if not version_section:
        return []
    versions = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"(?m)^\s*([A-Za-z0-9_.-]+)\s*=\s*['\"]([^'\"]+)['\"]",
            version_section.group(1),
        )
    }
    plugin_section = re.search(r"(?ms)^\[plugins\]\s*(.*?)(?=^\[|\Z)", text)
    if not plugin_section:
        return []
    found: list[str] = []
    for line in plugin_section.group(1).splitlines():
        if "com.android." not in line:
            continue
        ref = re.search(r"version\.ref\s*=\s*['\"]([^'\"]+)['\"]", line)
        if ref and ref.group(1) in versions:
            found.append(versions[ref.group(1)])
        else:
            literal = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", line)
            if literal:
                found.append(literal.group(1))
    return found


def detect_agp_versions(files: list[Path], variables: dict[str, str]) -> list[str]:
    coordinate = re.compile(r"com\.android\.tools\.build:gradle:([^:'\"\s)]+)")
    plugin = re.compile(
        r"\bid\s*\(?\s*['\"]com\.android\.(?:application|library|test|dynamic-feature|test-fixtures)['\"]"
        r"\s*\)?\s*version\s*['\"]([^'\"]+)['\"]",
        re.S,
    )
    candidates: list[str] = []
    for path in files:
        text = read_text(path)
        if path.name.endswith(".versions.toml"):
            candidates.extend(catalog_agp_versions(text))
        candidates.extend(match.group(1) for match in coordinate.finditer(text))
        candidates.extend(match.group(1) for match in plugin.finditer(text))
    resolved = [
        value for candidate in candidates
        if version_tuple(value := resolve_variable(candidate, variables)) is not None
    ]
    return sorted(set(resolved), key=lambda item: padded(version_tuple(item) or (0,)))


def required_gradle_for_agp(version: str) -> str:
    actual = version_tuple(version)
    if actual is None:
        return ""
    for threshold, required in AGP_GRADLE_REQUIREMENTS:
        if padded(actual) >= padded(threshold):
            return required
    return ""


def minimum_jdk_for_agp(agp_version: str, gradle_version: str) -> int:
    if not agp_version:
        if at_least(gradle_version, "7.3"):
            return 17
        if at_least(gradle_version, "5.0"):
            return 11
        return 8
    if at_least(agp_version, "8.0"):
        return 17
    if at_least(agp_version, "7.0"):
        return 11
    return 8


def gradle_jdk_range(version: str) -> tuple[int, int]:
    minimum = 17 if at_least(version, "9.0") else 8
    maximums = (
        ("9.8", 27), ("9.4", 26), ("9.1", 25), ("8.14", 24),
        ("8.10", 23), ("8.8", 22), ("8.5", 21), ("8.3", 20),
        ("7.6", 19), ("7.5", 18), ("7.3", 17), ("7.0", 16),
        ("6.7", 15), ("6.3", 14), ("6.0", 13), ("5.4", 12),
        ("5.0", 11), ("4.7", 10), ("4.3", 9), ("2.0", 8),
    )
    maximum = 8
    for threshold, java_version in maximums:
        if at_least(version, threshold):
            maximum = java_version
            break
    return minimum, maximum


def write_outputs(values: dict[str, str]) -> None:
    lines = [
        f"{key}={value.replace(chr(10), ' ').replace(chr(13), ' ')}"
        for key, value in values.items()
    ]
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gradle-version", default="auto")
    parser.add_argument("--jdk-version", default="auto")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1

    files = project_files(root)
    variables = parse_variables(files)
    agp_versions = detect_agp_versions(files, variables)
    agp_version = agp_versions[-1] if agp_versions else ""
    agp_required_gradle = required_gradle_for_agp(agp_version)
    wrapper_version = find_wrapper_version(root)
    wrapper_script = (root / "gradlew").is_file()
    requested_gradle = args.gradle_version.strip() or "auto"
    requested_jdk = args.jdk_version.strip() or "auto"
    warnings: list[str] = []

    if requested_gradle != "auto" and requested_gradle not in BUILTIN_GRADLE_VERSIONS:
        print(
            f"::error::Unsupported Gradle fallback version '{requested_gradle}'. "
            f"Choose one of: {', '.join(BUILTIN_GRADLE_VERSIONS)}",
            file=sys.stderr,
        )
        return 1
    if len(agp_versions) > 1:
        warnings.append(
            "Multiple AGP versions were found: " + ", ".join(agp_versions)
            + ". The highest detected version is used for compatibility checks."
        )

    if wrapper_version:
        resolved_gradle = wrapper_version
        gradle_source = (
            "Gradle Wrapper" if wrapper_script
            else "gradle-wrapper.properties (CLI fallback)"
        )
        use_wrapper = wrapper_script
        if requested_gradle != "auto":
            warnings.append(
                f"Selected Gradle fallback {requested_gradle} is ignored because "
                f"the project declares Wrapper Gradle {wrapper_version}."
            )
        if agp_required_gradle and not at_least(wrapper_version, agp_required_gradle):
            warnings.append(
                f"Wrapper Gradle {wrapper_version} is older than AGP {agp_version}'s "
                f"minimum ({agp_required_gradle}); preserving the project's Wrapper declaration."
            )
    elif wrapper_script:
        resolved_gradle = agp_required_gradle or (
            requested_gradle if requested_gradle != "auto" else DEFAULT_GRADLE_VERSION
        )
        gradle_source = "Gradle Wrapper script (distribution version unknown)"
        use_wrapper = True
        warnings.append(
            "gradlew exists but gradle-wrapper.properties has no readable distribution URL; "
            "the Wrapper is preserved and its version cannot be verified in advance."
        )
    elif requested_gradle != "auto":
        resolved_gradle = requested_gradle
        gradle_source = "manual fallback selection"
        use_wrapper = False
    elif agp_required_gradle:
        resolved_gradle = agp_required_gradle
        gradle_source = "AGP compatibility table"
        use_wrapper = False
    else:
        resolved_gradle = DEFAULT_GRADLE_VERSION
        gradle_source = "built-in default fallback"
        use_wrapper = False

    if version_tuple(resolved_gradle) is None:
        print(f"::error::Invalid Gradle version: {resolved_gradle}", file=sys.stderr)
        return 1
    if agp_required_gradle and not at_least(resolved_gradle, agp_required_gradle):
        warnings.append(
            f"Selected Gradle {resolved_gradle} is below AGP {agp_version}'s "
            f"minimum ({agp_required_gradle})."
        )

    gradle_min_jdk, gradle_max_jdk = gradle_jdk_range(resolved_gradle)
    agp_min_jdk = minimum_jdk_for_agp(agp_version, resolved_gradle)
    auto_jdk = max(gradle_min_jdk, agp_min_jdk)
    if auto_jdk > gradle_max_jdk:
        warnings.append(
            f"No JDK satisfies Gradle {resolved_gradle} (Java {gradle_min_jdk}-{gradle_max_jdk}) "
            f"and AGP {agp_version or 'unknown'} (Java {agp_min_jdk}+)."
        )
        auto_jdk = gradle_max_jdk

    if requested_jdk == "auto":
        resolved_jdk = str(auto_jdk)
        jdk_source = "AGP/Gradle compatibility"
    else:
        if not requested_jdk.isdigit():
            print(f"::error::Invalid JDK version: {requested_jdk}", file=sys.stderr)
            return 1
        resolved_jdk = requested_jdk
        jdk_source = "manual selection"
        if int(resolved_jdk) < agp_min_jdk:
            warnings.append(
                f"Selected JDK {resolved_jdk} is below AGP {agp_version or 'unknown'} "
                f"minimum Java {agp_min_jdk}."
            )
        if not gradle_min_jdk <= int(resolved_jdk) <= gradle_max_jdk:
            warnings.append(
                f"Selected JDK {resolved_jdk} is outside Gradle {resolved_gradle}'s "
                f"supported Java range ({gradle_min_jdk}-{gradle_max_jdk})."
            )

    if use_wrapper:
        install_mode = (
            "legacy-wrapper" if compare_versions(resolved_gradle, "6.0") < 0 else "wrapper"
        )
    else:
        install_mode = (
            "legacy" if compare_versions(resolved_gradle, "6.0") < 0 else "setup-gradle"
        )

    warning = " ".join(warnings)
    values = {
        "agp_version": agp_version or "unknown",
        "agp_versions": ",".join(agp_versions) if agp_versions else "unknown",
        "agp_required_gradle": agp_required_gradle or "unknown",
        "wrapper_gradle_version": wrapper_version or "none",
        "wrapper_script_found": "true" if wrapper_script else "false",
        "use_wrapper": "true" if use_wrapper else "false",
        "resolved_gradle_version": resolved_gradle,
        "gradle_source": gradle_source,
        "gradle_install_mode": install_mode,
        "requested_gradle_version": requested_gradle,
        "resolved_jdk_version": resolved_jdk,
        "jdk_source": jdk_source,
        "requested_jdk_version": requested_jdk,
        "gradle_min_jdk": str(gradle_min_jdk),
        "gradle_max_jdk": str(gradle_max_jdk),
        "agp_min_jdk": str(agp_min_jdk),
        "toolchain_warning": warning or "none",
    }
    write_outputs(values)
    if warning:
        print(f"::warning::{warning}")
    print(
        "Resolved Android toolchain: "
        f"AGP={values['agp_version']}, Gradle={resolved_gradle} ({gradle_source}), "
        f"JDK={resolved_jdk} ({jdk_source}), mode={install_mode}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
