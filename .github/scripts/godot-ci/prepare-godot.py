#!/usr/bin/env python3
"""Detect a Godot project and prepare a non-secret Android export preset."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def detect_project(root: Path, requested_version: str) -> tuple[str, bool, str, str]:
    project_file = root / "project.godot"
    if not project_file.is_file():
        raise ValueError("No project.godot was found in the target repository.")

    project_text = read_text(project_file)
    name_match = re.search(r'(?m)^\s*config/name\s*=\s*"([^"]+)"', project_text)
    project_name = name_match.group(1) if name_match else root.name

    sdk_versions: list[str] = []
    frameworks: list[str] = []
    for csproj in sorted(root.glob("*.csproj")):
        try:
            project = ET.parse(csproj).getroot()
        except ET.ParseError as exc:
            raise ValueError(f"Invalid C# project file {csproj.name}: {exc}") from exc
        sdk = project.attrib.get("Sdk", "")
        match = re.search(r"Godot\.NET\.Sdk/(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)", sdk)
        if match:
            sdk_versions.append(match.group(1))
        for element in project.iter():
            if element.tag.rsplit("}", 1)[-1] in {"TargetFramework", "TargetFrameworks"}:
                frameworks.extend(item.strip() for item in (element.text or "").split(";") if item.strip())

    is_csharp = bool(sdk_versions or frameworks or '"C#"' in project_text)
    if requested_version and requested_version != "auto":
        godot_version = requested_version
    elif sdk_versions:
        godot_version = sdk_versions[0]
        if len(set(sdk_versions)) > 1:
            raise ValueError("Multiple Godot.NET.Sdk versions were found: " + ", ".join(sorted(set(sdk_versions))))
    else:
        feature = re.search(r'config/features\s*=\s*PackedStringArray\("(\d+\.\d+(?:\.\d+)?)"', project_text)
        godot_version = feature.group(1) if feature else "4.5.1"
        if godot_version.count(".") == 1:
            godot_version += ".1"

    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", godot_version):
        raise ValueError(f"Godot version must include major, minor and patch: {godot_version}")

    dotnet_version = ""
    global_json = root / "global.json"
    if is_csharp and global_json.is_file():
        try:
            sdk_version = json.loads(read_text(global_json)).get("sdk", {}).get("version", "")
        except (ValueError, AttributeError):
            sdk_version = ""
        if sdk_version:
            dotnet_version = sdk_version
    if is_csharp and not dotnet_version:
        for framework in frameworks:
            match = re.fullmatch(r"net(\d+)(?:\.(\d+))?", framework, re.I)
            if not match:
                continue
            raw_major = match.group(1)
            if len(raw_major) >= 2 and not match.group(2):
                major, minor = raw_major[:-1], raw_major[-1]
            else:
                major, minor = raw_major, match.group(2) or "0"
            dotnet_version = f"{int(major)}.{int(minor)}.x"
            break
        if not dotnet_version:
            dotnet_version = "8.0.x"

    return godot_version, is_csharp, dotnet_version, project_name


def preset_sections(content: str) -> list[tuple[int, str, str]]:
    result = []
    pattern = re.compile(r"(?ms)^\[preset\.(\d+)\][ \t]*\r?\n(.*?)(?=^\[|\Z)")
    for match in pattern.finditer(content):
        body = match.group(2)
        name = re.search(r'(?m)^\s*name\s*=\s*"([^"]+)"', body)
        platform = re.search(r'(?m)^\s*platform\s*=\s*"([^"]+)"', body)
        result.append((int(match.group(1)), name.group(1) if name else "", platform.group(1) if platform else ""))
    return result


def quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def ensure_android_preset(root: Path, requested_preset: str, package_name: str) -> str:
    path = root / "export_presets.cfg"
    content = read_text(path)
    sections = preset_sections(content)
    android = [section for section in sections if section[2].lower() == "android"]

    if requested_preset != "auto":
        match = next((section for section in android if section[1] == requested_preset), None)
        if not match:
            raise ValueError(f"Android export preset '{requested_preset}' was not found in export_presets.cfg.")
        return requested_preset

    if android:
        preferred = next((section for section in android if section[1] == "Android"), android[0])
        return preferred[1]

    preset_id = max((section[0] for section in sections), default=-1) + 1
    project_text = read_text(root / "project.godot")
    name_match = re.search(r'(?m)^\s*config/name\s*=\s*"([^"]+)"', project_text)
    display_name = name_match.group(1) if name_match else root.name
    safe_package = package_name.strip() or "org.godotengine.androidbuilder"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", safe_package):
        raise ValueError(f"Invalid Android package name: {safe_package}")

    preset = f'''
[preset.{preset_id}]
name="Android CI"
platform="Android"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/android/android-ci.apk"
patches=PackedStringArray()
encryption_include_filters=""
encryption_exclude_filters=""
seed=0
encrypt_pck=false
encrypt_directory=false
script_export_mode=2

[preset.{preset_id}.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=false
architectures/armeabi-v7a=false
architectures/arm64-v8a=true
architectures/x86=false
architectures/x86_64=false
version/code=1
version/name="1.0.0"
package/unique_name={quoted(safe_package)}
package/name={quoted(display_name)}
screen/immersive_mode=true
'''
    path.write_text(content.rstrip() + "\n" + preset.lstrip(), encoding="utf-8")
    return "Android CI"


def write_outputs(values: dict[str, str]) -> None:
    lines = [f"{key}={value.replace(chr(10), ' ').replace(chr(13), ' ')}" for key, value in values.items()]
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--godot-version", default="auto")
    parser.add_argument("--preset", default="auto")
    parser.add_argument("--package-name", default="org.godotengine.androidbuilder")
    parser.add_argument("--build-type", choices=("debug", "release", "all"), default="debug")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1

    try:
        godot_version, is_csharp, dotnet_version, project_name = detect_project(root, args.godot_version)
        preset_name = ensure_android_preset(root, args.preset, args.package_name)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    build_types = ("debug", "release") if args.build_type == "all" else (args.build_type,)
    matrix = {
        "include": [
            {
                "build_type": build_type,
                "export_flag": "--export-debug" if build_type == "debug" else "--export-release",
                "artifact": f"{re.sub(r'[^A-Za-z0-9._-]+', '-', project_name).strip('-') or 'godot'}-{build_type}.apk",
            }
            for build_type in build_types
        ]
    }
    write_outputs({
        "godot_version": godot_version,
        "use_dotnet": "true" if is_csharp else "false",
        "dotnet_version": dotnet_version,
        "project_name": project_name,
        "export_preset": preset_name,
        "matrix": json.dumps(matrix, ensure_ascii=False),
    })
    print(f"Prepared Godot Android preset '{preset_name}' for {project_name} ({godot_version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
