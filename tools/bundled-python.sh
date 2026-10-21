#!/usr/bin/env bash
# Print the path of a ready-to-use copy of the Python interpreter the GUI bundles (unpacked from
# the archive tools/stage-runtime.sh staged), so tests run upstream on the exact interpreter users
# get -- not whatever python3 the dev machine happens to have.
#
#   tools/bundled-python.sh                 -> /path/to/python3 (python.exe on Windows)
#   tools/bundled-python.sh --with-pytest   also make pytest importable (dev/test only; never shipped)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/src-tauri/resources/runtime/manifest.json"
[ -f "$MANIFEST" ] || "$ROOT/tools/stage-runtime.sh" >&2
# Any host Python just to read the manifest; Windows (Git Bash) has `python`, not `python3`.
HOSTPY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c '' 2>/dev/null; then HOSTPY="$cand"; break; fi
done
[ -n "$HOSTPY" ] || { echo "need a Python on PATH (python3 or python) to read the runtime manifest" >&2; exit 2; }
read -r ARCHIVE SHA < <("$HOSTPY" -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["python_archive"], m["python_sha256"])' "$MANIFEST" | tr -d '\r')
DEST="$ROOT/build/test-python/${SHA:0:16}"
# python-build-standalone's layout: bin/python3 on Linux/macOS, python.exe at the root on Windows.
exe() { if [ -x "$DEST/python/bin/python3" ]; then echo "$DEST/python/bin/python3"; elif [ -f "$DEST/python/python.exe" ]; then echo "$DEST/python/python.exe"; fi; }
if [ -z "$(exe)" ]; then
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar -xzf "$ROOT/src-tauri/resources/runtime/$ARCHIVE" -C "$DEST"
fi
PY="$(exe)"
[ -n "$PY" ] || { echo "no interpreter in $ARCHIVE" >&2; exit 1; }
if [ "${1:-}" = "--with-pytest" ] && ! "$PY" -c 'import pytest' 2>/dev/null; then
  "$PY" -m pip install --quiet --disable-pip-version-check pytest >&2
fi
echo "$PY"
