#!/usr/bin/env bash
# Cut a release of the GUI in two steps, matching how main takes changes (through a PR):
#
#   tools/release.sh prepare 0.2.0   on a clean, up-to-date main: create branch release/v0.2.0,
#                                    set the version in all three files, commit
#                                    "chore(release): 0.2.0". Push it and open a PR yourself
#                                    (or add --push to push the branch).
#   tools/release.sh tag 0.2.0       after that PR is merged, on main: check everything a release
#                                    needs, create the annotated tag v0.2.0 on main's tip and push
#                                    it (asks first; --yes to skip the question).
#
# Pushing the tag is what builds the release: build.yml builds every enabled target and attaches
# the installers and SHA256SUMS to a DRAFT GitHub release with generated notes. Review the draft,
# install at least one build, and click Publish. See docs/RELEASING.md.
#
# `tag` refuses, before creating anything, unless:
#   - the working tree is clean and HEAD is exactly origin/main;
#   - tauri.conf.json, Cargo.toml and ui/package.json all say <version> (tools/release_version.py);
#   - the tag doesn't exist yet, locally or on origin;
#   - the pinned CLI commit (the upstream/aitpotluck-local-client submodule) is on the CLI's main,
#     so a release never ships a CLI that only exists on a feature branch.
#
# Env: AIPOTLUCK_CLI_REMOTE overrides where the CLI's main is fetched from (tests use a local repo).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "release.sh: needs Python 3.9+ on PATH" >&2; exit 2; }

die() { echo "release.sh: $*" >&2; exit 1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

[ $# -ge 2 ] || usage
CMD="$1"; VERSION="${2#v}"; shift 2
PUSH=0; YES=0
for a in "$@"; do
  case "$a" in
    --push) PUSH=1 ;;
    --yes) YES=1 ;;
    *) die "unknown option: $a" ;;
  esac
done
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || die "'$VERSION' is not MAJOR.MINOR.PATCH[-pre]"
TAG="v$VERSION"

require_clean_main() {
  [ -z "$(git status --porcelain --untracked-files=no)" ] || die "the working tree has uncommitted changes"
  git fetch -q origin main --tags
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] \
    || die "HEAD isn't origin/main ($(git rev-parse --short origin/main)). Check out main and pull first."
}

case "$CMD" in
  prepare)
    require_clean_main
    current="$("$PY" tools/release_version.py)"
    [ "$current" != "$VERSION" ] || die "the version is already $VERSION; run: tools/release.sh tag $VERSION"
    if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then die "$TAG already exists"; fi
    branch="release/$TAG"
    if git rev-parse -q --verify "refs/heads/$branch" >/dev/null; then die "branch $branch already exists"; fi
    git checkout -q -b "$branch"
    "$PY" tools/release_version.py --set "$VERSION"
    "$PY" tools/release_version.py --check >/dev/null
    git add src-tauri/tauri.conf.json src-tauri/Cargo.toml src-tauri/Cargo.lock ui/package.json
    git commit -q -m "chore(release): $VERSION"
    echo "Prepared $current -> $VERSION on branch $branch ($(git rev-parse --short HEAD))."
    if [ "$PUSH" = 1 ]; then
      git push -q -u origin "$branch"
      echo "Pushed $branch. Open a PR into main, merge it, then: tools/release.sh tag $VERSION"
    else
      echo "Next: git push -u origin $branch, open a PR into main, merge it, then: tools/release.sh tag $VERSION"
    fi
    ;;

  tag)
    require_clean_main
    "$PY" tools/release_version.py --tag "$TAG" >/dev/null \
      || die "the app's version files don't all say $VERSION (merge the release PR first?)"
    if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then die "$TAG already exists locally"; fi
    if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then die "$TAG already exists on origin"; fi

    sub=upstream/aitpotluck-local-client
    pin="$(git ls-tree HEAD "$sub" | awk '{print $3}')"
    [ -n "$pin" ] || die "no CLI pin found at $sub"
    cli_remote="${AIPOTLUCK_CLI_REMOTE:-$(git config -f .gitmodules "submodule.$sub.url")}"
    [ -e "$sub/.git" ] || git submodule update -q --init "$sub"
    git -C "$sub" fetch -q "$cli_remote" main || die "couldn't fetch the CLI's main from $cli_remote"
    git -C "$sub" merge-base --is-ancestor "$pin" FETCH_HEAD \
      || die "the pinned CLI commit ${pin:0:7} isn't on the CLI's main. Merge the CLI change first and re-pin."

    head="$(git rev-parse --short HEAD)"
    echo "Ready: $TAG on main at $head, CLI pin ${pin:0:7} (on the CLI's main)."
    if [ "$YES" != 1 ]; then
      read -r -p "Create and push $TAG? This starts the release build. [y/N] " ok
      [[ "$ok" =~ ^[Yy] ]] || { echo "Nothing created."; exit 1; }
    fi
    git tag -a "$TAG" -m "$TAG"
    git push -q origin "$TAG"
    echo "Pushed $TAG. build.yml now builds every enabled target and makes a DRAFT release."
    echo "Review it, install at least one build, then Publish: Releases -> $TAG."
    ;;

  *) usage ;;
esac
