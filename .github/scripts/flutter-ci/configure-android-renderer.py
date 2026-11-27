#!/usr/bin/env python3
"""Configure the Android Flutter renderer in the temporary CI checkout."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

META_NAME = "io.flutter.embedding.android.EnableImpeller"


def configure_renderer(root: Path, backend: str) -> bool:
    backend = backend.strip().lower()
    if backend not in {"impeller", "skia"}:
        raise ValueError(f"Unsupported Android renderer '{backend}'. Choose 'impeller' or 'skia'.")

    manifest = root / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    try:
        content = manifest.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Unable to read Android manifest at {manifest}: {exc}") from exc

    value = "true" if backend == "impeller" else "false"
    meta_pattern = re.compile(
        rf"<meta-data\b(?=[^>]*\bandroid:name\s*=\s*['\"]{re.escape(META_NAME)}['\"])[^>]*/?>",
        re.S,
    )
    match = meta_pattern.search(content)
    if match:
        tag = match.group(0)
        value_pattern = re.compile(r"\bandroid:value\s*=\s*(['\"])[^'\"]*\1")
        if value_pattern.search(tag):
            updated_tag = value_pattern.sub(f'android:value="{value}"', tag, count=1)
        else:
            closing = "/>" if tag.rstrip().endswith("/>") else ">"
            updated_tag = tag.rstrip()[:-len(closing)].rstrip() + f' android:value="{value}" {closing}'
        if updated_tag == tag:
            return False
        content = content[:match.start()] + updated_tag + content[match.end():]
    else:
        application = re.search(r"<application\b[^>]*>", content, re.S)
        if not application:
            raise ValueError("Android manifest does not contain an <application> element.")
        tag = f'<meta-data android:name="{META_NAME}" android:value="{value}" />'
        content = content[:application.end()] + "\n        " + tag + content[application.end():]

    manifest.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--backend", choices=("impeller", "skia"), required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error::Project directory not found: {root}", file=sys.stderr)
        return 1
    try:
        changed = configure_renderer(root, args.backend)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    print(f"Android renderer: {args.backend} ({'updated CI manifest' if changed else 'already configured'})")
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"renderer={args.backend}\n")
            stream.write(f"renderer_manifest_changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
