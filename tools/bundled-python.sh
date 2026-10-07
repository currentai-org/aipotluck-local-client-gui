#!/usr/bin/env bash
# Print the path of a ready-to-use copy of the Python interpreter the GUI bundles (unpacked from
# the archive tools/stage-runtime.sh staged), so tests run upstream on the exact interpreter users
# get -- not whatever python3 the dev machine happens to have.
#
#   tools/bundled-python.sh                 -> /path/to/python3
#   tools/bundled-python.sh --with-pytest   also make pytest importable (dev/test only; never shipped)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/src-tauri/resources/runtime/manifest.json"
[ -f "$MANIFEST" ] || "$ROOT/tools/stage-runtime.sh" >&2
read -r ARCHIVE SHA < <(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["python_archive"], m["python_sha256"])' "$MANIFEST")
DEST="$ROOT/build/test-python/${SHA:0:16}"
if [ ! -x "$DEST/python/bin/python3" ]; then
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar -xzf "$ROOT/src-tauri/resources/runtime/$ARCHIVE" -C "$DEST"
fi
PY="$DEST/python/bin/python3"
if [ "${1:-}" = "--with-pytest" ] && ! "$PY" -c 'import pytest' 2>/dev/null; then
  "$PY" -m pip install --quiet --disable-pip-version-check pytest >&2
fi
echo "$PY"
