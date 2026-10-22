#!/usr/bin/env bash
# Stage the bundled runtime the app ships with, into src-tauri/resources/runtime/:
#
#   python-<tag>-<target>.tar.gz   python-build-standalone, pinned + sha256-verified (runtime/python_version.json)
#   upstream-<sha>.tar.gz          `git archive` of the pinned upstream/aitpotluck-local-client submodule commit
#   gui_probe.py                   our read-only state probe (sidecar/gui_probe.py)
#   gui_plan.py                    our read-only install plan (sidecar/gui_plan.py)
#   gui_server.py                  which AI Potluck server pairing uses, per upstream (sidecar/gui_server.py)
#   manifest.json                  what the app checks before unpacking
#
#   tools/stage-runtime.sh [--target linux-x64|linux-arm64|macos-arm64|macos-x64|windows-x64]
#
# Run before `cargo tauri dev` / `cargo tauri build` (tools/build.sh does it for you). Downloads are
# cached in build/cache/. Exit codes: 0 staged, 1 verification failure, 2 usage/environment error.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/upstream/aitpotluck-local-client"
OUT="$ROOT/src-tauri/resources/runtime"
CACHE="$ROOT/build/cache"
PIN="$ROOT/runtime/python_version.json"

host_target() {
  local os arch
  case "$(uname -s)" in
    Linux) os=linux ;; Darwin) os=macos ;; MINGW*|MSYS*|CYGWIN*) os=windows ;;
    *) echo "unsupported OS: $(uname -s)" >&2; exit 2 ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64) arch=x64 ;; aarch64|arm64) arch=arm64 ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 2 ;;
  esac
  echo "$os-$arch"
}

TARGET="$(host_target)"
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:?--target needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
# Windows runners (Git Bash) ship `python`, not `python3`; a Windows Store stub may answer to
# `python3` without being a real interpreter, so check that it actually runs.
PY3=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    PY3="$cand"; break
  fi
done
[ -n "$PY3" ] || { echo "need a Python 3.8+ interpreter on PATH (python3 or python) to read the pins" >&2; exit 2; }
json_get() { "$PY3" -c 'import json,sys; d=json.load(open(sys.argv[1])); 
for k in sys.argv[2].split("."): d=d[k]
print(d)' "$1" "$2" | tr -d '\r'; }

[ -f "$UPSTREAM/aipotluck/installer/install.py" ] || {
  echo "upstream submodule missing -- run: git submodule update --init upstream/aitpotluck-local-client" >&2; exit 2; }

mkdir -p "$CACHE" "$OUT"
rm -f "$OUT"/*.tar.gz "$OUT"/manifest.json "$OUT"/gui_*.py

# ---------------------------------------------------------------- python-build-standalone
PY_TAG="$(json_get "$PIN" tag)"
PY_FILE="$(json_get "$PIN" "assets.$TARGET.file")"
PY_SHA="$(json_get "$PIN" "assets.$TARGET.sha256")"
PY_URL="$(json_get "$PIN" release_base_url)/$PY_TAG/${PY_FILE//+/%2B}"
if [ ! -f "$CACHE/$PY_FILE" ] || [ "$(sha256 "$CACHE/$PY_FILE")" != "$PY_SHA" ]; then
  echo "downloading $PY_FILE"
  curl -fL --retry 3 -o "$CACHE/$PY_FILE.part" "$PY_URL"
  mv "$CACHE/$PY_FILE.part" "$CACHE/$PY_FILE"
fi
GOT="$(sha256 "$CACHE/$PY_FILE")"
[ "$GOT" = "$PY_SHA" ] || { echo "python archive checksum mismatch: $GOT != $PY_SHA" >&2; exit 1; }
PY_OUT="python-$PY_TAG-$TARGET.tar.gz"
cp "$CACHE/$PY_FILE" "$OUT/$PY_OUT"

# ---------------------------------------------------------------- upstream source, at the pinned commit
UP_SHA="$(git -C "$UPSTREAM" rev-parse HEAD)"
if [ -n "$(git -C "$UPSTREAM" status --porcelain --untracked-files=no)" ]; then
  echo "WARNING: upstream submodule has local modifications; bundling the committed tree at $UP_SHA only" >&2
fi
UP_OUT="upstream-${UP_SHA:0:12}.tar.gz"
# `git archive` = exactly the tracked files at that commit (vendor/llama.cpp submodule excluded --
# see docs/ARCHITECTURE.md "Source builds").
git -C "$UPSTREAM" archive --format=tar "$UP_SHA" | gzip -n -9 > "$OUT/$UP_OUT"

cp "$ROOT/sidecar/gui_probe.py" "$OUT/gui_probe.py"
cp "$ROOT/sidecar/gui_plan.py" "$OUT/gui_plan.py"
cp "$ROOT/sidecar/gui_server.py" "$OUT/gui_server.py"

cat > "$OUT/manifest.json" <<EOF
{
  "target": "$TARGET",
  "python_tag": "$PY_TAG-$TARGET",
  "python_archive": "$PY_OUT",
  "python_sha256": "$PY_SHA",
  "upstream_sha": "$UP_SHA",
  "upstream_archive": "$UP_OUT",
  "upstream_sha256": "$(sha256 "$OUT/$UP_OUT")"
}
EOF
echo "staged runtime for $TARGET: python $PY_TAG, upstream ${UP_SHA:0:12} -> $OUT"
