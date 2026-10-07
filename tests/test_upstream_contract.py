"""Contract tests: the GUI's Python-side assumptions, checked against upstream's REAL code.

These start upstream's actual service payload (aipotluck/service/aipotluck_service.py -- the exact
argv the GUI's runtime.rs uses when it hosts the service) against a throwaway config dir, and run
upstream's actual `cli login/logout` the way the GUI's Pair/Unpair buttons do. Nothing upstream is
mocked; only the outside world is kept out (no network: the newt binary is pre-seeded at the path
upstream's checksum-verified cache expects, and no llama-server is installed).

Which upstream is tested: $AIPOTLUCK_UPSTREAM_DIR (tools/sync_upstream.sh points this at a
candidate commit), else the pinned submodule.

Run on the bundled interpreter: `$(tools/bundled-python.sh --with-pytest) -m pytest tests`.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("AIPOTLUCK_UPSTREAM_DIR") or ROOT / "upstream" / "aitpotluck-local-client")
PROBE = ROOT / "sidecar" / "gui_probe.py"
PLAN = ROOT / "sidecar" / "gui_plan.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "XDG_"))}
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_STATE_HOME=str(home / ".local" / "state"),
        PYTHONNOUSERSITE="1",
        PYTHONUNBUFFERED="1",
        # No service manager in tests: upstream's systemd backend no-ops when systemctl is absent.
        PATH="/usr/bin/false-dir-only",
    )
    return env


def _get(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".config").mkdir(parents=True)
    return h


def _layout(home: Path) -> dict:
    out = subprocess.run(
        [sys.executable, str(PROBE)], cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_probe_reports_upstreams_own_layout_and_a_fresh_machine_as_not_installed(home: Path):
    probe = _layout(home)
    assert probe["installed"] is False
    assert probe["logged_in"] is False
    # The probe must place runtime.json exactly where upstream's own CLI reads it from.
    assert probe["runtime_json"] == str(home / ".config" / "aipotluck" / "runtime.json")
    assert probe["service_manager_usable"] is False  # no systemctl on PATH in this test


def test_probe_sees_an_install_only_when_the_llama_server_binary_really_exists(home: Path):
    cfg = home / ".config" / "aipotluck"
    cfg.mkdir(parents=True)
    fake = home / "llama-server"
    (cfg / "runtime.json").write_text(json.dumps({"llama_cpp": {"server_binary": str(fake)}, "logged_in": True}))
    assert _layout(home)["installed"] is False
    fake.write_text("#!/bin/sh\n")
    probe = _layout(home)
    assert probe["installed"] is True and probe["logged_in"] is True


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "aipotluck.installer.cli", *args],
        cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=120,
    )


def test_pairing_file_the_gui_writes_is_accepted_by_upstreams_own_parser(tmp_path: Path):
    """runtime.rs write_private_credentials writes the clipboard text, trimmed, to a file that
    `cli login --credentials-file` reads. Upstream's parser is the authority on what's accepted."""
    sys.path.insert(0, str(UPSTREAM))
    try:
        from aipotluck.installer import cli
    finally:
        sys.path.pop(0)
    clipboard = '  {"tunnelId":"t-123","tunnelSecret":"sekret-xyz","tunnelEndpoint":"https://pangolin.example"}\n'
    creds = tmp_path / "pairing.json"
    creds.write_text(clipboard.strip())
    assert cli._parse_credentials_json(creds.read_text()) == ("t-123", "sekret-xyz", "https://pangolin.example")


def test_login_with_a_bad_pairing_file_fails_loudly_and_leaves_the_device_unpaired(home: Path, tmp_path: Path):
    cfg = home / ".config" / "aipotluck"
    cfg.mkdir(parents=True)
    (cfg / "runtime.json").write_text(json.dumps({"llama_cpp": {}, "logged_in": False}))
    creds = tmp_path / "pairing.json"
    creds.write_text('{"tunnelId": "t"}')
    result = _run_cli(home, "login", "--credentials-file", str(creds))
    assert result.returncode != 0
    assert json.loads((cfg / "runtime.json").read_text())["logged_in"] is False


def test_logout_via_upstream_cli_clears_pairing_the_way_unpair_expects(home: Path):
    cfg = home / ".config" / "aipotluck"
    cfg.mkdir(parents=True)
    (cfg / "runtime.json").write_text(json.dumps({
        "llama_cpp": {}, "logged_in": True,
        "tunnel": {"provider": "pangolin", "id": "t", "secret": "s", "endpoint": "e", "binary": "/x"},
    }))
    result = _run_cli(home, "logout")
    assert result.returncode == 0, result.stderr
    after = json.loads((cfg / "runtime.json").read_text())
    assert after["logged_in"] is False and "tunnel" not in after
    assert _layout(home)["logged_in"] is False


@pytest.fixture
def hosted_service(home: Path):
    """Upstream's service payload, started with the argv runtime.rs spawn_service uses."""
    cfg = home / ".config" / "aipotluck"
    logs = home / ".local" / "state" / "aipotluck" / "logs"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "runtime.json").write_text(json.dumps({"llama_cpp": {}, "logged_in": False}))
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(UPSTREAM / "aipotluck" / "service" / "aipotluck_service.py"),
         "--config-dir", str(cfg), "--log-dir", str(logs), "--port", str(port)],
        cwd=UPSTREAM, env=_env(home), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if _get(base + "/healthz")[0] == 200:
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("upstream service never became healthy")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_hosted_service_answers_every_route_the_gui_proxy_allows(hosted_service: str):
    # The Rust allow-list (src-tauri/src/service.rs) must only name routes upstream really serves.
    for path in ("/healthz", "/status", "/jobs"):
        status, _ = _get(hosted_service + path)
        assert status == 200, path


def test_status_fields_the_status_screen_reads_are_present_while_logged_out(hosted_service: str):
    _, body = _get(hosted_service + "/status")
    status = json.loads(body)
    # ui/src/lib/state.ts statusRows reads exactly these.
    for key in ("logged_in", "llama_server", "tunnel", "runtime_config"):
        assert key in status, key
    assert status["logged_in"] is False
    assert status["llama_server"] is None and status["tunnel"] is None


def _plan(home: Path, *args: str) -> dict:
    env = _env(home)
    # Keep the outside world out: every request goes to a proxy on a closed port and fails fast.
    env.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", NO_PROXY="")
    env.pop("no_proxy", None)
    for token in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        env.pop(token, None)
    out = subprocess.run(
        [sys.executable, str(PLAN), *args], cwd=UPSTREAM, env=env, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_install_plan_offline_reports_unknown_sizes_and_never_fails(home: Path):
    plan = _plan(home)
    assert plan["llama_cpp"]["bytes"] is None
    assert plan["newt"]["bytes"] is None
    assert plan["model"]["bytes"] is None
    # It still names what would be installed: upstream's own pins, for this host.
    llama_pin = json.loads((UPSTREAM / "llama_version.json").read_text())
    assert plan["llama_cpp"]["tag"] == llama_pin["tag"]
    if not plan["llama_cpp"]["source_build"]:
        assert plan["llama_cpp"]["asset_key"] in llama_pin["assets"]
        assert plan["llama_cpp"]["file"] == llama_pin["assets"][plan["llama_cpp"]["asset_key"]]["file"]
    assert plan["newt"]["tag"] == json.loads((UPSTREAM / "newt_version.json").read_text())["tag"]


def test_install_plan_default_model_is_the_one_upstreams_installer_would_pull(home: Path):
    parsed = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from aipotluck.installer.install import build_arg_parser;"
         "print(build_arg_parser().parse_args([]).model_hf)"],
        cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=30,
    )
    assert parsed.returncode == 0, parsed.stderr
    plan = _plan(home)
    assert plan["model"]["default_id"] == parsed.stdout.strip()
    assert plan["model"]["id"] == plan["model"]["default_id"] and plan["model"]["is_default"] is True


def test_customized_model_is_planned_and_handed_to_upstream_in_the_form_it_parses(home: Path):
    chosen = "unsloth/Qwen3-4B-GGUF:Q4_K_M"
    plan = _plan(home, f"--model-hf={chosen}")
    assert plan["model"]["id"] == chosen and plan["model"]["is_default"] is False
    # setup_device passes the override as one `--model-hf=<id>` token; upstream must read it back.
    parsed = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from aipotluck.installer.install import build_arg_parser;"
         f"print(build_arg_parser().parse_args(['--backend', 'auto', '--model-hf={chosen}']).model_hf)"],
        cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=30,
    )
    assert parsed.returncode == 0, parsed.stderr
    assert parsed.stdout.strip() == chosen
