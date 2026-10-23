#!/usr/bin/env bash
# Check a macOS .app holds only machine code for the architecture its target says, everywhere it
# matters: the app's own executable and the Python runtime it bundles (the interpreter the bundled
# CLI runs on). A mismatch fails the build -- an Intel binary in the Apple silicon download would
# run under Rosetta on every M-series Mac.
#
#   tools/check-macos-arch.sh <app-bundle-or-.app.zip> <macos-arm64|macos-x64>
#
# Needs `file` and `tar` (present on GitHub's macOS runners and on Linux).
set -euo pipefail
APP="${1:?usage: check-macos-arch.sh <app or .app.zip> <macos-arm64|macos-x64>}"
TARGET="${2:?target}"
case "$TARGET" in
  macos-arm64) want=arm64; other=x86_64 ;;
  macos-x64)   want=x86_64; other=arm64 ;;
  *) echo "not a macOS target: $TARGET" >&2; exit 2 ;;
esac

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
# Absolute, because the zip is extracted from inside $work: a relative path like the build's
# dist/<name>.app.zip would no longer resolve once there.
[ -e "$APP" ] || { echo "no such file: $APP" >&2; exit 2; }
APP="$(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
if [[ "$APP" == *.zip ]]; then
  (cd "$work" && { ditto -x -k "$APP" . 2>/dev/null || python3 -m zipfile -e "$APP" .; })
  APP="$(find "$work" -maxdepth 1 -name '*.app' | head -1)"
fi
[ -d "$APP" ] || { echo "no .app at $APP" >&2; exit 2; }

fail=0
check() { # <label> <binary>
  local desc; desc="$(file -b "$2")"
  if [[ "$desc" != *"$want"* ]] || [[ "$desc" == *"$other"* ]]; then
    echo "WRONG ARCH: $1 is '$desc', expected $want only" >&2; fail=1
  else
    echo "ok: $1 is $want"
  fi
}

for exe in "$APP"/Contents/MacOS/*; do check "Contents/MacOS/$(basename "$exe")" "$exe"; done

py_archive="$(find "$APP/Contents/Resources" -path '*runtime/python-*.tar.gz' | head -1)"
if [ -n "$py_archive" ]; then
  # The interpreter's real file (python3 itself is a symlink to it), whatever 3.x the pin bundles.
  # Named from the archive's listing rather than a --wildcards pattern, which BSD tar on macOS lacks.
  py_member="$(tar -tzf "$py_archive" | grep -E '^python/bin/python3\.[0-9]+$' | head -1)"
  [ -n "$py_member" ] || { echo "WRONG: no python/bin/python3.N in $py_archive" >&2; exit 1; }
  tar -xzf "$py_archive" -C "$work" "$py_member"
  py="$(find "$work/python/bin" -name 'python3*' -type f | head -1)"
  check "bundled Python ($(basename "$py_archive"))" "$py"
else
  echo "WRONG: no bundled Python runtime in $APP/Contents/Resources" >&2; fail=1
fi
exit $fail
