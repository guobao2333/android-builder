#!/usr/bin/env python3
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

from unsigned_gradle_options import has_explicit_unsigned


EXCLUDED_DIRS = {".git", ".gradle", "build", ".idea", ".github", "node_modules"}
SIGNING_FILE_NAMES = {
    "keystore.properties",
    "key.properties",
    "signing.properties",
    "signing-config.properties",
    "release.properties",
    "gradle.properties",
    "local.properties",
}
SIGNING_FILE_PATTERNS = (
    "*.jks",
    "*.keystore",
    "*.p12",
    "*.pfx",
)
GRADLE_FILE_PATTERNS = (
    "build.gradle",
    "build.gradle.kts",
    "*.gradle",
    "*.gradle.kts",
)

# Complete environment-variable groups that commonly describe Android release signing.
ENV_GROUPS: Sequence[Tuple[str, Sequence[str]]] = (
    ("ANDROID_INJECTED_SIGNING_*", (
        "ANDROID_INJECTED_SIGNING_STORE_FILE",
        "ANDROID_INJECTED_SIGNING_STORE_PASSWORD",
        "ANDROID_INJECTED_SIGNING_KEY_ALIAS",
        "ANDROID_INJECTED_SIGNING_KEY_PASSWORD",
    )),
    ("SIGNING_KEYSTORE_BASE64", (
        "SIGNING_KEYSTORE_BASE64",
        "SIGNING_STORE_PASSWORD",
        "SIGNING_KEY_ALIAS",
        "SIGNING_KEY_PASSWORD",
    )),
    ("SIGNING_KEY", (
        "SIGNING_KEY",
        "SIGNING_STORE_PASSWORD",
        "SIGNING_KEY_ALIAS",
        "SIGNING_KEY_PASSWORD",
    )),
    ("SIGNING_KEYSTORE_FILE", (
        "SIGNING_KEYSTORE_FILE",
        "SIGNING_STORE_PASSWORD",
        "SIGNING_KEY_ALIAS",
        "SIGNING_KEY_PASSWORD",
    )),
    ("KEYSTORE_BASE64", (
        "KEYSTORE_BASE64",
        "KEYSTORE_PASSWORD",
        "KEY_ALIAS",
        "KEY_PASSWORD",
    )),
    ("KEYSTORE_FILE", (
        "KEYSTORE_FILE",
        "KEYSTORE_PASSWORD",
        "KEY_ALIAS",
        "KEY_PASSWORD",
    )),
    ("ANDROID_KEYSTORE_BASE64", (
        "ANDROID_KEYSTORE_BASE64",
        "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS",
        "ANDROID_KEY_PASSWORD",
    )),
    ("ANDROID_KEYSTORE_FILE", (
        "ANDROID_KEYSTORE_FILE",
        "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS",
        "ANDROID_KEY_PASSWORD",
    )),
    ("RELEASE_KEYSTORE_BASE64", (
        "RELEASE_KEYSTORE_BASE64",
        "RELEASE_STORE_PASSWORD",
        "RELEASE_KEY_ALIAS",
        "RELEASE_KEY_PASSWORD",
    )),
    ("RELEASE_KEYSTORE_FILE", (
        "RELEASE_KEYSTORE_FILE",
        "RELEASE_STORE_PASSWORD",
        "RELEASE_KEY_ALIAS",
        "RELEASE_KEY_PASSWORD",
    )),
    ("STORE_FILE", (
        "STORE_FILE",
        "STORE_PASSWORD",
        "KEY_ALIAS",
        "KEY_PASSWORD",
    )),
)

# Complete Gradle/property key groups. Keys are compared after removing punctuation.
PROPERTY_GROUPS: Sequence[Tuple[str, Sequence[str]]] = (
    ("android.injected.signing", (
        "androidinjectedsigningstorefile",
        "androidinjectedsigningstorepassword",
        "androidinjectedsigningkeyalias",
        "androidinjectedsigningkeypassword",
    )),
    ("storeFile/storePassword/keyAlias/keyPassword", (
        "storefile",
        "storepassword",
        "keyalias",
        "keypassword",
    )),
    ("signingStore*", (
        "signingstorefile",
        "signingstorepassword",
        "signingkeyalias",
        "signingkeypassword",
    )),
    ("keystore*", (
        "keystorefile",
        "keystorepassword",
        "keyalias",
        "keypassword",
    )),
    ("releaseStore*", (
        "releasestorefile",
        "releasestorepassword",
        "releasekeyalias",
        "releasekeypassword",
    )),
    ("releaseKeystore*", (
        "releasekeystore",
        "releasestorepassword",
        "releasekeyalias",
        "releasekeypassword",
    )),
)

SIGNING_KEY_HINTS = (
    "storefile",
    "storepassword",
    "keyalias",
    "keypassword",
    "keystore",
    "signingstore",
    "signingkey",
    "releasestore",
    "releasekey",
    "androidinjectedsigning",
)


def gha_error(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    sys.exit(1)


def gha_warning(message: str) -> None:
    print(f"::warning::{message}")


def parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def read_options(raw: str) -> List[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        gha_error(f"Invalid BUILD_OPTIONS_JSON: {exc}")
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        gha_error("BUILD_OPTIONS_JSON must be a JSON array of strings.")
    return data


def output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def under_excluded_dir(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def safe_read_text(path: Path, limit: int = 1_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def property_values_from_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*(?:=|:)\s*(.*)$", stripped)
        if match:
            values[normalize_key(match.group(1))] = match.group(2).strip().strip('"\'')
    return values


def looks_concrete_signing_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in {"changeme", "change-me", "todo", "tbd", "none", "null", "xxxx", "xxx"}:
        return False
    # Values that are only unresolved placeholders should be backed by env/vars
    # detection rather than counted as complete repository-side config.
    if re.search(r"\$\{|system\.getenv|providers\.environmentvariable|secrets\.|vars\.", stripped, re.IGNORECASE):
        return False
    return True


def complete_property_group(keys: set[str]) -> str:
    for label, required in PROPERTY_GROUPS:
        if all(key in keys for key in required):
            return label
    return ""


def complete_property_group_from_values(values: dict[str, str]) -> str:
    keys = set(values)
    for label, required in PROPERTY_GROUPS:
        if all(key in keys and looks_concrete_signing_value(values[key]) for key in required):
            return label
    return ""


def gradle_prop_keys_from_args(args: Sequence[str]) -> set[str]:
    keys: set[str] = set()
    for arg in args:
        if not arg.startswith("-P") or arg == "-P":
            continue
        body = arg[2:]
        key = body.split("=", 1)[0]
        if key:
            keys.add(normalize_key(key))
    return keys


def detect_env_config() -> list[str]:
    sources: list[str] = []
    for label, names in ENV_GROUPS:
        if all(os.environ.get(name, "") != "" for name in names):
            sources.append(f"variables/secrets:{label}")
    return sources


def detect_repo_config(root: Path) -> tuple[list[str], bool]:
    sources: list[str] = []
    gradle_declares_signing = False
    signing_key_file_found = False
    property_file_has_signing_hints = False

    # Keystore-like files in the repository are useful evidence, but passwords/alias
    # are still required before treating the repository config as complete.
    for pattern in SIGNING_FILE_PATTERNS:
        for path in root.rglob(pattern):
            rel = path.relative_to(root)
            if under_excluded_dir(rel):
                continue
            signing_key_file_found = True
            sources.append(f"repo-file:{rel.as_posix()}")
            break
        if signing_key_file_found:
            break

    property_paths: list[Path] = []
    for path in root.rglob("*.properties"):
        rel = path.relative_to(root)
        if under_excluded_dir(rel):
            continue
        if path.name in SIGNING_FILE_NAMES or any(token in path.name.lower() for token in ("sign", "key", "release", "store")):
            property_paths.append(path)

    complete_property_sources: list[str] = []
    for path in property_paths:
        rel = path.relative_to(root)
        text = safe_read_text(path)
        if not text:
            continue
        values = property_values_from_text(text)
        if any(
            any(hint in key for hint in SIGNING_KEY_HINTS) and looks_concrete_signing_value(value)
            for key, value in values.items()
        ):
            property_file_has_signing_hints = True
        label = complete_property_group_from_values(values)
        if label:
            complete_property_sources.append(f"repo-properties:{rel.as_posix()}:{label}")

    for pattern in GRADLE_FILE_PATTERNS:
        for path in root.rglob(pattern):
            rel = path.relative_to(root)
            if under_excluded_dir(rel):
                continue
            text = safe_read_text(path)
            if not text:
                continue
            if re.search(r"\bsigningConfigs\b|\bsigningConfig\b|storePassword|keyAlias", text):
                gradle_declares_signing = True
                sources.append(f"gradle-signing-declaration:{rel.as_posix()}")
                break
        if gradle_declares_signing:
            break

    # A complete property file is sufficient. A checked-in keystore plus signing
    # property hints is also treated as repository-side config.
    complete_sources = list(complete_property_sources)
    if signing_key_file_found and property_file_has_signing_hints:
        complete_sources.append("repo-keystore-and-properties")

    if complete_sources:
        return complete_sources, gradle_declares_signing
    return [], gradle_declares_signing



def main() -> None:
    requested_signing = parse_bool(os.environ.get("SIGNING_INPUT", "false"))
    options = read_options(os.environ.get("BUILD_OPTIONS_JSON", "[]"))

    arg_property_keys = gradle_prop_keys_from_args(options)
    arg_property_label = complete_property_group(arg_property_keys)
    option_sources = [f"build_options:{arg_property_label}"] if arg_property_label else []

    env_sources = detect_env_config()
    repo_sources, gradle_declares_signing = detect_repo_config(Path.cwd())

    detected_sources = option_sources + env_sources + repo_sources
    signing_config_detected = bool(detected_sources)
    explicit_unsigned = has_explicit_unsigned(options)

    # Important: do not append -Punsigned globally here. Debug variants normally
    # use Android's debug keystore and should remain untouched. run-gradle.sh
    # applies the unsigned property only to release/aggregate tasks, and retries
    # debug/other tasks with -Punsigned only when they fail with signing errors.
    if explicit_unsigned:
        effective_signing = "unsigned"
        unsigned_scope = "all"
        unsigned_reason = "build_options already contains -Punsigned"
    elif requested_signing and signing_config_detected:
        effective_signing = "signed"
        unsigned_scope = "none"
        unsigned_reason = "signing requested and signing config detected"
    else:
        effective_signing = "unsigned"
        unsigned_scope = "release"
        if not requested_signing:
            unsigned_reason = "signing input is disabled; release artifacts will be built unsigned"
        elif gradle_declares_signing:
            unsigned_reason = "signing requested but no complete signing config was detected; release signing declaration exists"
        else:
            unsigned_reason = "signing requested but no complete signing config was detected"
        if requested_signing and not signing_config_detected:
            gha_warning("Signing was requested, but no complete repository/variable signing config was detected. Release tasks will use -Punsigned to avoid build failures.")

    build_options_json = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
    build_options_display = shlex.join(options)
    sources_display = ", ".join(detected_sources) if detected_sources else "none"

    output("build_options_json", build_options_json)
    output("build_options_display", build_options_display)
    output("signing_config_detected", "true" if signing_config_detected else "false")
    output("signing_config_sources", sources_display)
    output("effective_signing", effective_signing)
    output("unsigned_scope", unsigned_scope)
    output("unsigned_reason", unsigned_reason)

    print(f"Signing input: {'enabled' if requested_signing else 'disabled'}")
    print(f"Signing config detected: {'yes' if signing_config_detected else 'no'}")
    print(f"Gradle declares signing: {'yes' if gradle_declares_signing else 'no'}")
    print(f"Signing config sources: {sources_display}")
    print(f"Effective signing mode: {effective_signing}")
    print(f"Unsigned scope: {unsigned_scope}")
    print(f"Unsigned fallback reason: {unsigned_reason}")
    print(f"Base Gradle args: {build_options_display or '(none)'}")


if __name__ == "__main__":
    main()
