#!/usr/bin/env bash
set -euo pipefail

PREFER_WRAPPER="${CI_PREFER_WRAPPER:-true}"
if [ "$PREFER_WRAPPER" = "true" ] && [ -f ./gradlew ]; then
  chmod +x ./gradlew
  printf '%s\n' "./gradlew"
  exit 0
fi

if command -v gradle >/dev/null 2>&1; then
  command -v gradle
  exit 0
fi

echo "::error::Gradle Wrapper './gradlew' is missing and no 'gradle' executable is available. Check the Gradle setup step and gradle_version input." >&2
exit 1
