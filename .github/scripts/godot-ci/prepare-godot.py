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


EXCLUDED_PROJECT_DIRS = {".git", ".godot", ".ci-workflow", "bin", "obj", "build", "node_modules"}


def find_csproj_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.csproj")
        if not any(part in EXCLUDED_PROJECT_DIRS for part in path.relative_to(root).parts)
    )


def parse_tfm(value: str) -> tuple[tuple[int, int], str] | None:
    match = re.fullmatch(r"net(\d+)(?:\.(\d+))?([-+].*)?", value.strip(), re.I)
    if not match:
        return None
    digits, minor, suffix = match.groups()
    if minor is None:
        if len(digits) < 2:
            major, minor_value = digits, "0"
        else:
            major, minor_value = digits[:-1], digits[-1]
    else:
        major, minor_value = digits, minor
    return (int(major), int(minor_value)), suffix or ""


def required_android_tfm(godot_version: str) -> str:
    version = tuple(int(part) for part in godot_version.split(".")[:2])
    if version[0] != 4:
        raise ValueError(f"Android C# export compatibility is not defined for Godot {godot_version}.")
    if version[1] >= 8:
        return "net10.0"
    if version[1] >= 5:
        return "net9.0"
    return "net8.0"


def rewrite_android_target_frameworks(path: Path, required_tfm: str) -> tuple[list[str], bool]:
    content = read_text(path)
    required_match = parse_tfm(required_tfm)
    if required_match is None:
        raise ValueError(f"Unsupported Android target framework requirement: {required_tfm}")
    required_version, _ = required_match
    found: list[str] = []
    changed = False
    pattern = re.compile(r"(?is)(<TargetFrameworks?>)(.*?)(</TargetFrameworks?>)")

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        updated_parts = []
        for raw_part in match.group(2).split(";"):
            leading = raw_part[:len(raw_part) - len(raw_part.lstrip())]
            trailing = raw_part[len(raw_part.rstrip()):]
            value = raw_part.strip()
            parsed = parse_tfm(value)
            if parsed:
                current_version, suffix = parsed
                if current_version[0] < 5:
                    raise ValueError(
                        f"{path.name} targets legacy framework '{value}', which cannot be safely "
                        "retargeted for a Godot Android export."
                    )
                if current_version < required_version:
                    value = required_tfm + suffix
                    changed = True
            found.append(value)
            updated_parts.append(leading + value + trailing)
        return match.group(1) + ";".join(updated_parts) + match.group(3)

    updated = pattern.sub(replace, content)
    if not found:
        raise ValueError(
            f"No explicit TargetFramework/TargetFrameworks was found in {path.name}; "
            "the Android export target cannot be inferred safely."
        )
    if changed:
        path.write_text(updated, encoding="utf-8")
    return found, changed


def prepare_dotnet_android(
    root: Path,
    godot_version: str,
    is_csharp: bool,
) -> tuple[str, str, str]:
    if not is_csharp:
        return "", "", ""

    projects = find_csproj_files(root)
    godot_projects: list[Path] = []
    for path in projects:
        try:
            project = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise ValueError(f"Invalid C# project file {path.name}: {exc}") from exc
        if "Godot.NET.Sdk" in project.attrib.get("Sdk", ""):
            godot_projects.append(path)

    if not godot_projects:
        raise ValueError(
            "A Godot C# project was detected, but no project using Godot.NET.Sdk was found. "
            "Automatic Android target-framework adaptation is unavailable."
        )

    required_tfm = required_android_tfm(godot_version)
    all_frameworks: list[str] = []
    upgrades: list[str] = []
    for path in godot_projects:
        frameworks, changed = rewrite_android_target_frameworks(path, required_tfm)
        all_frameworks.extend(frameworks)
        if changed:
            upgrades.append(path.relative_to(root).as_posix())

    required = parse_tfm(required_tfm)
    assert required is not None
    required_major = required[0][0]
    target_majors = [
        parsed[0][0]
        for item in all_frameworks
        if (parsed := parse_tfm(item)) is not None
    ]
    if not target_majors or max(target_majors) < required_major:
        raise ValueError(
            f"Godot {godot_version} Android export requires {required_tfm}, "
            f"but the detected project targets are {', '.join(all_frameworks)}."
        )

    sdk_version = ""
    global_json = root / "global.json"
    global_json_changed = False
    if global_json.is_file():
        try:
            data = json.loads(read_text(global_json))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid global.json: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("global.json must contain a JSON object.")
        sdk = data.setdefault("sdk", {})
        if not isinstance(sdk, dict):
            raise ValueError("global.json 'sdk' property must be a JSON object.")
        pinned = str(sdk.get("version", "")).strip()
        if pinned:
            match = re.match(r"^(\d+)\.(\d+)\.(\d+)", pinned)
            if not match:
                raise ValueError(f"Cannot interpret global.json SDK version: {pinned}")
            pinned_major = int(match.group(1))
            required_sdk_major = max(required_major, max(target_majors))
            if pinned_major < required_sdk_major:
                old_version = pinned
                pinned = f"{required_sdk_major}.0.100"
                sdk["version"] = pinned
                sdk["rollForward"] = "latestFeature"
                global_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                global_json_changed = True
                upgrades.append("global.json")
                print(
                    f"Adjusted CI workspace global.json SDK pin from {old_version} to {pinned} "
                    "to satisfy the Android export target."
                )
            sdk_version = pinned
        else:
            sdk_version = f"{max(required_major, max(target_majors))}.0.x"
    else:
        sdk_version = f"{max(required_major, max(target_majors))}.0.x"

    target_display = ", ".join(dict.fromkeys(all_frameworks))
    if upgrades:
        upgrade_display = (
            f"CI workspace retargeted {', '.join(upgrades)} for Android "
            f"({required_tfm}); source repository is unchanged"
        )
    else:
        upgrade_display = f"Project already targets {target_display}; no automatic retargeting needed"
    return sdk_version, target_display, upgrade_display


def detect_project(root: Path, requested_version: str) -> tuple[str, bool, str, str]:
    project_file = root / "project.godot"
    if not project_file.is_file():
        raise ValueError("No project.godot was found in the target repository.")

    project_text = read_text(project_file)
    name_match = re.search(r'(?m)^\s*config/name\s*=\s*"([^"]+)"', project_text)
    project_name = name_match.group(1) if name_match else root.name

    sdk_versions: list[str] = []
    frameworks: list[str] = []
    for csproj in find_csproj_files(root):
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


def ensure_android_texture_import(root: Path) -> bool:
    """Enable ETC2/ASTC texture import required by Godot Android export."""

    path = root / "project.godot"
    content = read_text(path)
    if not content:
        raise ValueError("project.godot is missing or unreadable.")

    section = re.compile(r"(?ms)^\[rendering\][ \t]*\r?\n(.*?)(?=^\[[^\r\n]+\][ \t]*$|\Z)")
    key = "textures/vram_compression/import_etc2_astc"
    match = section.search(content)

    if match:
        body = match.group(1)
        setting = re.compile(
            rf"(?m)^([ \t]*){re.escape(key)}[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$"
        )
        found = setting.search(body)
        if found and found.group(2) == "true":
            return False
        if found:
            updated_body = setting.sub(
                lambda item: item.group(1) + key + "=true",
                body,
                count=1,
            )
        else:
            separator = "" if not body or body.endswith("\n") else "\n"
            updated_body = body + separator + key + "=true\n"
        updated = content[:match.start(1)] + updated_body + content[match.end(1):]
    else:
        addition = "\n[rendering]\n" + key + "=true\n"
        updated = content.rstrip() + addition

    path.write_text(updated, encoding="utf-8")
    return True

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
        dotnet_version, dotnet_target_framework, dotnet_upgrade = prepare_dotnet_android(
            root, godot_version, is_csharp
        )
        preset_name = ensure_android_preset(root, args.preset, args.package_name)
        rendering_setting_changed = ensure_android_texture_import(root)
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
        "dotnet_target_framework": dotnet_target_framework,
        "dotnet_upgrade": dotnet_upgrade,
        "project_name": project_name,
        "export_preset": preset_name,
        "android_texture_import": "enabled (temporary CI workspace)" if rendering_setting_changed else "already enabled",
        "matrix": json.dumps(matrix, ensure_ascii=False),
    })
    print(f"Prepared Godot Android preset '{preset_name}' for {project_name} ({godot_version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
