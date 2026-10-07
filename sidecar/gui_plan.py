#!/usr/bin/env python3
"""Answer "what will Set up install, and roughly how big is it?" for the GUI, using upstream's code.

Run with the bundled interpreter from inside the unpacked upstream checkout:

    python gui_plan.py [--model-hf REPO[:QUANT]]

Prints one JSON object on stdout. It never writes anything and downloads nothing. Every decision
is upstream's own:
- which llama.cpp build: `build_strategy.resolve_install_strategy` (and `build_cache` for a host
  that needs a custom build), the same calls `install.run_install` makes;
- which newt binary: `newt_fetch.resolve_newt_asset`;
- the default model: `install.DEFAULT_MODEL_HF`;
- the model's size: `model_preflight.remote_model_bytes`, which mirrors llama.cpp's own `-hf`
  file resolution, so it measures the file the downloader would fetch.

The one thing upstream doesn't know is how big its pinned llama.cpp and newt downloads are. This
asks the release URL upstream would download from (built the way `fetch.download_asset` builds it)
for its Content-Length, with a HEAD request. Any failure there, or anywhere, is reported as an
unknown size (null), never as an error: this is an estimate shown before anything happens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.getcwd())

from aipotluck.installer import build_cache, build_strategy, fetch, model_preflight, newt_fetch  # noqa: E402
from aipotluck.installer.install import DEFAULT_MODEL_HF, REPO_ROOT  # noqa: E402
from aipotluck.installer.platform_detect import detect_host_profile  # noqa: E402

_TIMEOUT_SECONDS = 10.0


def _content_length(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "aipotluck-local-client-gui"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            value = response.headers.get("Content-Length")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        size = int(value) if value else 0
    except ValueError:
        return None
    return size if size > 0 else None


def _release_url(manifest: dict, filename: str) -> str:
    return f"{manifest['release_base_url']}/{manifest['tag']}/{filename}"


def plan_llama(profile) -> dict:
    manifest = fetch.load_version_manifest(REPO_ROOT / "llama_version.json")
    out = {"tag": manifest.get("tag"), "asset_key": None, "file": None, "bytes": None, "source_build": False}
    try:
        strategy = build_strategy.resolve_install_strategy(profile, manifest)
    except Exception as exc:  # report, never crash the plan
        out["error"] = str(exc)
        return out
    if strategy.use_source_build:
        custom_manifest = build_cache.load_custom_manifest(REPO_ROOT / "llama_custom_builds.json")
        match = build_cache.find_custom_build(profile, custom_manifest, cuda_arch=strategy.cuda_arch)
        if match is None:
            out.update(source_build=True, asset_key=profile.asset_key, reason=strategy.reason)
            return out
        key, entry = match
        out.update(asset_key=key, file=entry["file"], bytes=_content_length(_release_url(custom_manifest, entry["file"])))
        return out
    out.update(
        asset_key=strategy.asset_key,
        file=strategy.asset_entry["file"],
        bytes=_content_length(_release_url(manifest, strategy.asset_entry["file"])),
    )
    return out


def plan_newt(profile) -> dict:
    manifest = newt_fetch.load_newt_manifest(REPO_ROOT / "newt_version.json")
    out = {"tag": manifest.get("tag"), "file": None, "bytes": None}
    try:
        _, entry = newt_fetch.resolve_newt_asset(manifest, profile)
    except Exception as exc:  # e.g. an unverified checksum on this platform: pairing would fail too
        out["error"] = str(exc)
        return out
    out.update(file=entry["file"], bytes=_content_length(_release_url(manifest, entry["file"])))
    return out


def plan_model(model_hf: str | None) -> dict:
    model_id = model_hf or DEFAULT_MODEL_HF
    size = model_preflight.remote_model_bytes(model_id)
    return {
        "id": model_id,
        "is_default": model_id == DEFAULT_MODEL_HF,
        "default_id": DEFAULT_MODEL_HF,
        "bytes": size.total_bytes if size else None,
        "files": size.paths if size else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-hf", default=None)
    args = parser.parse_args()
    profile = detect_host_profile("auto")
    print(
        json.dumps(
            {
                "host": {"os": profile.os_name, "arch": profile.arch, "backend": profile.backend},
                "llama_cpp": plan_llama(profile),
                "newt": plan_newt(profile),
                "model": plan_model(args.model_hf),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
