#!/usr/bin/env bash
set -euo pipefail

CI_HELPERS_DIR="${CI_HELPERS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
GRADLE_TASK="${GRADLE_TASK:-}"
BUILD_OPTIONS_JSON="${BUILD_OPTIONS_JSON:-[]}"

if [ -z "$GRADLE_TASK" ]; then
  echo "::error::GRADLE_TASK is required."
  exit 1
fi

chmod +x ./gradlew
EXTRA_GRADLE_ARGS=()
while IFS= read -r arg; do
  EXTRA_GRADLE_ARGS+=("$arg")
done < <(BUILD_OPTIONS_JSON="$BUILD_OPTIONS_JSON" python3 "$CI_HELPERS_DIR/parse-gradle-options.py" --from-json --format lines)

echo "Running Gradle task: $GRADLE_TASK"
if [ "${#EXTRA_GRADLE_ARGS[@]}" -gt 0 ]; then
  printf 'Extra Gradle args:'
  printf ' %q' "${EXTRA_GRADLE_ARGS[@]}"
  printf '\n'
fi

./gradlew "$GRADLE_TASK" --no-daemon --stacktrace "${EXTRA_GRADLE_ARGS[@]}"
