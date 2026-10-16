#!/usr/bin/env python3
"""The release version, the build matrix, and whether everything that carries a version agrees.

    tools/release_version.py                 print the version (from src-tauri/tauri.conf.json)
    tools/release_version.py --check         exit 1 unless tauri.conf.json, Cargo.toml and
                                             ui/package.json all carry the same version
    tools/release_version.py --tag v0.2.0    also exit 1 unless the tag is exactly v<version>
    tools/release_version.py --matrix        the ENABLED targets of .github/build-targets.json, as
                                             compact JSON for a GitHub Actions `fromJSON`
    tools/release_version.py --matrix --only windows-x64
                                             just that target, even if disabled -- an explicit,
                                             one-off request (workflow_dispatch) to try it
    tools/release_version.py --target-info linux-x64
                                             one target's entry as JSON (tools/build.sh uses it)

The installers take their version from tauri.conf.json, so a release tag that disagrees with it
would publish files whose names and About box say a different version than the tag. The release
workflow runs `--tag "$GITHUB_REF_NAME"` before building anything, so that mismatch fails in
seconds instead of after a 30-minute matrix. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def versions() -> dict[str, str | None]:
    tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    ui = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))
    cargo = (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    package = cargo.split("[package]", 1)[1].split("\n[", 1)[0]
    m = re.search(r'^version\s*=\s*"([^"]+)"', package, re.M)
    return {
        "src-tauri/tauri.conf.json": tauri.get("version"),
        "src-tauri/Cargo.toml": m.group(1) if m else None,
        "ui/package.json": ui.get("version"),
    }


def targets() -> list[dict]:
    return json.loads((ROOT / ".github" / "build-targets.json").read_text(encoding="utf-8"))["targets"]


def matrix(only: str | None = None) -> dict:
    all_targets = targets()
    if only:
        picked = [t for t in all_targets if t["target"] == only]
        if not picked:
            known = ", ".join(t["target"] for t in all_targets)
            raise SystemExit(f"no such build target: {only!r} (known: {known})")
    else:
        picked = [t for t in all_targets if t.get("enabled")]
        if not picked:
            raise SystemExit("no build target is enabled in .github/build-targets.json")
    return {"include": picked}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--target-info", default=None)
    args = ap.parse_args(argv)

    if args.matrix:
        print(json.dumps(matrix(args.only or None), separators=(",", ":")))
        return 0
    if args.target_info:
        print(json.dumps(matrix(args.target_info)["include"][0]))
        return 0

    found = versions()
    version = found["src-tauri/tauri.conf.json"]
    if args.check or args.tag:
        if len(set(found.values())) != 1 or version is None:
            print("version mismatch -- these must all be equal:", file=sys.stderr)
            for path, v in found.items():
                print(f"  {path}: {v}", file=sys.stderr)
            return 1
        if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version):
            print(f"version {version!r} is not semver (MAJOR.MINOR.PATCH[-pre])", file=sys.stderr)
            return 1
    if args.tag is not None and args.tag != f"v{version}":
        print(f"tag {args.tag!r} does not match the app version: expected 'v{version}'", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
