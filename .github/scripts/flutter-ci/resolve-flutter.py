#!/usr/bin/env python3
"""Resolve a Flutter SDK from project metadata before dependency resolution."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MANIFEST_URL = "https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?$")
CHANNELS = {"stable", "beta", "main", "master"}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def version_tuple(value: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.fullmatch((value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def lower_bound(constraint: str) -> tuple[int, int, int] | None:
    raw = (constraint or "").strip().strip("\"'")
    match = re.search(r"(?:>=\s*|\^\s*|~>\s*|^)(\d+\.\d+(?:\.\d+)?)", raw)
    if not match:
        return None
    parts = tuple(int(part) for part in match.group(1).split("."))
    return (parts + (0,))[:3]


def read_lock_constraints(root: Path) -> dict[str, tuple[int, int, int]]:
    constraints: dict[str, tuple[int, int, int]] = {}
    lock_text = read_text(root / "pubspec.lock")
    section = re.search(r"(?ms)^sdks:\s*\r?\n((?:^[ \t]+.*(?:\r?\n|$))*)", lock_text)
    if section:
        for name, raw in re.findall(r"(?m)^[ \t]+(dart|flutter):\s*([^\r\n]+)", section.group(1)):
            bound = lower_bound(raw)
            if bound:
                constraints[name] = bound

    if "dart" not in constraints or "flutter" not in constraints:
        pubspec = read_text(root / "pubspec.yaml")
        environment = re.search(
            r"(?ms)^environment:[ \t]*\r?\n(.*?)(?=^[^ \t#][^\r\n]*:|\Z)",
            pubspec,
        )
        if environment:
            for name, raw in re.findall(
                r"(?m)^[ \t]+(sdk|flutter):\s*([^\r\n]+)",
                environment.group(1),
            ):
                key = "dart" if name == "sdk" else "flutter"
                if key not in constraints:
                    bound = lower_bound(raw)
                    if bound:
                        constraints[key] = bound
    return constraints


def read_pinned_version(root: Path) -> tuple[str, str] | None:
    for path, keys in (
        (root / ".fvmrc", ("flutter",)),
        (root / ".fvm" / "fvm_config.json", ("flutterSdkVersion", "flutter")),
    ):
        raw = read_text(path)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Flutter version config {path.relative_to(root)}: {exc}") from exc
        if isinstance(data, dict):
            for key in keys:
                value = str(data.get(key, "")).strip()
                if value:
                    return value, path.relative_to(root).as_posix()

    pubspec = read_text(root / "pubspec.yaml")
    environment = re.search(
        r"(?ms)^environment:[ \t]*\r?\n(.*?)(?=^[^ \t#][^\r\n]*:|\Z)",
        pubspec,
    )
    if environment:
        match = re.search(r"(?m)^[ \t]+flutter:\s*['\"]?([^\s'\"#]+)", environment.group(1))
        if match and version_tuple(match.group(1)):
            return match.group(1), "pubspec.yaml environment.flutter"
    return None


def read_metadata_revision(root: Path) -> tuple[str, str] | None:
    metadata = read_text(root / ".metadata")
    if not metadata:
        return None
    revision_line = re.search(r"(?m)^[ \t]+revision:\s*(.*?)\s*$", metadata)
    channel_match = re.search(r'(?m)^[ \t]+channel:\s*["\']?([A-Za-z]+)["\']?\s*$', metadata)
    if not revision_line:
        return None
    revision = revision_line.group(1).strip().strip("\"'")
    if not re.fullmatch(r"[0-9a-f]{7,40}", revision, re.I):
        raise ValueError(f"Invalid Flutter git revision in .metadata: {revision!r}")
    channel = channel_match.group(1).lower() if channel_match else "stable"
    if channel not in CHANNELS:
        raise ValueError(f"Unsupported Flutter channel in .metadata: {channel}")
    return revision, channel


def load_manifest(manifest_file: str = "", manifest_url: str = MANIFEST_URL) -> dict[str, Any]:
    if manifest_file:
        try:
            with open(manifest_file, "r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read Flutter release manifest fixture: {exc}") from exc

    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "android-builder-flutter-resolver"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read Flutter release manifest: {exc}") from exc


def release_for(
    manifest: dict[str, Any],
    *,
    version: str = "",
    revision: str = "",
    channel: str = "",
) -> dict[str, Any]:
    releases = manifest.get("releases")
    if not isinstance(releases, list):
        raise ValueError("Flutter release manifest does not contain a releases list.")

    for item in releases:
        if not isinstance(item, dict):
            continue
        if item.get("dart_sdk_arch", "x64") != "x64":
            continue
        if channel and item.get("channel") != channel:
            continue
        if revision and item.get("hash") != revision:
            continue
        if version and item.get("version") != version.lstrip("v"):
            continue
        return item
    selector = f"revision {revision}" if revision else f"version {version}" if version else f"channel {channel}"
    raise ValueError(f"Flutter release manifest has no Linux x64 release matching {selector}.")


def check_constraints(release: dict[str, Any], constraints: dict[str, tuple[int, int, int]]) -> None:
    flutter_version = str(release.get("version", ""))
    flutter_tuple = version_tuple(flutter_version)
    if flutter_tuple is None:
        raise ValueError(f"Flutter release has an invalid version: {flutter_version!r}")
    minimum_flutter = constraints.get("flutter")
    if minimum_flutter and flutter_tuple < minimum_flutter:
        raise ValueError(
            f"Resolved Flutter {flutter_version} is below the project's locked minimum "
            f"{'.'.join(map(str, minimum_flutter))}."
        )

    dart_raw = str(release.get("dart_sdk_version", ""))
    dart_match = re.search(r"\d+\.\d+(?:\.\d+)?", dart_raw)
    dart_tuple = tuple(int(part) for part in dart_match.group(0).split(".")) if dart_match else None
    minimum_dart = constraints.get("dart")
    if minimum_dart and dart_tuple is None:
        raise ValueError("Cannot verify the project's Dart SDK constraint against this Flutter release.")
    if minimum_dart and dart_tuple is not None and (dart_tuple + (0,))[:3] < minimum_dart:
        raise ValueError(
            f"Resolved Flutter {flutter_version} bundles Dart {dart_raw}, below the project's "
            f"locked minimum {'.'.join(map(str, minimum_dart))}."
        )


def resolve_flutter(
    root: Path,
    requested: str = "auto",
    manifest_file: str = "",
    manifest_url: str = MANIFEST_URL,
) -> dict[str, str]:
    requested = (requested or "auto").strip()
    constraints = read_lock_constraints(root)

    if requested in CHANNELS:
        if requested in {"main", "master"}:
            return {
                "flutter_channel": requested,
                "flutter_version": "",
                "flutter_version_source": "manual channel selection",
                "flutter_dart_version": "unknown",
                "flutter_revision": "unknown",
            }
        release = release_for(load_manifest(manifest_file, manifest_url), channel=requested)
        check_constraints(release, constraints)
        source = "manual channel selection"
    elif requested != "auto":
        if not version_tuple(requested):
            raise ValueError(
                f"Invalid flutter_version '{requested}'. Use auto, a channel, or an exact x.y.z version."
            )
        release = release_for(load_manifest(manifest_file, manifest_url), version=requested)
        check_constraints(release, constraints)
        source = "manual version selection"
    else:
        pinned = read_pinned_version(root)
        metadata = read_metadata_revision(root) if not pinned else None
        manifest = None

        if pinned:
            pin, source = pinned
            if pin in CHANNELS:
                if pin in {"main", "master"}:
                    return {
                        "flutter_channel": pin,
                        "flutter_version": "",
                        "flutter_version_source": source,
                        "flutter_dart_version": "unknown",
                        "flutter_revision": "unknown",
                    }
                manifest = load_manifest(manifest_file, manifest_url)
                release = release_for(manifest, channel=pin)
            elif version_tuple(pin):
                manifest = load_manifest(manifest_file, manifest_url)
                release = release_for(manifest, version=pin)
            else:
                raise ValueError(f"Unsupported Flutter version in {source}: {pin!r}")
        elif metadata:
            revision, metadata_channel = metadata
            if metadata_channel in {"main", "master"}:
                return {
                    "flutter_channel": metadata_channel,
                    "flutter_version": revision,
                    "flutter_version_source": ".metadata git revision",
                    "flutter_dart_version": "unknown",
                    "flutter_revision": revision,
                }
            manifest = load_manifest(manifest_file, manifest_url)
            release = release_for(manifest, revision=revision, channel=metadata_channel)
            source = ".metadata pinned revision"
        else:
            manifest = load_manifest(manifest_file, manifest_url)
            release = release_for(manifest, channel="stable")
            source = "latest stable (no project pin found)"

        check_constraints(release, constraints)

    return {
        "flutter_channel": str(release.get("channel", "stable")),
        "flutter_version": str(release.get("version", "")),
        "flutter_version_source": source,
        "flutter_dart_version": str(release.get("dart_sdk_version", "unknown")),
        "flutter_revision": str(release.get("hash", "unknown")),
    }


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
    parser.add_argument("--root", default=".")
    parser.add_argument("--requested", default="auto")
    parser.add_argument("--manifest-file", default="", help=argparse.SUPPRESS)
    parser.add_argument("--manifest-url", default=MANIFEST_URL, help=argparse.SUPPRESS)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1

    try:
        values = resolve_flutter(root, args.requested, args.manifest_file, args.manifest_url)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    write_outputs(values)
    print(
        "Resolved Flutter SDK: "
        f"channel={values['flutter_channel']} "
        f"version={values['flutter_version'] or '<latest>'} "
        f"Dart={values['flutter_dart_version']} "
        f"source={values['flutter_version_source']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
