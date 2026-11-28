#!/usr/bin/env python3
"""NDK revision and official preview archive metadata for Android CI."""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from typing import Sequence

# Gradle's NDK version and source.properties Pkg.Revision are not always equal.
# Preview releases can have a suffixed Pkg.Revision while keeping the base
# revision as their SDK directory and Gradle ndkVersion.
NDK_PKG_REVISIONS = {
    "29.0.13113456": "29.0.13113456-beta1",
}

# These beta archives are published by the official android/ndk release, but
# are not listed as installable packages in the standard sdkmanager repository.
# Checksums are copied from the corresponding official release page.
NDK_PREVIEW_DOWNLOADS = {
    "29.0.13113456": {
        "pkg_revision": "29.0.13113456-beta1",
        "assets": {
            "linux": {
                "url": "https://dl.google.com/android/repository/android-ndk-r29-beta1-linux.zip",
                "sha1": "ec2d8801e42009edf66be853c1bab9ba216378f9",
                "format": "zip",
            },
            "darwin": {
                "url": "https://dl.google.com/android/repository/android-ndk-r29-beta1-darwin.dmg",
                "sha1": "b3a8e0d8147de981478c8edefe4036440910ee46",
                "format": "dmg",
            },
        },
    },
}

NDK_REVISIONS = OrderedDict(
    (
        ("r29", "29.0.14033849"),
        ("r28c", "28.2.13676358"),
        ("r27d", "27.3.13750724"),
        ("r26d", "26.3.11579264"),
        ("r25c", "25.2.9519653"),
        ("r24", "24.0.8215888"),
        ("r23c", "23.2.8568313"),
        ("r22b", "22.1.7171670"),
        ("r21e", "21.4.7075529"),
        ("r20b", "20.1.5948944"),
    )
)


def resolve_ndk_revision(value: str) -> str:
    value = value.strip()
    if value in NDK_REVISIONS:
        return NDK_REVISIONS[value]
    parts = value.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return value
    aliases = ", ".join(NDK_REVISIONS)
    raise ValueError(f"Unable to map NDK version '{value}' to a full SDK revision. Known aliases: {aliases}")


def resolve_ndk_pkg_revision(value: str) -> str:
    """Resolve source.properties Pkg.Revision for an NDK version."""
    revision = resolve_ndk_revision(value)
    return NDK_PKG_REVISIONS.get(revision, revision)


def resolve_preview_download(value: str, platform: str) -> dict[str, str] | None:
    """Return verified official archive metadata for a known preview NDK."""
    revision = resolve_ndk_revision(value)
    release = NDK_PREVIEW_DOWNLOADS.get(revision)
    if release is None:
        return None
    asset = release["assets"].get(platform)
    if asset is None:
        raise ValueError(f"No official NDK preview archive is configured for platform '{platform}'.")
    return {
        "pkg_revision": release["pkg_revision"],
        **asset,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    version_group = parser.add_mutually_exclusive_group()
    version_group.add_argument("--resolve", metavar="VERSION", help="Print the NDK base revision.")
    version_group.add_argument("--pkg-revision", metavar="VERSION", help="Print source.properties Pkg.Revision.")
    version_group.add_argument("--preview-download", metavar="VERSION", help="Print official preview download metadata.")
    parser.add_argument("--platform", choices=("linux", "darwin"), help="Host platform for --preview-download.")
    parser.add_argument("--aliases", action="store_true", help="Print supported aliases as a comma-separated list.")
    parser.add_argument("--choices-json", action="store_true", help="Print supported workflow choices as a JSON-style list.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    ns = parse_args(argv or sys.argv[1:])
    try:
        if ns.resolve:
            print(resolve_ndk_revision(ns.resolve))
            return 0
        if ns.pkg_revision:
            print(resolve_ndk_pkg_revision(ns.pkg_revision))
            return 0
        if ns.preview_download:
            if not ns.platform:
                raise ValueError("--platform is required with --preview-download.")
            metadata = resolve_preview_download(ns.preview_download, ns.platform)
            if metadata is None:
                return 1
            print("\\t".join((metadata["url"], metadata["sha1"], metadata["format"], metadata["pkg_revision"])))
            return 0
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if ns.aliases:
        print(",".join(NDK_REVISIONS))
        return 0
    if ns.choices_json:
        print("[" + ", ".join(repr(alias) for alias in NDK_REVISIONS) + "]")
        return 0
    print("::error::No action specified. Use --resolve, --pkg-revision, --preview-download, --aliases, or --choices-json.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
