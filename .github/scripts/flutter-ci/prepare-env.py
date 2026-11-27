#!/usr/bin/env python3
"""Prepare a parseable .env asset in the temporary Flutter CI checkout."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PLACEHOLDER_ENTRY = "ANDROID_BUILDER_CI_PLACEHOLDER=true"


def has_entries(content: str) -> bool:
    """Return whether the dotenv file contains a non-comment entry."""

    return any(
        line.strip() and not line.strip().startswith("#")
        for line in content.splitlines()
    )


def prepare_env(root: Path) -> tuple[str, bool]:
    env_path = root / ".env"
    example_path = root / ".env.example"

    if env_path.exists() and not env_path.is_file():
        raise ValueError(".env exists but is not a regular file.")
    if example_path.exists() and not example_path.is_file():
        raise ValueError(".env.example exists but is not a regular file.")

    if env_path.is_file():
        content = env_path.read_text(encoding="utf-8")
        source = ".env"
        if not has_entries(content) and example_path.is_file():
            example = example_path.read_text(encoding="utf-8")
            if has_entries(example):
                content = example
                source = ".env.example"
    elif example_path.is_file():
        content = example_path.read_text(encoding="utf-8")
        source = ".env.example"
    else:
        content = ""
        source = "CI fallback"

    placeholder_added = not has_entries(content)
    if placeholder_added:
        if content and not content.endswith("\n"):
            content += "\n"
        content += PLACEHOLDER_ENTRY + "\n"

    if not env_path.is_file() or env_path.read_text(encoding="utf-8") != content:
        env_path.write_text(content, encoding="utf-8")

    return source, placeholder_added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Flutter project directory not found: {root}", file=sys.stderr)
        return 1

    try:
        source, placeholder_added = prepare_env(root)
    except (OSError, ValueError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    print(f"Prepared .env from {source}.")
    if placeholder_added:
        print(
            "::warning::.env had no usable entries; added "
            "ANDROID_BUILDER_CI_PLACEHOLDER=true so optional dotenv loading "
            "does not fail on an empty asset. App-specific configuration is still absent."
        )

    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"env_source={source.replace(' ', '_')}\n")
            stream.write(f"env_placeholder_added={'true' if placeholder_added else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
