#!/usr/bin/env python3
"""End-to-end smoke test: drive the REAL app through the whole user flow on a throwaway HOME.

    tools/e2e-smoke.py [--app PATH] [--keep]

What it does, through the actual window (WebDriver via tauri-driver -> WebKitWebDriver):
  1. fresh HOME -> app unpacks its runtime -> "Set up this computer"
  2. click Set up -> upstream's real installer runs (real llama.cpp + model download)
  3. pair screen -> "Paste instead" -> type a pairing JSON -> Pair -> upstream's real `cli login`
     (real newt download, checksum-verified against upstream's pin)
  4. running screen: service + inference server healthy; the tunnel row must report the fake
     endpoint as NOT connected (proves the status screen reads tunnel_connected, not `running`)
  5. Unpair -> back to the pair screen, runtime.json logged out
Screenshots of every step go to build/e2e/.

Needs: Xvfb (or a real display), tauri-driver (`cargo install tauri-driver --locked`),
WebKitWebDriver (apt: webkit2gtk-driver), and a debug or release build of the app.
The pairing used is fake (endpoint https://pangolin.invalid) -- it never reaches aipotluck.org.
Exit 0 = every step passed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "e2e"
FAKE_PAIRING = {"tunnelId": "e2e-smoke", "tunnelSecret": "e2e-not-a-secret", "tunnelEndpoint": "https://pangolin.invalid"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WD:
    def __init__(self, base: str):
        self.base, self.sid = base, None

    def _req(self, method: str, path: str, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}").get("value")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path}: {e.code} {e.read()[:400]!r}") from None

    def start(self, app: str):
        v = self._req("POST", "/session", {"capabilities": {"alwaysMatch": {"tauri:options": {"application": app}}}}, timeout=120)
        self.sid = v["sessionId"]

    def s(self, path):
        return f"/session/{self.sid}{path}"

    def text(self) -> str:
        return self.js("return document.body.innerText")

    def js(self, script: str, *args):
        return self._req("POST", self.s("/execute/sync"), {"script": script, "args": list(args)})

    def click_button(self, label: str):
        ok = self.js(
            "const want = arguments[0].toLowerCase();"
            "const b = [...document.querySelectorAll('button')].find(b => b.innerText.trim().toLowerCase().includes(want) && !b.disabled);"
            "if (!b) return false; b.click(); return true;", label)
        if not ok:
            raise AssertionError(f"no enabled button labelled {label!r}; page:\n{self.text()}")

    def type_into(self, css: str, value: str):
        el = self._req("POST", self.s("/element"), {"using": "css selector", "value": css})
        eid = next(iter(el.values()))
        self._req("POST", self.s(f"/element/{eid}/value"), {"text": value})

    def shot(self, name: str):
        png = self._req("GET", self.s("/screenshot"))
        (OUT / f"{name}.png").write_bytes(base64.b64decode(png))

    def wait_for(self, needle: str, timeout: float, step: str):
        end = time.time() + timeout
        last = ""
        while time.time() < end:
            try:
                last = self.text()
            except RuntimeError:
                pass
            if needle.lower() in last.lower():
                return last
            time.sleep(2)
        self.shot(f"FAIL-{step}")
        raise AssertionError(f"[{step}] timed out waiting for {needle!r}; page was:\n{last}")

    def quit(self):
        if self.sid:
            try:
                self._req("DELETE", self.s(""), timeout=20)
            except Exception:
                pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=str(ROOT / "src-tauri" / "target" / "debug" / "aipotluck-local-client-gui"))
    ap.add_argument("--keep", action="store_true", help="keep the throwaway HOME for inspection")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    driver = shutil.which("tauri-driver") or str(Path.home() / ".cargo" / "bin" / "tauri-driver")
    if not Path(driver).exists():
        print("tauri-driver not found: cargo install tauri-driver --locked", file=sys.stderr)
        return 2

    home = Path(tempfile.mkdtemp(prefix="aipotluck-e2e-home-"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "DBUS_"))}
    env["HOME"] = str(home)
    procs = []
    if not env.get("DISPLAY"):
        disp = ":97"
        procs.append(subprocess.Popen(["Xvfb", disp, "-screen", "0", "1280x900x24", "-nolisten", "tcp"]))
        env["DISPLAY"] = disp
        time.sleep(1)
    port = free_port()
    procs.append(subprocess.Popen([driver, "--port", str(port), "--native-port", str(free_port())], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    wd = WD(f"http://127.0.0.1:{port}")
    steps = []
    try:
        wd.start(args.app)
        wd.wait_for("Set up this computer", 120, "1-setup-screen"); wd.shot("1-setup"); steps.append("setup screen shown on a fresh machine")

        wd.click_button("Set up")
        t0 = time.time()
        wd.wait_for("Pair with AI Potluck", 1800, "2-install"); wd.shot("2-pair")
        steps.append(f"upstream installer finished via the GUI in {time.time() - t0:.0f}s")
        runtime = json.loads((home / ".config" / "aipotluck" / "runtime.json").read_text())
        assert Path(runtime["llama_cpp"]["server_binary"]).exists(), "installer did not leave a llama-server"
        assert runtime["logged_in"] is False

        wd.click_button("Paste instead")
        wd.type_into("textarea.paste", json.dumps(FAKE_PAIRING))
        wd.shot("3-pasted")
        page = wd.text()
        assert FAKE_PAIRING["tunnelSecret"] not in page, "secret visible on screen"
        wd.click_button("Pair")
        wd.wait_for("Sharing with AI Potluck", 300, "3-pair")
        runtime = json.loads((home / ".config" / "aipotluck" / "runtime.json").read_text())
        assert runtime["logged_in"] is True and runtime["tunnel"]["id"] == FAKE_PAIRING["tunnelId"]
        assert not list((home / ".local" / "share" / "aipotluck" / "gui-runtime").glob(".pairing-*.json")), \
            "pairing temp file was not cleaned up"
        steps.append("paired via upstream `cli login`; temp credentials file removed")

        page = wd.wait_for("Inference server", 60, "4-status")
        end = time.time() + 240
        while time.time() < end and ("Ready" not in page or "Can’t reach" not in page and "Can't reach" not in page):
            time.sleep(3); page = wd.text()
        wd.shot("4-running")
        assert "Ready" in page, f"inference server never reported Ready:\n{page}"
        assert "reach AI Potluck" in page, f"fake tunnel was not reported as unreachable:\n{page}"
        assert FAKE_PAIRING["tunnelSecret"] not in page
        steps.append("status: inference server Ready, fake tunnel honestly reported as not connected")

        wd.click_button("Unpair")
        wd.wait_for("Pair with AI Potluck", 120, "5-unpair"); wd.shot("5-unpaired")
        runtime = json.loads((home / ".config" / "aipotluck" / "runtime.json").read_text())
        assert runtime["logged_in"] is False and "tunnel" not in runtime
        steps.append("unpaired via upstream `cli logout`")
    except Exception as e:
        print("E2E FAILED:", e, file=sys.stderr)
        for s in steps:
            print("  ok:", s, file=sys.stderr)
        return 1
    finally:
        wd.quit()
        for p in reversed(procs):
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        # Nothing the app started may outlive it -- checked after the app is gone, including the
        # GUI-hosted service and the llama-server/newt it supervises. (This check found a real
        # orphaned service the first time it ran.)
        time.sleep(3)
        leftover = subprocess.run(["pgrep", "-af", str(home)], capture_output=True, text=True).stdout.strip()
        if leftover:
            print("E2E FAILED: processes outlived the app:\n" + leftover, file=sys.stderr)
            for line in leftover.splitlines():
                try:
                    os.kill(int(line.split()[0]), signal.SIGTERM)
                except (ValueError, ProcessLookupError):
                    pass
            failed_cleanup = True
        else:
            failed_cleanup = False
        if args.keep:
            print("kept HOME:", home)
        else:
            shutil.rmtree(home, ignore_errors=True)
    if failed_cleanup:
        return 1
    steps.append("nothing the app started outlived it")
    for s in steps:
        print("ok:", s)
    print(f"E2E PASSED -- screenshots in {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
