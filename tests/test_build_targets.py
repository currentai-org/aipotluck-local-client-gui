"""The release build matrix (.github/build-targets.json) and the version gate the release workflow
runs first (tools/release_version.py). Both are pure-data checks: no network, no build.

The matrix is the one place a target is declared, so these tests are what stop it naming a target
the app can't actually ship (no bundled Python, no newt) or a runner/bundle combination the
workflow can't build.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream" / "aitpotluck-local-client"
TARGETS = json.loads((ROOT / ".github" / "build-targets.json").read_text())["targets"]
TOOL = ROOT / "tools" / "release_version.py"

BUNDLES_BY_OS = {"linux": {"deb", "appimage", "rpm"}, "windows": {"nsis", "msi"}, "macos": {"app", "dmg"}}
TRIPLE_BY_TARGET = {
    "linux-x64": "x86_64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
    "windows-x64": "x86_64-pc-windows-msvc",
    "windows-arm64": "aarch64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x64": "x86_64-apple-darwin",
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, cwd=ROOT)


def test_every_build_target_has_a_bundled_python_and_a_newt_pin():
    """A target with no bundled Python can't start; one with no newt pin can't pair. Neither may
    be in the release matrix, however tempting (e.g. windows-arm64 has a llama.cpp asset)."""
    python = json.loads((ROOT / "runtime" / "python_version.json").read_text())["assets"]
    newt = json.loads((UPSTREAM / "newt_version.json").read_text())["assets"]
    for t in TARGETS:
        assert t["target"] in python, f"{t['target']}: no bundled Python asset"
        assert t["target"] in newt, f"{t['target']}: no newt asset in upstream's pin"


# The llama.cpp asset every device of a target falls back to: CPU, except Apple silicon, where
# upstream's one prebuilt asset is the Metal build (it has no separate CPU-only one).
BASELINE_BACKEND = {"macos-arm64": "metal"}


def test_every_build_target_has_a_baseline_llama_asset_upstream_can_install():
    """The GUI ships one binary per OS x arch; the baseline llama.cpp asset is what every device of
    that kind can install with no GPU detected, so it must exist for each target."""
    llama = json.loads((UPSTREAM / "llama_version.json").read_text())["assets"]
    for t in TARGETS:
        key = f"{t['target']}-{BASELINE_BACKEND.get(t['target'], 'cpu')}"
        assert key in llama, f"{t['target']}: no {key} llama.cpp asset upstream"


def test_the_must_ship_targets_are_all_present():
    names = {t["target"] for t in TARGETS if t["priority"] == "must"}
    assert names == {"linux-x64", "windows-x64", "macos-arm64"}


def test_each_target_names_a_matching_rust_triple_and_only_its_own_os_bundles():
    seen = set()
    for t in TARGETS:
        assert t["target"] not in seen, f"duplicate target {t['target']}"
        seen.add(t["target"])
        assert t["rust_target"] == TRIPLE_BY_TARGET[t["target"]]
        os_name = t["target"].split("-")[0]
        bundles = set(t["bundles"].split(","))
        assert bundles <= BUNDLES_BY_OS[os_name], f"{t['target']}: {bundles - BUNDLES_BY_OS[os_name]}"


def test_linux_targets_build_on_ubuntu_22_04_so_the_glibc_floor_stays_low():
    """A Linux binary needs the build host's glibc or newer. Building on 24.04 would silently drop
    22.04 users (and Jetson/JetPack 6, which upstream supports). A self-hosted runner (label list)
    must carry an explicit ubuntu-22.04 label to say it meets the same floor."""
    for t in TARGETS:
        if t["target"].startswith("linux-"):
            labels = t["runner"] if isinstance(t["runner"], list) else [t["runner"]]
            assert any(l.startswith("ubuntu-22.04") for l in labels), f"{t['target']} builds on {t['runner']}"


def test_runner_is_a_label_or_a_list_of_labels():
    """runs-on takes either form; the docs promise a self-hosted list can be dropped in."""
    for t in TARGETS:
        r = t["runner"]
        assert isinstance(r, str) or (isinstance(r, list) and r and all(isinstance(x, str) for x in r))


def test_the_default_matrix_builds_only_enabled_targets():
    """A disabled target must cost nothing on PRs and pushes: it isn't in the default matrix."""
    r = _run("--matrix")
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout)
    assert [t["target"] for t in m["include"]] == [t["target"] for t in TARGETS if t["enabled"]]


def test_only_targets_proven_on_a_real_machine_are_enabled():
    """Today's decision, made explicit so flipping a target on is a deliberate, visible change
    (update this test in the same commit that enables one). Linux: the dev host. macOS arm64 and
    x64: built with tools/build.sh --release-target on a Mac mini (M5 Pro, macOS 27), the arm64
    app run, its runtime set up and paired. Windows x64: built the same way on a Windows 10 22H2
    PC, installed as a standard user, set up on CPU, CUDA and Vulkan, paired, and the background
    logon task confirmed at the desktop."""
    assert {t["target"] for t in TARGETS if t["enabled"]} == {
        "linux-x64", "linux-arm64", "windows-x64", "macos-arm64", "macos-x64"
    }


def test_windows_ships_the_nsis_installer_only():
    """The MSI is left out until it has been built once: WiX's light.exe needs the Windows
    Installer service, which the Linux dev environment used to prove the Windows build can't reach,
    so no MSI has ever been produced. The NSIS installer is the one tested end to end. A failing MSI
    step would fail the Windows job and, with it, every nightly (they publish only when all
    enabled targets build). To add it: one `only: windows-x64` dispatch with "nsis,msi" first."""
    win = next(t for t in TARGETS if t["target"] == "windows-x64")
    assert win["bundles"] == "nsis"


def test_every_target_says_whether_it_is_enabled():
    for t in TARGETS:
        assert isinstance(t.get("enabled"), bool), f"{t['target']}: 'enabled' must be true or false"


def test_a_disabled_target_can_still_be_built_on_request(monkeypatch):
    """workflow_dispatch `only` and tools/build.sh --release-target both rely on this. Every
    target is enabled today, so the check runs against a copy of the list with one switched off."""
    sys.path.insert(0, str(TOOL.parent))
    import release_version

    some_off = [dict(t, enabled=(t["target"] != "windows-x64")) for t in TARGETS]
    monkeypatch.setattr(release_version, "targets", lambda: some_off)
    assert "windows-x64" not in [t["target"] for t in release_version.matrix()["include"]]
    assert [t["target"] for t in release_version.matrix("windows-x64")["include"]] == ["windows-x64"]
    for t in TARGETS:  # and every real target is buildable by name
        r = _run("--matrix", "--only", t["target"])
        assert r.returncode == 0, r.stderr
        assert [x["target"] for x in json.loads(r.stdout)["include"]] == [t["target"]]


def test_an_unknown_target_is_refused_rather_than_building_nothing():
    r = _run("--matrix", "--only", "windows-arm64")
    assert r.returncode != 0 and "no such build target" in (r.stderr + r.stdout)


def test_version_files_agree_today():
    r = _run("--check")
    assert r.returncode == 0, r.stderr


def test_a_release_tag_that_disagrees_with_the_app_version_is_refused():
    version = _run().stdout.strip()
    assert _run("--tag", f"v{version}").returncode == 0
    bad = _run("--tag", "v99.0.0")
    assert bad.returncode == 1 and "does not match" in bad.stderr
    assert _run("--tag", version).returncode == 1, "a tag without the leading v must be refused"
