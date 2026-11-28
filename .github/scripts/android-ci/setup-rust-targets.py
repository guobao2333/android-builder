#!/usr/bin/env python3
"""Detect Android Rust target triples used by a project and install their rust-std components."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

EXCLUDED_DIRS = {
    ".git", ".gradle", ".idea", ".kotlin", ".dart_tool", ".fvm",
    "build", "target", "out", "node_modules", "Pods", ".ci-workflow",
}
SCAN_SUFFIXES = {".gradle", ".kts", ".toml", ".sh", ".properties"}
ANDROID_TARGETS = (
    "aarch64-linux-android",
    "armv7-linux-androideabi",
    "i686-linux-android",
    "x86_64-linux-android",
)
ABI_TO_TARGET = {
    "arm64-v8a": "aarch64-linux-android",
    "armeabi-v7a": "armv7-linux-androideabi",
    "x86": "i686-linux-android",
    "x86_64": "x86_64-linux-android",
}


def iter_project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        for name in names:
            path = Path(current) / name
            if path.suffix.lower() in SCAN_SUFFIXES:
                try:
                    if path.stat().st_size <= 1_000_000:
                        files.append(path)
                except OSError:
                    continue
    return sorted(files)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def find_cargo_manifests(root: Path) -> list[Path]:
    manifests: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        if "Cargo.toml" in names:
            manifests.append(Path(current) / "Cargo.toml")
    return sorted(manifests)


def detect_android_targets(root: Path) -> dict[str, Any]:
    """Find exact Rust Android triples or infer them from Android ABI filters."""

    manifests = find_cargo_manifests(root)
    manifest_paths = [path.relative_to(root).as_posix() for path in manifests]
    if not manifests:
        return {
            "manifests": [],
            "targets": [],
            "source": "No Cargo.toml files found.",
        }

    contents = [(path, read_text(path)) for path in iter_project_files(root)]
    explicit: set[str] = set()
    for _, content in contents:
        for target in ANDROID_TARGETS:
            if target in content:
                explicit.add(target)

    if explicit:
        targets = sorted(explicit)
        source = "Explicit Android Rust target triple(s) found in Gradle, Cargo, or shell configuration."
    else:
        abis: set[str] = set()
        for _, content in contents:
            for match in re.finditer(r"\babiFilters\b", content):
                block = content[match.start():match.start() + 500]
                for abi in ABI_TO_TARGET:
                    if re.search(r"['\"]" + re.escape(abi) + r"['\"]", block):
                        abis.add(abi)
            for match in re.finditer(r"(?:--target-abi|-t)\s*['\"]?([A-Za-z0-9_-]+)", content):
                if match.group(1) in ABI_TO_TARGET:
                    abis.add(match.group(1))
        targets = sorted({ABI_TO_TARGET[abi] for abi in abis})
        source = (
            "Inferred Rust targets from Android ABI filters / cargo-ndk ABI arguments."
            if targets else
            "Cargo projects were found, but no Android Rust target or Android ABI filter was detected."
        )

    return {
        "manifests": manifest_paths,
        "targets": targets,
        "source": source,
    }


def find_rustup() -> str:
    executable = shutil.which("rustup")
    if executable:
        return executable
    fallback = Path.home() / ".cargo" / "bin" / ("rustup.exe" if os.name == "nt" else "rustup")
    return str(fallback) if fallback.is_file() else ""


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def rust_target_has_core(target: str, cwd: Path) -> bool:
    rustc = shutil.which("rustc")
    if not rustc:
        fallback = Path.home() / ".cargo" / "bin" / ("rustc.exe" if os.name == "nt" else "rustc")
        rustc = str(fallback) if fallback.is_file() else ""
    if not rustc:
        return False

    result = run([rustc, "--print", "target-libdir", "--target", target], cwd)
    if result.returncode != 0:
        return False
    libdir = Path(result.stdout.strip().splitlines()[-1])
    if not libdir.is_dir():
        return False
    return any(libdir.glob("libcore-*.rlib")) or any(libdir.glob("libcore-*.rmeta"))


def install_targets(root: Path, manifests: list[str], targets: list[str]) -> dict[str, Any]:
    if not targets:
        return {"status": "skipped", "installed": [], "already_installed": [], "detail": "No Android Rust target was detected."}

    rustup = find_rustup()
    if not rustup:
        # Non-rustup distributions are allowed when their target standard libraries already exist.
        missing = [
            f"{manifest}: {target}"
            for manifest in manifests
            for target in targets
            if not rust_target_has_core(target, root / Path(manifest).parent)
        ]
        if missing:
            raise RuntimeError(
                "Rust Android targets are required, but rustup is unavailable and the target "
                "standard library is missing: " + ", ".join(missing)
            )
        return {
            "status": "verified",
            "installed": [],
            "already_installed": targets,
            "detail": "Verified existing Rust target libraries; rustup is not installed.",
        }

    installed: list[str] = []
    already_installed: list[str] = []
    details: list[str] = []
    manifest_dirs = [root / Path(manifest).parent for manifest in manifests]

    for cwd in manifest_dirs:
        listing = run([rustup, "target", "list", "--installed"], cwd)
        if listing.returncode != 0:
            raise RuntimeError(
                f"Unable to list installed Rust targets in {cwd}: {listing.stdout.strip()}"
            )
        current = set(listing.stdout.splitlines())

        for target in targets:
            if target not in current:
                result = run([rustup, "target", "add", target], cwd)
                if result.returncode != 0:
                    raise RuntimeError(
                        f"Failed to install Rust target '{target}' for Cargo project "
                        f"{cwd}: {result.stdout.strip()}"
                    )
                installed.append(target)
                current.add(target)
                details.append(f"Installed {target} for {cwd.relative_to(root).as_posix() or '.'}")
            else:
                already_installed.append(target)

            if not rust_target_has_core(target, cwd):
                raise RuntimeError(
                    f"Rust target '{target}' is listed as installed, but its core library "
                    f"cannot be found for Cargo project {cwd}."
                )

    return {
        "status": "ready",
        "installed": sorted(set(installed)),
        "already_installed": sorted(set(already_installed)),
        "detail": "; ".join(details) if details else "All required Rust target libraries were already installed.",
    }


def write_summary(detection: dict[str, Any], preparation: dict[str, Any], error: str = "") -> None:
    rows = [
        "## Android Rust target preparation",
        "",
        f"- **Status:** {preparation['status']}",
        f"- **Cargo manifests:** {', '.join(detection['manifests']) if detection['manifests'] else 'none'}",
        f"- **Required Android Rust targets:** {', '.join(detection['targets']) if detection['targets'] else 'none detected'}",
        f"- **Detection source:** {detection['source']}",
        f"- **Newly installed targets:** {', '.join(preparation.get('installed', [])) or 'none'}",
        f"- **Already installed targets:** {', '.join(preparation.get('already_installed', [])) or 'none'}",
        f"- **Details:** {preparation.get('detail', '')}",
    ]
    if error:
        rows.extend(["", f"- **Failure reason:** {error}"])
    rows.append("")
    summary = "\n".join(rows)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write(summary)
    print(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1

    detection = detect_android_targets(root)
    try:
        preparation = install_targets(root, detection["manifests"], detection["targets"])
    except RuntimeError as exc:
        preparation = {
            "status": "failed",
            "installed": [],
            "already_installed": [],
            "detail": "Rust target preparation did not complete.",
        }
        write_summary(detection, preparation, str(exc))
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if preparation["status"] == "skipped":
        print("No Android Rust target installation was needed.")
    write_summary(detection, preparation)
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"rust_targets={','.join(detection['targets'])}\n")
            stream.write(f"rust_target_status={preparation['status']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
