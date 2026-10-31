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
UPSTREAM = Path(os.environ.get("AIPOTLUCK_UPSTREAM_DIR") or ROOT / "upstream" / "aipotluck-local-client")
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
    if sys.platform == "win32":
        # Upstream's Windows layout reads %LOCALAPPDATA%; keep it inside the test home. PATH must
        # keep System32 (python.exe needs its DLLs, and schtasks lives there).
        env.update(
            USERPROFILE=str(home),
            LOCALAPPDATA=str(home / "AppData" / "Local"),
            APPDATA=str(home / "AppData" / "Roaming"),
            PATH=os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
        )
    return env


def _get(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def _cfg(home: Path) -> Path:
    """Where upstream keeps runtime.json for a user install on this OS (aipotluck/installer/layout.py),
    written out independently here so the probe is checked against it rather than against itself."""
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "aipotluck" / "config"
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "aipotluck" / "config"
    return home / ".config" / "aipotluck"


def _logs(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "aipotluck"
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "aipotluck" / "logs"
    return home / ".local" / "state" / "aipotluck" / "logs"


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
    assert probe["runtime_json"] == str(_cfg(home) / "runtime.json")
    # Linux: no systemctl on PATH in this test. macOS/Windows: launchd/Task Scheduler are always
    # there, and before anything is installed the probe takes them as usable.
    assert probe["service_manager_usable"] is (sys.platform in ("darwin", "win32"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Task Scheduler")
def test_an_installed_windows_device_with_no_scheduled_task_is_hosted_by_the_app(home: Path):
    """Upstream now refuses to report a task it couldn't register (a non-interactive logon). After
    an install, no task means this session can't have one, so the GUI must host the service --
    otherwise nothing runs it at all."""
    cfg = _cfg(home)
    cfg.mkdir(parents=True)
    binary = home / "llama-server.exe"
    binary.write_text("")
    (cfg / "runtime.json").write_text(json.dumps({"llama_cpp": {"server_binary": str(binary)}, "logged_in": False}))
    probe = _layout(home)
    assert probe["installed"] is True
    assert probe["service"]["state"] == "not_installed"
    assert probe["service_manager_usable"] is False


def test_probe_sees_an_install_only_when_the_llama_server_binary_really_exists(home: Path):
    cfg = _cfg(home)
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
    cfg = _cfg(home)
    cfg.mkdir(parents=True)
    (cfg / "runtime.json").write_text(json.dumps({"llama_cpp": {}, "logged_in": False}))
    creds = tmp_path / "pairing.json"
    creds.write_text('{"tunnelId": "t"}')
    result = _run_cli(home, "login", "--credentials-file", str(creds))
    assert result.returncode != 0
    assert json.loads((cfg / "runtime.json").read_text())["logged_in"] is False


def test_logout_via_upstream_cli_clears_pairing_the_way_unpair_expects(home: Path):
    cfg = _cfg(home)
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
    cfg = _cfg(home)
    logs = _logs(home)
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


@pytest.mark.parametrize("backend", ["cuda", "vulkan", "cpu"])
def test_a_compute_override_is_planned_and_handed_to_upstream_in_the_form_it_parses(home: Path, backend: str):
    plan = _plan(home, f"--backend={backend}")
    # The plan is sized for the build upstream's own resolver picks for that backend on this host:
    # its exact asset, or (no asset for this OS/arch) a source build -- never a silent other one.
    assert plan["host"]["backend"] == backend and plan["backends"]["selected"] == backend
    if not plan["llama_cpp"]["source_build"]:
        assert plan["llama_cpp"]["asset_key"].endswith(f"-{backend}")
    # setup_device passes the override as one `--backend=<b>` token; upstream must accept it.
    parsed = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from aipotluck.installer.install import build_arg_parser;"
         f"print(build_arg_parser().parse_args(['--backend={backend}']).backend)"],
        cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=30,
    )
    assert parsed.returncode == 0, parsed.stderr
    assert parsed.stdout.strip() == backend


def test_the_compute_picker_reports_upstreams_auto_choice_and_every_option(home: Path):
    plan = _plan(home)
    picker = plan["backends"]
    assert picker["auto"] == plan["host"]["backend"] == picker["selected"]
    llama_pin = json.loads((UPSTREAM / "llama_version.json").read_text())
    host = plan["host"]
    if host["os"] in ("linux", "windows"):
        assert [o["backend"] for o in picker["options"]] == ["cuda", "vulkan", "cpu"]
        for o in picker["options"]:
            assert o["available"] == (f"{host['os']}-{host['arch']}-{o['backend']}" in llama_pin["assets"])
    else:
        assert picker["options"] == []


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


def _size_with_flaky_server(home: Path, statuses: list[int]) -> tuple[object, int]:
    """Ask gui_plan's size lookup about a local server answering `statuses` in turn (then 200)."""
    import http.server
    import threading

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            seen.append(self.path)
            code = statuses[len(seen) - 1] if len(seen) <= len(statuses) else 200
            self.send_response(code)
            self.send_header("Content-Length", "16844042" if code == 200 else "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(PLAN.parent)!r}); import gui_plan;"
             f"print(gui_plan._content_length('http://127.0.0.1:{server.server_port}/asset'))"],
            cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=30,
        )
    finally:
        server.shutdown()
    assert out.returncode == 0, out.stderr
    value = out.stdout.strip()
    return (None if value == "None" else int(value)), len(seen)


def test_a_passing_github_server_error_does_not_leave_a_size_unknown(home: Path):
    assert _size_with_flaky_server(home, [500]) == (16844042, 2)


def test_a_size_lookup_that_cannot_succeed_is_not_retried(home: Path):
    assert _size_with_flaky_server(home, [404]) == (None, 1)
    assert _size_with_flaky_server(home, [500, 502]) == (None, 2)


# ---------------------------------------------------------------- one-click pairing (cli login, no flags)
#
# The GUI's "Pair in your browser" runs upstream's `cli login` with no credential flags (plus
# `--server-url=<override>` when the hidden override is set), reads the pairing link out of what it
# prints, and SIGINTs it for Cancel. These hold upstream to exactly those behaviours, against a
# stand-in aipotluck.org on 127.0.0.1 (http is accepted for loopback only, by upstream's rule).

NEWT_CACHE = ROOT / "build" / "cache" / "newt"


def _seed_newt(home: Path) -> None:
    """login fetches newt BEFORE it polls (so a server it provisions is never stranded), so the
    real, checksum-verified binary must be where upstream's cache looks. Downloaded once and kept
    in build/cache; upstream re-verifies the sha256 itself before trusting it."""
    import hashlib
    import shutil
    import urllib.request

    sys.path.insert(0, str(UPSTREAM))
    try:
        from aipotluck.installer.platform_detect import detect_host_profile
    finally:
        sys.path.pop(0)
    manifest = json.loads((UPSTREAM / "newt_version.json").read_text())
    profile = detect_host_profile("cpu")
    entry = manifest["assets"][f"{profile.os_name}-{profile.arch}"]
    cached = NEWT_CACHE / manifest["tag"] / entry["file"]
    if not cached.exists() or hashlib.sha256(cached.read_bytes()).hexdigest() != entry["sha256"]:
        cached.parent.mkdir(parents=True, exist_ok=True)
        url = f"{manifest['release_base_url']}/{manifest['tag']}/{entry['file']}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                cached.write_bytes(r.read())
        except OSError as exc:
            pytest.skip(f"newt not cached and not downloadable ({exc}); one-click login fetches it first")
    # Upstream's own layout for this OS, computed under the test HOME (Path.home() reads $HOME).
    out = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.');"
         "from aipotluck.installer import layout, platform_detect;"
         "print(layout.get_layout(platform_detect.detect_os()).install_root)"],
        cwd=UPSTREAM, env=_env(home), capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    install_root = Path(out.stdout.strip())
    dest = install_root / "newt" / manifest["tag"] / entry["file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, dest)
    dest.chmod(0o755)


class _FakePairingServer:
    """aipotluck.org's poll route, per upstream's pairing.py docstring: `{}` until approved, then
    exactly once `{"id","label","installArgs":{...}}`, then `{}` again. `approve_after` polls."""

    def __init__(self, approve_after: int = 1, status: int = 200):
        import http.server
        import threading

        self.polls: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.polls.append(self.path)
                if status != 200:
                    self.send_response(status)
                    self.end_headers()
                    return
                n = len(outer.polls)
                body = {}
                if n == approve_after + 1:
                    body = {"id": "srv-1", "label": "test-box", "installArgs": {
                        "tunnelId": "t-oneclick", "tunnelSecret": "s-oneclick-not-real",
                        "tunnelEndpoint": "https://pangolin.example"}}
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


def _login_env(home: Path) -> dict:
    env = _env(home)
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER", "AIPOTLUCK_SERVER_URL"):
        env.pop(k, None)  # no browser: the printed link is the only way through, as on a headless box
    return env


def _ready_to_pair(home: Path) -> Path:
    cfg = _cfg(home)
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "runtime.json").write_text(json.dumps({"llama_cpp": {}, "logged_in": False}))
    _seed_newt(home)
    return cfg


def test_one_click_login_prints_the_link_the_gui_reads_and_pairs_once_approved(home: Path):
    cfg = _ready_to_pair(home)
    server = _FakePairingServer(approve_after=1)
    try:
        # Exactly the argv pair_one_click builds when the override is set: one --server-url=<url> token.
        out = subprocess.run(
            [sys.executable, "-m", "aipotluck.installer.cli", "login", f"--server-url={server.url}/"],
            cwd=UPSTREAM, env=_login_env(home), capture_output=True, text=True, timeout=120,
        )
    finally:
        server.close()
    assert out.returncode == 0, out.stdout + out.stderr
    lines = (out.stdout + out.stderr).splitlines()
    # ui/src/lib/oneclick.ts reads: a line that is only the URL (indented), to the pair page, with an id;
    # and the "Open this link..." wording when no browser could be opened.
    links = [l.strip() for l in lines if "/chat/local-inference/pair?" in l]
    assert len(links) == 1 and links[0].startswith(f"{server.url}/chat/local-inference/pair?id=")
    assert any(l.startswith("Open this link in a browser") for l in lines)
    # The poll went to the server the GUI chose (trailing slash normalized away), under the same id.
    pairing_id = links[0].split("id=", 1)[1].split("&", 1)[0]
    assert server.polls and all(p == f"/chat/api/v2/local-inference/pairings/{pairing_id}" for p in server.polls)
    after = json.loads((cfg / "runtime.json").read_text())
    assert after["logged_in"] is True and after["tunnel"]["id"] == "t-oneclick"
    # The secret went from the server straight into upstream's config, never onto stdout for the GUI to see.
    assert "s-oneclick-not-real" not in out.stdout + out.stderr
    assert _layout(home)["logged_in"] is True


def test_cancelling_a_waiting_one_click_login_changes_nothing(home: Path):
    """cancel_pairing sends SIGINT; upstream must treat it as Ctrl-C and leave the device unpaired."""
    import signal

    cfg = _ready_to_pair(home)
    server = _FakePairingServer(approve_after=10_000)  # never approves
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "aipotluck.installer.cli", "login", f"--server-url={server.url}"],
            cwd=UPSTREAM, env=_login_env(home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + 60
        while not server.polls and time.time() < deadline:
            time.sleep(0.2)
        assert server.polls, "login never started polling"
        proc.send_signal(signal.SIGINT)
        output, _ = proc.communicate(timeout=30)
    finally:
        server.close()
    assert proc.returncode == 130, output
    assert "Pairing cancelled; nothing was changed." in output
    assert json.loads((cfg / "runtime.json").read_text())["logged_in"] is False


def test_a_server_without_one_click_fails_fast_with_the_message_the_gui_turns_into_the_paste_fallback(home: Path):
    cfg = _ready_to_pair(home)
    server = _FakePairingServer(status=404)
    try:
        out = subprocess.run(
            [sys.executable, "-m", "aipotluck.installer.cli", "login", f"--server-url={server.url}"],
            cwd=UPSTREAM, env=_login_env(home), capture_output=True, text=True, timeout=60,
        )
    finally:
        server.close()
    assert out.returncode == 1
    assert "doesn't offer one-click pairing" in out.stdout + out.stderr  # oneClickUnavailable()
    assert json.loads((cfg / "runtime.json").read_text())["logged_in"] is False


SERVER = ROOT / "sidecar" / "gui_server.py"


def _server(home: Path, *args: str, env_url: str | None = None) -> dict:
    env = _login_env(home)
    if env_url:
        env["AIPOTLUCK_SERVER_URL"] = env_url
    out = subprocess.run([sys.executable, str(SERVER), *args], cwd=UPSTREAM, env=env,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_override_is_judged_by_upstreams_own_rule_not_the_guis(home: Path):
    sys.path.insert(0, str(UPSTREAM))
    try:
        from aipotluck.installer import pairing as up
    finally:
        sys.path.pop(0)
    default = _server(home)
    assert default["effective"] == up.DEFAULT_SERVER_URL and default["error"] is None
    assert _server(home, "--server-url=https://develop.aipotluck.org/")["effective"] == "https://develop.aipotluck.org"
    assert _server(home, "--server-url=http://localhost:5173")["effective"] == "http://localhost:5173"
    refused = _server(home, "--server-url=http://develop.aipotluck.org")
    assert refused["effective"] is None and "plain http" in refused["error"]
    assert _server(home, "--server-url=ftp://x")["error"]
    # With no GUI override, upstream's env var still applies, exactly as for a terminal user.
    assert _server(home, env_url="https://staging.example")["effective"] == "https://staging.example"
