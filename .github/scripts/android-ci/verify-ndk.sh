#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve_default_sdk_root() {
  case "$(uname -s)" in
    Darwin) echo "$HOME/Library/Android/sdk" ;;
    Linux) echo "/usr/local/lib/android/sdk" ;;
    *) echo "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}" ;;
  esac
}

resolve_ndk_host_tag() {
  case "$(uname -s)" in
    Darwin) echo "darwin-x86_64" ;;
    Linux) echo "linux-x86_64" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows-x86_64" ;;
    *)
      echo "::error::Unsupported NDK host OS: $(uname -s)"
      exit 1
      ;;
  esac
}

resolve_ndk_platform() {
  case "$(uname -s)" in
    Darwin) echo "darwin" ;;
    Linux) echo "linux" ;;
    *)
      echo "::error::Unsupported NDK preview archive host OS: $(uname -s)"
      exit 1
      ;;
  esac
}

DEFAULT_SDK_ROOT="$(resolve_default_sdk_root)"
SDK_ROOT="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$DEFAULT_SDK_ROOT}}"
echo "Android SDK paths: ANDROID_HOME=${ANDROID_HOME:-<unset>} ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT:-<unset>} SDK_ROOT=$SDK_ROOT"
echo "Resolved SDK root: $(readlink -f "$SDK_ROOT" 2>/dev/null || echo "$SDK_ROOT")"

REQUESTED_NDK_VERSION="${REQUESTED_NDK_VERSION:-}"
NDK_HOST_TAG="$(resolve_ndk_host_tag)"
NDK_PLATFORM="$(resolve_ndk_platform)"
TOOLCHAIN_REL="toolchains/llvm/prebuilt/${NDK_HOST_TAG}/bin/llvm-strip"

resolve_ndk_revision() {
  python3 "$SCRIPT_DIR/ndk_versions.py" --resolve "$1"
}

resolve_ndk_pkg_revision() {
  python3 "$SCRIPT_DIR/ndk_versions.py" --pkg-revision "$1"
}

read_ndk_revision() {
  local dir="$1"
  if [ -f "$dir/source.properties" ]; then
    awk -F'= *' '
      /^Pkg.BaseRevision/ {gsub(/[[:space:]]/, "", $2); base=$2}
      /^Pkg.Revision/ {gsub(/[[:space:]]/, "", $2); revision=$2}
      END {if (base != "") print base; else if (revision != "") print revision}
    ' "$dir/source.properties"
  fi
}

read_ndk_pkg_revision() {
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
  local pkg_revision=""
  [ -n "$dir" ] || return 1
  [ -d "$dir" ] || return 1
  revision="$(read_ndk_revision "$dir" || true)"
  pkg_revision="$(read_ndk_pkg_revision "$dir" || true)"
  [ "$revision" = "$REQUESTED_NDK_REVISION" ] &&
    [ "$pkg_revision" = "$REQUESTED_NDK_PKG_REVISION" ]
}

candidate_ndk_dirs_from_root() {
  local root="${1:-}"
  [ -n "$root" ] || return 0
  [ -d "$root" ] || return 0

  if [ -f "$root/source.properties" ]; then
    echo "$root"
  fi

  find "$root" -mindepth 1 -maxdepth 5 -type f -name source.properties -print 2>/dev/null \
    | while IFS= read -r source_properties; do
        dirname "$source_properties"
      done
}

find_complete_requested_ndk() {
  local root candidate seen_file
  seen_file="$(mktemp)"

  for root in \
    "$CANONICAL_NDK_DIR" \
    "${ANDROID_NDK_HOME:-}" \
    "${ANDROID_NDK_ROOT:-}" \
    "$SDK_ROOT/ndk"; do
    [ -n "$root" ] || continue
    while IFS= read -r candidate; do
      [ -n "$candidate" ] || continue
      [ -d "$candidate" ] || continue
      if grep -Fxq "$candidate" "$seen_file" 2>/dev/null; then
        continue
      fi
      echo "$candidate" >> "$seen_file"
      is_requested_revision "$candidate" || continue
      has_llvm_strip "$candidate" || continue
      rm -f "$seen_file"
      echo "$candidate"
      return 0
    done < <(candidate_ndk_dirs_from_root "$root")
  done

  rm -f "$seen_file"
  return 1
}

verify_sha1() {
  local expected="$1"
  local file="$2"
  if command -v sha1sum >/dev/null 2>&1; then
    printf '%s  %s\n' "$expected" "$file" | sha1sum --check --status
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s  %s\n' "$expected" "$file" | shasum -a 1 --check --status
  else
    echo "::error::Neither sha1sum nor shasum is available to verify the NDK archive."
    return 1
  fi
}

install_preview_ndk() {
  local metadata="$1"
  local url expected_sha1 archive_format
  local work_dir archive extract_dir source_properties source_dir staging_dir
  local mount_dir mounted=false

  IFS='|' read -r url expected_sha1 archive_format _ <<< "$metadata"
  if [ -z "$url" ] || [ -z "$expected_sha1" ] || [ -z "$archive_format" ]; then
    echo "::error::Incomplete official preview archive metadata for NDK $REQUESTED_NDK_VERSION."
    return 1
  fi

  work_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/ndk-preview.XXXXXX")"
  archive="$work_dir/ndk-preview.$archive_format"
  extract_dir="$work_dir/extracted"
  staging_dir="$SDK_ROOT/ndk/.install-${REQUESTED_NDK_REVISION}-$$"
  mkdir -p "$extract_dir"

  echo "Installing official NDK preview archive for base revision $REQUESTED_NDK_REVISION."
  echo "Download: $url"
  echo "Expected SHA-1: $expected_sha1"

  curl --fail --location --retry 3 --retry-delay 2 \
    --connect-timeout 30 "$url" --output "$archive"

  if ! verify_sha1 "$expected_sha1" "$archive"; then
    echo "::error::SHA-1 verification failed for the official NDK archive."
    rm -rf "$work_dir"
    return 1
  fi
  echo "Official NDK archive SHA-1 verified."

  case "$archive_format" in
    zip)
      command -v unzip >/dev/null 2>&1 || {
        echo "::error::unzip is required to extract the NDK archive."
        rm -rf "$work_dir"
        return 1
      }
      unzip -q "$archive" -d "$extract_dir"
      ;;
    dmg)
      command -v hdiutil >/dev/null 2>&1 || {
        echo "::error::hdiutil is required to mount the NDK DMG archive."
        rm -rf "$work_dir"
        return 1
      }
      mount_dir="$work_dir/mounted"
      mkdir -p "$mount_dir"
      hdiutil attach -readonly -nobrowse -mountpoint "$mount_dir" "$archive" >/dev/null
      mounted=true
      extract_dir="$mount_dir"
      ;;
    *)
      echo "::error::Unsupported NDK preview archive format: $archive_format"
      rm -rf "$work_dir"
      return 1
      ;;
  esac

  source_properties="$(find "$extract_dir" -type f -name source.properties -print -quit 2>/dev/null || true)"
  if [ -z "$source_properties" ]; then
    echo "::error::The downloaded NDK archive does not contain source.properties."
    if [ "$mounted" = true ]; then hdiutil detach "$mount_dir" >/dev/null || true; fi
    rm -rf "$work_dir"
    return 1
  fi

  source_dir="$(dirname "$source_properties")"
  rm -rf "$staging_dir"
  mkdir -p "$staging_dir"
  cp -a "$source_dir/." "$staging_dir/"

  if ! is_requested_revision "$staging_dir"; then
    echo "::error::Downloaded NDK metadata mismatch: expected base=$REQUESTED_NDK_REVISION and Pkg.Revision=$REQUESTED_NDK_PKG_REVISION."
    rm -rf "$staging_dir"
    if [ "$mounted" = true ]; then hdiutil detach "$mount_dir" >/dev/null || true; fi
    rm -rf "$work_dir"
    return 1
  fi
  if ! has_llvm_strip "$staging_dir"; then
    echo "::error::Downloaded NDK is missing the required host toolchain binary: $TOOLCHAIN_REL."
    rm -rf "$staging_dir"
    if [ "$mounted" = true ]; then hdiutil detach "$mount_dir" >/dev/null || true; fi
    rm -rf "$work_dir"
    return 1
  fi

  rm -rf "$CANONICAL_NDK_DIR"
  mv "$staging_dir" "$CANONICAL_NDK_DIR"

  if [ "$mounted" = true ]; then hdiutil detach "$mount_dir" >/dev/null; fi
  rm -rf "$work_dir"
  echo "Installed official NDK preview archive into $CANONICAL_NDK_DIR."
}

install_sdkmanager_ndk() {
  local sdkmanager
  sdkmanager="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
  if [ ! -x "$sdkmanager" ]; then
    sdkmanager="$(command -v sdkmanager || true)"
  fi
  if [ -z "$sdkmanager" ]; then
    echo "::error::sdkmanager was not found; cannot install ndk;$REQUESTED_NDK_REVISION."
    exit 1
  fi

  echo "Installing stable SDK Manager package ndk;$REQUESTED_NDK_REVISION."
  echo "sdkmanager: $sdkmanager"
  rm -rf "$CANONICAL_NDK_DIR"

  set +e
  set +o pipefail
  yes 2>/dev/null | "$sdkmanager" --sdk_root="$SDK_ROOT" --licenses >/dev/null
  license_pipeline_status=( "${PIPESTATUS[@]}" )
  license_status="${license_pipeline_status[1]:-1}"

  yes 2>/dev/null | "$sdkmanager" --sdk_root="$SDK_ROOT" --install "ndk;$REQUESTED_NDK_REVISION"
  install_pipeline_status=( "${PIPESTATUS[@]}" )
  install_status="${install_pipeline_status[1]:-1}"
  set -o pipefail
  set -e

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
REQUESTED_NDK_PKG_REVISION="$(resolve_ndk_pkg_revision "$REQUESTED_NDK_VERSION")"
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
  if PREVIEW_METADATA="$(python3 "$SCRIPT_DIR/ndk_versions.py" \
    --preview-download "$REQUESTED_NDK_VERSION" --platform "$NDK_PLATFORM" 2>/dev/null)"; then
    install_preview_ndk "$PREVIEW_METADATA"
  else
    install_sdkmanager_ndk
  fi
fi

if ! has_llvm_strip "$CANONICAL_NDK_DIR" || ! is_requested_revision "$CANONICAL_NDK_DIR"; then
  echo "::error::NDK installation is incomplete: expected base revision $REQUESTED_NDK_REVISION, Pkg.Revision $REQUESTED_NDK_PKG_REVISION, and $TOOLCHAIN_REL."
  echo "Detected SDK NDK directories:"
  find "$SDK_ROOT/ndk" -maxdepth 2 -name source.properties -print -exec awk -F'= *' '/^Pkg.(Base)?Revision/ {print "  " FILENAME ": " $0}' {} \\; 2>/dev/null || true
  exit 1
fi

{
  echo "ANDROID_NDK_HOME=$CANONICAL_NDK_DIR"
  echo "ANDROID_NDK_ROOT=$CANONICAL_NDK_DIR"
} >> "$GITHUB_ENV"
{
  echo "$CANONICAL_NDK_DIR"
  echo "$CANONICAL_NDK_DIR/toolchains/llvm/prebuilt/$NDK_HOST_TAG/bin"
} >> "$GITHUB_PATH"

echo "NDK verified: $REQUESTED_NDK_VERSION -> base=$REQUESTED_NDK_REVISION Pkg.Revision=$REQUESTED_NDK_PKG_REVISION ($CANONICAL_NDK_DIR, host=$NDK_HOST_TAG)"
