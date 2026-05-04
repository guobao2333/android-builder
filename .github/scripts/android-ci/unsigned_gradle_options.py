#!/usr/bin/env python3
"""Shared helpers for Android CI's -Punsigned Gradle option handling."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Sequence

TRUE_VALUES = {"", "1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


def unsigned_state(arg: str) -> str:
    """Return true/false/other/empty for a Gradle -Punsigned argument."""
    if arg == "-Punsigned":
        return "true"
    if arg.startswith("-Punsigned="):
        value = arg.split("=", 1)[1].strip().lower()
        if value in TRUE_VALUES:
            return "true"
        if value in FALSE_VALUES:
            return "false"
        return "other"
    return ""


def has_explicit_unsigned(args: Sequence[str]) -> bool:
    return any(unsigned_state(arg) == "true" for arg in args)


def ensure_unsigned(args: Sequence[str]) -> tuple[list[str], bool]:
    """Return args with exactly one effective unsigned=true intent.

    Explicit true values are preserved. Explicit false values are removed before
    appending -Punsigned so Gradle does not receive conflicting properties.
    """
    if has_explicit_unsigned(args):
        return list(args), False
    cleaned = [arg for arg in args if unsigned_state(arg) != "false"]
    cleaned.append("-Punsigned")
    return cleaned, True


def read_json_options(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid BUILD_OPTIONS_JSON: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise SystemExit("BUILD_OPTIONS_JSON must be a JSON array of strings.")
    return data


def emit(args: Sequence[str], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(list(args), ensure_ascii=False, separators=(",", ":")))
    elif output_format == "display":
        print(shlex.join(args))
    elif output_format == "lines":
        for arg in args:
            print(arg)
    else:
        raise SystemExit(f"Unsupported output format: {output_format}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", action="store_true", help="Read arguments from BUILD_OPTIONS_JSON instead of argv.")
    parser.add_argument("--ensure-unsigned", action="store_true", help="Append -Punsigned if no effective unsigned=true argument exists.")
    parser.add_argument("--has-explicit-unsigned", action="store_true", help="Exit 0 if an effective unsigned=true argument exists; otherwise exit 1.")
    parser.add_argument("--format", choices=("json", "display", "lines"), default="lines")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)
    if ns.args and ns.args[0] == "--":
        ns.args = ns.args[1:]
    return ns


def main(argv: Sequence[str] | None = None) -> int:
    ns = parse_args(argv or sys.argv[1:])
    args = read_json_options(os.environ.get("BUILD_OPTIONS_JSON", "[]")) if ns.from_json else list(ns.args)

    if ns.has_explicit_unsigned:
        return 0 if has_explicit_unsigned(args) else 1

    if ns.ensure_unsigned:
        args, _ = ensure_unsigned(args)

    emit(args, ns.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
