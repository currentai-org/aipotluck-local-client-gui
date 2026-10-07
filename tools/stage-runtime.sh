#!/usr/bin/env bash
# Stage the bundled runtime the app ships with, into src-tauri/resources/runtime/:
#
#   python-<tag>-<target>.tar.gz   python-build-standalone, pinned + sha256-verified (runtime/python_version.json)
#   upstream-<sha>.tar.gz          `git archive` of the pinned upstream/aitpotluck-local-client submodule commit
#   gui_probe.py                   our read-only state probe (sidecar/gui_probe.py)
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
json_get() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); 
for k in sys.argv[2].split("."): d=d[k]
print(d)' "$1" "$2"; }

[ -f "$UPSTREAM/aipotluck/installer/install.py" ] || {
  echo "upstream submodule missing -- run: git submodule update --init upstream/aitpotluck-local-client" >&2; exit 2; }

mkdir -p "$CACHE" "$OUT"
rm -f "$OUT"/*.tar.gz "$OUT"/manifest.json "$OUT"/gui_probe.py

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
