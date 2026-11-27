#!/usr/bin/env python3
"""Classify an Android-targetable repository for the supported build adapters."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

EXCLUDED_DIRS = {
    ".git", ".gradle", ".godot", ".idea", ".kotlin", ".fvm", ".dart_tool",
    "build", "node_modules", "Pods", "bin", "obj", ".ci-workflow",
}


def read_text(path: Path, limit: int = 1_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def gradle_files(root: Path, base: Path | None = None) -> list[Path]:
    search_root = base or root
    names = {"settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts"}
    found: list[Path] = []
    if not search_root.is_dir():
        return found
    for current, dirs, files in os.walk(search_root):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        for name in files:
            if name in names or name.endswith(".versions.toml"):
                found.append(Path(current) / name)
    return sorted(found)


def flutter_project(root: Path) -> bool:
    pubspec = read_text(root / "pubspec.yaml")
    if not pubspec:
        return False
    sections = re.finditer(
        r"(?ms)^(?:dependencies|dev_dependencies):[ \t]*\r?\n(.*?)(?=^[^ \t#][^\r\n]*:|\Z)",
        pubspec,
    )
    for section in sections:
        if re.search(
            r"(?ms)^[ \t]+flutter:[ \t]*\r?\n[ \t]+sdk:[ \t]*flutter\b",
            section.group(1),
        ):
            return True
    return False


def package_dependencies(root: Path) -> dict[str, Any]:
    raw = read_text(root / "package.json")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    result: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = data.get(key, {})
        if isinstance(value, dict):
            result.update(value)
    return result


def has_android_application(files: list[Path]) -> bool:
    text = "\n".join(read_text(path) for path in files)
    return bool(re.search(r"com\.android\.application|android-application", text, re.I))


def has_android_library(files: list[Path]) -> bool:
    text = "\n".join(read_text(path) for path in files)
    return bool(re.search(r"com\.android\.library|android-library", text, re.I))


def classify(root: Path) -> dict[str, str]:
    markers: list[str] = []
    dependencies = package_dependencies(root)
    package_json_exists = (root / "package.json").is_file()

    # Recognize wrappers before looking at generated Gradle files. They need
    # their own toolchain/build steps; an android/ folder alone is insufficient.
    if (root / "capacitor.config.ts").is_file() or (root / "capacitor.config.js").is_file() or (root / "capacitor.config.json").is_file() or "@capacitor/android" in dependencies:
        return {
            "project_type": "unsupported:capacitor",
            "detected_markers": "Capacitor config or @capacitor/android dependency",
            "reason": "Capacitor requires Node/package-manager and web asset preparation before its Android Gradle project can build.",
        }

    if "react-native" in dependencies or (package_json_exists and (root / "react-native.config.js").is_file()):
        return {
            "project_type": "unsupported:react-native",
            "detected_markers": "React Native package/config",
            "reason": "React Native requires Node/Metro, package installation and native project preparation; the Android Gradle workflow alone is not sufficient.",
        }

    if (root / "config.xml").is_file() and ("cordova" in dependencies or (root / "www").is_dir()):
        return {
            "project_type": "unsupported:cordova",
            "detected_markers": "Cordova config.xml",
            "reason": "Cordova requires its platform preparation and web asset pipeline before Android Gradle can build.",
        }

    if (root / "ProjectSettings" / "ProjectVersion.txt").is_file() and (root / "Assets").is_dir():
        return {
            "project_type": "unsupported:unity",
            "detected_markers": "Unity ProjectSettings/ProjectVersion.txt and Assets/",
            "reason": "Unity Android builds require the Unity Editor, modules and licensing setup; no Unity adapter is implemented.",
        }

    csproj_text = "\n".join(read_text(path) for path in root.rglob("*.csproj") if not any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts))
    if "<UseMaui>true</UseMaui>" in csproj_text or "Microsoft.Maui" in csproj_text:
        return {
            "project_type": "unsupported:maui",
            "detected_markers": ".NET MAUI project file",
            "reason": ".NET MAUI requires its workload and Android packaging pipeline; no MAUI adapter is implemented.",
        }

    if (root / "project.godot").is_file():
        markers.append("project.godot")
        return {
            "project_type": "godot",
            "detected_markers": ", ".join(markers),
            "reason": "Godot project detected.",
        }

    if (root / "pubspec.yaml").is_file() and flutter_project(root):
        markers.append("Flutter SDK dependency in pubspec.yaml")
        if (root / "android").is_dir():
            markers.append("android/")
            return {
                "project_type": "flutter",
                "detected_markers": ", ".join(markers),
                "reason": "Flutter project with an Android platform directory detected.",
            }
        return {
            "project_type": "unsupported:flutter-no-android",
            "detected_markers": ", ".join(markers),
            "reason": "Flutter project detected, but the repository has no android/ platform directory.",
        }

    root_gradle = gradle_files(root)
    nested_android_gradle = gradle_files(root, root / "android")
    if root_gradle:
        markers.extend(path.relative_to(root).as_posix() for path in root_gradle[:8])
        if has_android_application(root_gradle):
            return {
                "project_type": "android",
                "detected_markers": ", ".join(markers),
                "reason": "Root Android Gradle Application project detected.",
            }
        if has_android_library(root_gradle):
            return {
                "project_type": "unsupported:android-library",
                "detected_markers": ", ".join(markers),
                "reason": "Only Android library plugins were detected; the current workflow produces installable APK/AAB application artifacts.",
            }
        return {
            "project_type": "unsupported:gradle-unknown",
            "detected_markers": ", ".join(markers),
            "reason": "A root Gradle project exists, but no Android Application plugin could be identified.",
        }

    if nested_android_gradle:
        markers.extend(path.relative_to(root).as_posix() for path in nested_android_gradle[:8])
        return {
            "project_type": "unsupported:android-subdirectory",
            "detected_markers": ", ".join(markers),
            "reason": "An Android Gradle project was found under android/, not at the repository root. The native workflow does not yet accept a project subdirectory.",
        }

    if package_json_exists:
        return {
            "project_type": "unsupported:javascript",
            "detected_markers": "package.json",
            "reason": "A JavaScript/TypeScript project was detected, but no supported Android adapter was identified.",
        }

    markers = [
        name for name in (
            "pubspec.yaml", "project.godot", "settings.gradle", "settings.gradle.kts",
            "build.gradle", "build.gradle.kts", "package.json", "pom.xml",
            "Cargo.toml", "buildozer.spec", "CMakeLists.txt",
        )
        if (root / name).exists()
    ]
    return {
        "project_type": "unknown",
        "detected_markers": ", ".join(markers) if markers else "no recognized project markers",
        "reason": "No supported Android project adapter could be selected from the repository root.",
    }


def resolve(root: Path, requested: str = "auto") -> dict[str, str]:
    detected = classify(root)
    detected_type = detected["project_type"]
    if requested == "auto":
        selected = detected_type
    else:
        if requested not in {"android", "flutter", "godot"}:
            raise ValueError(f"Unsupported requested project_type: {requested}")
        if detected_type != requested:
            raise ValueError(
                f"Requested adapter '{requested}', but detected '{detected_type}'. "
                f"{detected['reason']}"
            )
        selected = requested
    return {
        "project_type": selected,
        "detected_markers": detected["detected_markers"],
        "detection_reason": detected["reason"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--requested", choices=("auto", "android", "flutter", "godot"), default="auto")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1
    try:
        result = resolve(root, args.requested)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    output = os.environ.get("GITHUB_OUTPUT", "")
    lines = [f"{key}={value.replace(chr(10), ' ').replace(chr(13), ' ')}" for key, value in result.items()]
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)
    print(f"Project type: {result['project_type']} ({result['detection_reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
