#!/usr/bin/env bash
set -euo pipefail

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/usr/local/lib/android/sdk}}"
REQUESTED_NDK_VERSION="${REQUESTED_NDK_VERSION:-}"
TOOLCHAIN_REL="toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip"

resolve_ndk_revision() {
  case "$1" in
    r29|29.0.14033849) echo "29.0.14033849" ;;
    r28c|28.2.13676358) echo "28.2.13676358" ;;
    r27d|27.3.13750724) echo "27.3.13750724" ;;
    r26d|26.3.11579264) echo "26.3.11579264" ;;
    r25c|25.2.9519653) echo "25.2.9519653" ;;
    r24|24.0.8215888) echo "24.0.8215888" ;;
    r23c|23.2.8568313) echo "23.2.8568313" ;;
    r22b|22.1.7171670) echo "22.1.7171670" ;;
    r21e|21.4.7075529) echo "21.4.7075529" ;;
    r20b|20.1.5948944) echo "20.1.5948944" ;;
    [0-9]*.[0-9]*.[0-9]*) echo "$1" ;;
    *)
      echo "::error::Unable to map NDK version '$1' to a full SDK revision."
      exit 1
      ;;
  esac
}

read_ndk_revision() {
  local dir="$1"
  if [ -f "$dir/source.properties" ]; then
    awk -F'= *' '/^Pkg.Revision/ {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$dir/source.properties"
  fi
}

has_llvm_strip() {
  local dir="${1:-}"
  [ -n "$dir" ] && [ -x "$dir/$TOOLCHAIN_REL" ]
}

is_requested_revision() {
  local dir="${1:-}"
  local revision=""
  [ -n "$dir" ] || return 1
  [ -d "$dir" ] || return 1
  revision="$(read_ndk_revision "$dir" || true)"
  [ "$revision" = "$REQUESTED_NDK_REVISION" ]
}

find_complete_requested_ndk() {
  local candidate
  for candidate in \
    "$CANONICAL_NDK_DIR" \
    "$HOME/.setup-ndk/$REQUESTED_NDK_VERSION" \
    "$HOME/.setup-ndk/$REQUESTED_NDK_REVISION" \
    "${ANDROID_NDK_HOME:-}" \
    "${ANDROID_NDK_ROOT:-}" \
    "$SDK_ROOT/ndk"/*; do
    [ -n "$candidate" ] || continue
    [ -d "$candidate" ] || continue
    is_requested_revision "$candidate" || continue
    has_llvm_strip "$candidate" || continue
    echo "$candidate"
    return 0
  done
  return 1
}

install_requested_ndk() {
  local sdkmanager
  sdkmanager="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
  if [ ! -x "$sdkmanager" ]; then
    sdkmanager="$(command -v sdkmanager || true)"
  fi
  if [ -z "$sdkmanager" ]; then
    echo "::error::sdkmanager was not found; cannot install ndk;$REQUESTED_NDK_REVISION."
    exit 1
  fi

  echo "Installing ndk;$REQUESTED_NDK_REVISION with sdkmanager."
  rm -rf "$CANONICAL_NDK_DIR"

  set +o pipefail
  yes | "$sdkmanager" --licenses >/dev/null
  license_status=${PIPESTATUS[1]}
  yes | "$sdkmanager" --install "ndk;$REQUESTED_NDK_REVISION"
  install_status=${PIPESTATUS[1]}
  set -o pipefail

  if [ "$license_status" -ne 0 ]; then
    echo "::warning::sdkmanager --licenses exited with status $license_status; continuing because licenses may already be accepted."
  fi
  if [ "$install_status" -ne 0 ]; then
    echo "::error::sdkmanager failed to install ndk;$REQUESTED_NDK_REVISION with status $install_status."
    exit "$install_status"
  fi
}

if [ -z "$REQUESTED_NDK_VERSION" ]; then
  echo "::error::REQUESTED_NDK_VERSION is required."
  exit 1
fi

REQUESTED_NDK_REVISION="$(resolve_ndk_revision "$REQUESTED_NDK_VERSION")"
CANONICAL_NDK_DIR="$SDK_ROOT/ndk/$REQUESTED_NDK_REVISION"
mkdir -p "$SDK_ROOT/ndk"

COMPLETE_NDK_DIR="$(find_complete_requested_ndk || true)"

if [ -n "$COMPLETE_NDK_DIR" ] && [ "$COMPLETE_NDK_DIR" != "$CANONICAL_NDK_DIR" ]; then
  echo "Found complete requested NDK at $COMPLETE_NDK_DIR; linking it to $CANONICAL_NDK_DIR for Gradle ndkVersion resolution."
  rm -rf "$CANONICAL_NDK_DIR"
  ln -s "$COMPLETE_NDK_DIR" "$CANONICAL_NDK_DIR"
fi

if ! has_llvm_strip "$CANONICAL_NDK_DIR" || ! is_requested_revision "$CANONICAL_NDK_DIR"; then
  echo "::warning::Canonical NDK is missing or incomplete: $CANONICAL_NDK_DIR"
  install_requested_ndk
fi

if ! has_llvm_strip "$CANONICAL_NDK_DIR" || ! is_requested_revision "$CANONICAL_NDK_DIR"; then
  echo "::error::NDK installation is incomplete after repair: missing $CANONICAL_NDK_DIR/$TOOLCHAIN_REL or source.properties revision is not $REQUESTED_NDK_REVISION."
  echo "Detected SDK NDK directories:"
  find "$SDK_ROOT/ndk" -maxdepth 2 -name source.properties -print -exec awk -F'= *' '/^Pkg.Revision/ {print "  " FILENAME ": " $2}' {} \; 2>/dev/null || true
  exit 1
fi

{
  echo "ANDROID_NDK_HOME=$CANONICAL_NDK_DIR"
  echo "ANDROID_NDK_ROOT=$CANONICAL_NDK_DIR"
} >> "$GITHUB_ENV"
{
  echo "$CANONICAL_NDK_DIR"
  echo "$CANONICAL_NDK_DIR/toolchains/llvm/prebuilt/linux-x86_64/bin"
} >> "$GITHUB_PATH"

echo "NDK verified: $REQUESTED_NDK_VERSION -> $REQUESTED_NDK_REVISION ($CANONICAL_NDK_DIR)"
