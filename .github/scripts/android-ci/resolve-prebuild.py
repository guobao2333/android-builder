#!/usr/bin/env python3
import os
from pathlib import Path


def write_output(name: str, value: str, multiline: bool = False) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"{name}={value}")
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        if multiline:
            marker = "__PRE_BUILD_COMMAND__"
            fh.write(f"{name}<<{marker}\n{value}\n{marker}\n")
        else:
            fh.write(f"{name}={value}\n")


def command_uses_go(command: str) -> bool:
    return "go" in command or "gomobile" in command or "./run lib core" in command


def main() -> None:
    raw_command = os.environ.get("PRE_BUILD_COMMAND_INPUT", "").strip()
    command_lower = raw_command.lower()

    needed = "false"
    uses_go = "false"
    cache_path = ""
    mode = "none"
    command_value = ""

    if command_lower in {"", "none", "skip"}:
        mode = "none"
    elif command_lower == "auto":
        if Path("./run").is_file() and Path("libcore/build.sh").is_file():
            needed = "true"
            uses_go = "true"
            cache_path = "app/libs/libcore.aar"
            mode = "auto-nekobox-libcore"
            command_value = "./run lib core"
        else:
            mode = "auto-none"
    else:
        needed = "true"
        mode = "manual"
        command_value = raw_command
        if command_uses_go(raw_command):
            uses_go = "true"

    write_output("needed", needed)
    write_output("uses_go", uses_go)
    write_output("cache_path", cache_path)
    write_output("mode", mode)
    write_output("command", command_value, multiline=True)

    print(f"Pre-build mode: {mode}")
    print(f"Pre-build needed: {needed}")
    if needed == "true":
        print(f"Pre-build command: {command_value}")
        if cache_path:
            print(f"Pre-build output/cache path: {cache_path}")


if __name__ == "__main__":
    main()
