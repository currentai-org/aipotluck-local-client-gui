#!/usr/bin/env bash
# The merge gate. Exits 0 only if every check passes.
#
#   tools/check.sh            all checks
#   tools/check.sh --no-rust  skip the (slow) Rust build/tests
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.cargo/bin:$HOME/.npm-global/bin:$PATH"
RUST=1; [ "${1:-}" = "--no-rust" ] && RUST=0
FAILED=()
step() { echo; echo "== $1"; }
run() { local name="$1"; shift; step "$name"; "$@" || FAILED+=("$name"); }

# Always restage for THIS host: a `tools/build.sh --release-target <other arch>` leaves that
# target's interpreter staged (e.g. macos-x64 on Apple silicon: "Bad CPU type in executable").
# Cached by checksum, so this is a few seconds.
run "stage runtime (host)" tools/stage-runtime.sh

PY="$(tools/bundled-python.sh --with-pytest)" || { echo "bundled python unavailable"; exit 2; }
run "conformance: extract upstream surface" python3 tools/conformance/extract_surface.py \
  upstream/aitpotluck-local-client --out build/conformance/pinned-surface.json
run "conformance: no drift, every item classified" python3 tools/conformance/check_coverage.py \
  --surface build/conformance/pinned-surface.json --quiet
run "contract tests (bundled $("$PY" -V 2>&1) vs pinned upstream)" "$PY" -m pytest -q -p no:cacheprovider tests
run "ui unit tests" pnpm --dir ui test
run "ui type check" pnpm --dir ui check
if [ "$RUST" -eq 1 ]; then
  run "rust tests" bash -c 'cd src-tauri && cargo test -q -j 3'
fi

echo
if [ ${#FAILED[@]} -eq 0 ]; then echo "check.sh: ALL PASSED"; exit 0; fi
printf 'check.sh: FAILED -> %s\n' "${FAILED[@]}"; exit 1
