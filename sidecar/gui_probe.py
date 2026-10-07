#!/usr/bin/env python3
"""Answer "what state is this machine in?" for the GUI, using upstream's own code.

Run with the bundled interpreter from inside the unpacked upstream checkout:

    python gui_probe.py [--install-dir PATH]

Prints one JSON object on stdout. It never writes anything, and it computes nothing itself:
paths come from `aipotluck.installer.layout`, service state from upstream's own
`get_service_manager(...).status(...)`, so the GUI can't drift from where the CLI looks.

The one thing upstream has no notion of is whether the OS service manager is usable at all
(a container without a systemd user session, WSL without systemd). Upstream's installer raises
on `start` in that case, so the GUI needs to know before it runs the installer.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from aipotluck.installer import layout  # noqa: E402
from aipotluck.installer.platform_detect import detect_os  # noqa: E402
from aipotluck.installer.service.base import get_service_manager  # noqa: E402

SERVICE_NAME = "aipotluck"


def service_manager_usable(os_name: str) -> tuple[bool, str]:
    if os_name != "linux":
        return True, "assumed (launchd / Task Scheduler are always present)"
    if shutil.which("systemctl") is None:
        return False, "systemctl not found"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"systemctl --user failed: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, f"no systemd user session ({detail[0] if detail else 'exit ' + str(result.returncode)})"
    return True, "systemd user session available"


def probe(install_dir: Path | None) -> dict:
    os_name = detect_os()
    lay = layout.get_layout(os_name, system_scope=False, override_root=install_dir)
    runtime_path = lay.config_dir / "runtime.json"

    runtime: dict | None = None
    runtime_error = None
    if runtime_path.exists():
        try:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            runtime_error = str(exc)

    llama = (runtime or {}).get("llama_cpp") or {}
    server_binary = llama.get("server_binary")
    installed = bool(server_binary and Path(server_binary).exists())

    usable, usable_detail = service_manager_usable(os_name)
    service_state = None
    if usable:
        try:
            status = get_service_manager(os_name).status(SERVICE_NAME, system_scope=False)
            service_state = {"state": status.state.value, "detail": status.detail}
        except Exception as exc:  # report, never crash the probe
            service_state = {"state": "unknown", "detail": str(exc)}

    return {
        "os": os_name,
        "python": sys.executable,
        "layout": {
            "install_root": str(lay.install_root),
            "config_dir": str(lay.config_dir),
            "log_dir": str(lay.log_dir),
            "state_dir": str(lay.state_dir),
        },
        "runtime_json": str(runtime_path),
        "runtime_json_error": runtime_error,
        "installed": installed,
        "logged_in": bool((runtime or {}).get("logged_in")),
        "service_manager_usable": usable,
        "service_manager_detail": usable_detail,
        "service": service_state,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(probe(args.install_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
