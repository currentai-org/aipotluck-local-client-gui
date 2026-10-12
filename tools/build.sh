#!/usr/bin/env bash
# Build the app locally.
#
#   tools/build.sh                          release bundle for this host -> src-tauri/target/release/bundle/
#   tools/build.sh --dev                    run the app in dev mode (hot-reloading UI)
#   tools/build.sh --debug                  debug bundle, faster to compile
#   tools/build.sh --release-target <t>     EXACTLY what CI's build job does for target <t>
#                                           (linux-x64, linux-arm64, windows-x64, macos-arm64,
#                                           macos-x64): stage that target's runtime, `tauri build
#                                           --target --bundles` from .github/build-targets.json,
#                                           collect installers into dist/<t>/ with SHA256SUMS.
#                                           Use it to prove a target on your own machine before
#                                           enabling it in CI. Works without the target being
#                                           enabled. On Windows, run it from Git Bash.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.cargo/bin:$HOME/.npm-global/bin:$PATH"

git submodule update --init upstream/aitpotluck-local-client

if [ "${1:-}" = "--release-target" ]; then
  T="${2:?--release-target needs a target, e.g. windows-x64}"
  PY=""
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then PY="$cand"; break; fi
  done
  [ -n "$PY" ] || { echo "need Python 3.8+ on PATH (python3 or python)" >&2; exit 2; }
  INFO="$("$PY" tools/release_version.py --target-info "$T" | tr -d '\r')"
  field() { "$PY" -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$INFO" "$1" | tr -d '\r'; }
  TRIPLE="$(field rust_target)"; BUNDLES="$(field bundles)"
  echo "building $T ($TRIPLE; bundles: $BUNDLES)"
  rustup target add "$TRIPLE" >/dev/null
  tools/stage-runtime.sh --target "$T"
  [ -d ui/node_modules ] || pnpm --dir ui install --frozen-lockfile
  (cd src-tauri && cargo tauri build --ci --target "$TRIPLE" --bundles "$BUNDLES")
  tools/collect-bundles.sh "$T" --rust-target "$TRIPLE" --out "dist/$T"
  exit 0
fi

tools/stage-runtime.sh
[ -d ui/node_modules ] || pnpm --dir ui install --frozen-lockfile

cd src-tauri
case "${1:-}" in
  --dev) exec cargo tauri dev ;;
  --debug) cargo tauri build --debug ;;
  "") cargo tauri build ;;
  *) echo "unknown argument: $1" >&2; exit 2 ;;
esac
find target -path '*/bundle/*' \( -name '*.deb' -o -name '*.AppImage' \) -newer ../tools/build.sh -print
