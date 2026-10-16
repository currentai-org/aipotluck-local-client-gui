#!/usr/bin/env bash
# Gather the installers `cargo tauri build` produced into one flat directory, with the build target
# in every file name, plus a SHA256SUMS file. Same script locally and in CI, so a release's assets
# are named the same way no matter where they were built.
#
#   tools/collect-bundles.sh <target> [--rust-target TRIPLE] [--out DIR] [--label LABEL]
#
#   <target>        linux-x64 | linux-arm64 | windows-x64 | macos-arm64 | macos-x64
#   --rust-target   the triple passed to `tauri build --target` (bundles then live under
#                   src-tauri/target/<triple>/release/bundle); omit for a host build
#   --out           default dist/<target>
#   --label         what goes in the file name instead of the app version, e.g.
#                   0.1.0-nightly.20261010.2cbd67a, so a nightly download names itself
#
# Exit 1 if no installer was found -- a green build step that bundled nothing must not look like
# a release.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?usage: collect-bundles.sh <target> [--rust-target TRIPLE] [--out DIR] [--label LABEL]}"; shift
RUST_TARGET="" OUT="" LABEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --rust-target) RUST_TARGET="${2:?}"; shift 2 ;;
    --out) OUT="${2:?}"; shift 2 ;;
    --label) LABEL="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$LABEL" in *[!0-9A-Za-z.+-]*) echo "--label may only contain [0-9A-Za-z.+-]: $LABEL" >&2; exit 2 ;; esac
OUT="${OUT:-$ROOT/dist/$TARGET}"
if [ -n "$RUST_TARGET" ]; then
  BUNDLE="$ROOT/src-tauri/target/$RUST_TARGET/release/bundle"
else
  BUNDLE="$ROOT/src-tauri/target/release/bundle"
fi
[ -d "$BUNDLE" ] || { echo "no bundle directory at $BUNDLE" >&2; exit 1; }

VERSION="${LABEL:-$(cd "$ROOT" && (python3 tools/release_version.py 2>/dev/null || python tools/release_version.py) | tr -d '\r')}"
NAME="aipotluck-local-client-gui"
mkdir -p "$OUT"
rm -f "$OUT"/*

n=0
copy() { # <src> <ext>
  local dest="$OUT/${NAME}_${VERSION}_${TARGET}.$2"
  # Two bundles mapping to one release name means a stale bundle from an earlier build (e.g. a
  # renamed product) is still on disk. Refuse rather than let the last one silently win.
  if [ -e "$dest" ]; then
    echo "more than one .$2 bundle under $BUNDLE -- stale output from an earlier build? clean src-tauri/target and rebuild:" >&2
    ls -la "$(dirname "$1")" >&2
    exit 1
  fi
  cp "$1" "$dest"; n=$((n + 1))
}
shopt -s nullglob
for f in "$BUNDLE"/deb/*.deb;              do copy "$f" deb; done
for f in "$BUNDLE"/appimage/*.AppImage;    do copy "$f" AppImage; done
for f in "$BUNDLE"/msi/*.msi;              do copy "$f" msi; done
for f in "$BUNDLE"/nsis/*-setup.exe;       do copy "$f" setup.exe; done
for f in "$BUNDLE"/dmg/*.dmg;              do copy "$f" dmg; done
# The .app is a directory; ship it zipped for anyone who doesn't want the dmg.
for d in "$BUNDLE"/macos/*.app; do
  (cd "$(dirname "$d")" && ditto -c -k --keepParent "$(basename "$d")" "$OUT/${NAME}_${VERSION}_${TARGET}.app.zip" 2>/dev/null \
    || zip -qry "$OUT/${NAME}_${VERSION}_${TARGET}.app.zip" "$(basename "$d")")
  n=$((n + 1))
done

if [ "$n" -eq 0 ]; then
  echo "no installers found under $BUNDLE" >&2
  exit 1
fi
# Checksums go to a temp file first: redirecting straight into $OUT would create the sums file
# before the glob expands, and it would list itself.
SUMS="$(mktemp)"
(cd "$OUT" && if command -v sha256sum >/dev/null; then sha256sum -- *; else shasum -a 256 -- *; fi) > "$SUMS"
mv "$SUMS" "$OUT/SHA256SUMS.$TARGET"
chmod 644 "$OUT/SHA256SUMS.$TARGET"
echo "collected $n installer(s) for $TARGET into $OUT:"
ls -la "$OUT"
