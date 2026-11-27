#!/usr/bin/env bash
set -euo pipefail

mode="${CHECKOUT_SUBMODULES:-recursive}"
if [ ! -f .gitmodules ]; then
  echo "No .gitmodules file; skipping submodule verification."
  exit 0
fi

case "$mode" in
  false|none|off)
    echo "Submodule checkout is disabled by input; skipping initialization."
    exit 0
    ;;
  true|recursive)
    ;;
  *)
    echo "::error::Unsupported submodule mode: $mode. Expected false, true, or recursive." >&2
    exit 1
    ;;
esac

sync_args=()
update_args=()
status_args=()
if [ "$mode" = "recursive" ]; then
  sync_args+=(--recursive)
  update_args+=(--recursive)
  status_args+=(--recursive)
fi

echo "Synchronizing submodule URLs (mode: $mode)."
git submodule sync "${sync_args[@]}"

echo "Initializing submodules (mode: $mode)."
if ! git submodule update --init "${update_args[@]}"; then
  echo "::error::Failed to initialize Git submodules. Check .gitmodules URLs and ensure CHECKOUT_TOKEN can read every private submodule." >&2
  exit 1
fi

status="$(git submodule status "${status_args[@]}")"
if [ -n "$status" ]; then
  printf '%s\n' "$status"
fi
if printf '%s\n' "$status" | grep -Eq '^[+-U]'; then
  echo "::error::One or more submodules are uninitialized, checked out at the wrong commit, or conflicted." >&2
  exit 1
fi
