#!/usr/bin/env python3
"""NDK version aliases shared by Android CI helper scripts."""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from typing import Sequence

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


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", metavar="VERSION", help="Print the full SDK NDK revision for an alias or revision.")
    parser.add_argument("--aliases", action="store_true", help="Print supported aliases as a comma-separated list.")
    parser.add_argument("--choices-json", action="store_true", help="Print supported workflow choices as a JSON-style list.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    ns = parse_args(argv or sys.argv[1:])
    if ns.resolve:
        try:
            print(resolve_ndk_revision(ns.resolve))
        except ValueError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        return 0
    if ns.aliases:
        print(",".join(NDK_REVISIONS))
        return 0
    if ns.choices_json:
        print("[" + ", ".join(repr(alias) for alias in NDK_REVISIONS) + "]")
        return 0
    print("::error::No action specified. Use --resolve, --aliases, or --choices-json.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
