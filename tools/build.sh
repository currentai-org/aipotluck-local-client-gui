#!/usr/bin/env bash
# Build the app locally.
#
#   tools/build.sh           release bundle (.deb + .AppImage on Linux) -> src-tauri/target/release/bundle/
#   tools/build.sh --dev     run the app in dev mode (hot-reloading UI)
#   tools/build.sh --debug   debug bundle, faster to compile
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.cargo/bin:$HOME/.npm-global/bin:$PATH"

git submodule update --init upstream/aitpotluck-local-client
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
