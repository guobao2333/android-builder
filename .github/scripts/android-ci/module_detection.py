#!/usr/bin/env python3
"""Detect installable Android application modules from Gradle project/task output."""

from __future__ import annotations

import re
from typing import Any


class ModuleSelectionError(ValueError):
    """Raised when a requested Android application module cannot be selected."""


def canonical_module(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith(":"):
        raw = ":" + raw
    return re.sub(r":+", ":", raw)


def parse_gradle_projects(output: str) -> list[str]:
    """Extract Gradle project paths while preserving Gradle's project order."""

    modules: list[str] = []
    for line in output.splitlines():
        match = re.search(r"Project '(:[^']+)'", line)
        if not match:
            continue
        module = canonical_module(match.group(1))
        if module != ":" and module not in modules:
            modules.append(module)
    return modules


def parse_module_request(raw: str) -> tuple[str, list[str]]:
    """Return (mode, modules) for auto, all, or an explicit comma-separated list."""

    request = (raw or "").strip()
    if not request or request.casefold() == "auto":
        return "auto", []
    if request.casefold() == "all":
        return "all", []

    modules = list(dict.fromkeys(
        canonical_module(item) for item in request.split(",") if item.strip()
    ))
    if not modules:
        raise ModuleSelectionError(
            "The module input is empty after parsing. Use 'auto', 'all', or a comma-separated module list."
        )
    return "explicit", modules


def is_installable_application(tasks: list[str]) -> bool:
    """Recognize Android application modules without relying on a directory name."""

    return any(task.startswith("install") for task in tasks) or any(
        task.startswith("bundle") and not task.endswith("Aar") for task in tasks
    )


def select_modules(
    requested: str,
    all_modules: list[str],
    tasks_by_module: dict[str, list[str]],
) -> dict[str, Any]:
    """Resolve requested modules and explain whether selection was automatic or explicit."""

    mode, requested_modules = parse_module_request(requested)
    modules = list(dict.fromkeys(canonical_module(item) for item in all_modules))
    candidates = [
        module for module in modules
        if is_installable_application(tasks_by_module.get(module, []))
    ]

    if mode == "auto":
        if not candidates:
            raise ModuleSelectionError(
                "Automatic module detection found no installable Android Application modules. "
                "Detected Gradle subprojects: "
                + (", ".join(modules) if modules else "none")
                + ". Check the Gradle plugins/tasks or specify a module explicitly."
            )
        if len(candidates) > 1:
            raise ModuleSelectionError(
                "Automatic module detection found multiple Android Application candidates: "
                + ", ".join(candidates)
                + ". The main module is ambiguous; specify one or more modules explicitly, "
                "or use module=all to build every detected application."
            )
        selected = candidates
        reason = (
            "Selected the only detected installable Android Application module: "
            + selected[0]
            + ". The module name does not need to be 'app'."
        )
    elif mode == "all":
        if not candidates:
            raise ModuleSelectionError(
                "module=all was requested, but no installable Android Application modules were detected. "
                "Detected Gradle subprojects: "
                + (", ".join(modules) if modules else "none")
                + "."
            )
        selected = candidates
        reason = "Selected all detected installable Android Application modules."
    else:
        unknown = [module for module in requested_modules if module not in modules]
        if unknown:
            raise ModuleSelectionError(
                "Unknown module(s): "
                + ", ".join(unknown)
                + ". Available Gradle subprojects: "
                + (", ".join(modules) if modules else "none")
            )

        not_app = [
            module for module in requested_modules
            if not is_installable_application(tasks_by_module.get(module, []))
        ]
        if not_app:
            details = []
            for module in not_app:
                tasks = tasks_by_module.get(module, [])
                details.append(
                    f"{module} (detected tasks: {', '.join(tasks[:12]) if tasks else 'none'})"
                )
            raise ModuleSelectionError(
                "Requested module(s) do not expose installable Android Application tasks: "
                + "; ".join(details)
                + ". Select an application module, use 'auto', or use 'all'."
            )

        selected = requested_modules
        reason = "Used the explicitly requested module list: " + ", ".join(selected) + "."

    return {
        "mode": mode,
        "selected": selected,
        "candidates": candidates,
        "reason": reason,
    }
