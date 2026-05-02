#!/usr/bin/env bash
set -euo pipefail

PRE_BUILD_COMMAND="${PRE_BUILD_COMMAND:-}"
PRE_BUILD_CACHE_PATH="${PRE_BUILD_CACHE_PATH:-}"
PRE_BUILD_MODE="${PRE_BUILD_MODE:-none}"

if [ -z "$PRE_BUILD_COMMAND" ]; then
  echo "::error::PRE_BUILD_COMMAND is required when pre-build is marked as needed."
  exit 1
fi

if [ -n "$PRE_BUILD_CACHE_PATH" ] && [ -e "$PRE_BUILD_CACHE_PATH" ]; then
  echo "Pre-build output already exists, skipping command: $PRE_BUILD_CACHE_PATH"
  exit 0
fi

if [ "$PRE_BUILD_MODE" = "auto-nekobox-libcore" ]; then
  chmod +x ./run libcore/*.sh buildScript/*.sh 2>/dev/null || true
fi

echo "Running pre-build command: $PRE_BUILD_COMMAND"
bash -eo pipefail -c "$PRE_BUILD_COMMAND"

if [ -n "$PRE_BUILD_CACHE_PATH" ] && [ ! -e "$PRE_BUILD_CACHE_PATH" ]; then
  echo "::error::Pre-build command completed, but expected output was not found: $PRE_BUILD_CACHE_PATH"
  exit 1
fi
