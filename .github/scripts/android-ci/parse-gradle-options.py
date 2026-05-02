#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import sys
from typing import List


def gha_error(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    sys.exit(1)


def validate_args(args: List[str]) -> List[str]:
    for arg in args:
        if not isinstance(arg, str):
            gha_error("build_options JSON array must contain strings only.")
        if arg == "":
            gha_error("build_options must not contain empty arguments.")
        if "\n" in arg or "\r" in arg:
            gha_error("build_options arguments must not contain newlines.")
    return args


def parse_raw(raw: str) -> List[str]:
    raw = raw or ""
    if not raw.strip():
        return []

    stripped = raw.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            gha_error(f"Invalid build_options JSON array: {exc}")
        if not isinstance(data, list):
            gha_error("build_options JSON input must be an array of strings.")
        return validate_args(data)

    try:
        return validate_args(shlex.split(raw, posix=True))
    except ValueError as exc:
        gha_error(f"Invalid build_options shell quoting: {exc}")


def parse_json_env(raw: str) -> List[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        gha_error(f"Invalid normalized build_options JSON: {exc}")
    if not isinstance(data, list):
        gha_error("Normalized build_options must be a JSON array.")
    return validate_args(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Gradle build_options.")
    parser.add_argument("--from-json", action="store_true", help="Read BUILD_OPTIONS_JSON instead of BUILD_OPTIONS.")
    parser.add_argument("--format", choices=("json", "lines", "display"), default="json")
    args = parser.parse_args()

    options = parse_json_env(os.environ.get("BUILD_OPTIONS_JSON", "[]")) if args.from_json else parse_raw(os.environ.get("BUILD_OPTIONS", ""))

    if args.format == "json":
        print(json.dumps(options, ensure_ascii=False, separators=(",", ":")))
    elif args.format == "lines":
        for option in options:
            print(option)
    else:
        print(shlex.join(options))


if __name__ == "__main__":
    main()
