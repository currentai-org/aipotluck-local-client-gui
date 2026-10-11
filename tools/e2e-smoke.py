#!/usr/bin/env python3
"""End-to-end smoke test: drive the REAL app through the whole user flow on a throwaway HOME.

    tools/e2e-smoke.py [--app PATH] [--keep] [--visible] [--default-model] [--skip-models]

What it does, through the actual window (WebDriver via tauri-driver -> WebKitWebDriver):
  1. fresh HOME -> app unpacks its runtime -> "Set up this computer", listing client, llama.cpp,
     newt and the starter model, each with a size, and a total
  2. Customize -> a malformed model id is refused and the page stays open -> a small real model is
     saved -> the list names it and re-sizes it (skipped with --default-model)
  3. click Set up -> upstream's real installer runs (real llama.cpp + model download) and pulls
     exactly the model the list showed
  4. pair screen -> "Paste instead" -> type a pairing JSON -> Pair -> upstream's real `cli login`
     (real newt download, checksum-verified against upstream's pin)
  5. running screen: service + inference server healthy; the tunnel row must report the fake
     endpoint as NOT connected (proves the status screen reads tunnel_connected, not `running`)
  6. models: the installed model is listed; a malformed Add is refused; a second small real model
     is added (progress panel shown while it downloads and measures); Benchmark scores both; one is
     deleted through its confirm row (skipped with --skip-models)
  7. Unpair -> back to the pair screen, runtime.json logged out
Screenshots of every step go to build/e2e/.

The window lives on a private Xvfb display, never the desktop, even when DISPLAY is set (a
Wayland session sets it for XWayland); --visible uses $DISPLAY instead, to watch it run.

Needs: Xvfb, tauri-driver (`cargo install tauri-driver --locked`),
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
# Small (~105 MB), so the customized path is also the fast one. Not upstream's default model, so a
# Set up that ignored Customize would pull the wrong one and fail the check below.
CUSTOM_MODEL = "bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M"
# Added from the models screen: the same small model at another quant (~145 MB).
SECOND_MODEL = "bartowski/SmolLM2-135M-Instruct-GGUF:Q8_0"
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

    def click_css(self, css: str):
        ok = self.js("const e = document.querySelector(arguments[0]); if (!e || e.disabled) return false; e.click(); return true;", css)
        if not ok:
            raise AssertionError(f"nothing enabled matches {css!r}; page:\n{self.text()}")

    def type_into(self, css: str, value: str, clear: bool = False):
        el = self._req("POST", self.s("/element"), {"using": "css selector", "value": css})
        eid = next(iter(el.values()))
        if clear:
            self._req("POST", self.s(f"/element/{eid}/clear"), {})
        self._req("POST", self.s(f"/element/{eid}/value"), {"text": value})

    def shot(self, name: str):
        png = self._req("GET", self.s("/screenshot"))
        (OUT / f"{name}.png").write_bytes(base64.b64decode(png))

    def wait_for(self, needle: str, timeout: float, step: str, absent: str | None = None):
        """Wait until the page shows `needle` (and, if given, no longer shows `absent`)."""
        end = time.time() + timeout
        last = ""
        while time.time() < end:
            try:
                last = self.text()
            except RuntimeError:
                pass
            if needle.lower() in last.lower() and not (absent and absent.lower() in last.lower()):
                return last
            time.sleep(1)
        self.shot(f"FAIL-{step}")
        raise AssertionError(f"[{step}] timed out waiting for {needle!r}; page was:\n{last}")

    def quit(self):
        if self.sid:
            try:
                self._req("DELETE", self.s(""), timeout=20)
            except Exception:
                pass


def page_model_default(home: Path) -> str:
    """The model Set up installed when Customize was skipped: the one upstream sized."""
    presets = (home / ".config" / "aipotluck" / "llama_presets.ini").read_text()
    return next(line.strip("[]\n") for line in presets.splitlines() if line.startswith("["))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=str(ROOT / "src-tauri" / "target" / "debug" / "aipotluck-local-client-gui"))
    ap.add_argument("--keep", action="store_true", help="keep the throwaway HOME for inspection")
    ap.add_argument("--visible", action="store_true", help="use $DISPLAY instead of a private Xvfb")
    ap.add_argument("--default-model", action="store_true", help="skip Customize; install upstream's default model")
    ap.add_argument("--skip-models", action="store_true", help="skip the models screen (add, benchmark, delete)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    driver = shutil.which("tauri-driver") or str(Path.home() / ".cargo" / "bin" / "tauri-driver")
    if not Path(driver).exists():
        print("tauri-driver not found: cargo install tauri-driver --locked", file=sys.stderr)
        return 2

    home = Path(tempfile.mkdtemp(prefix="aipotluck-e2e-home-"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "DBUS_"))}
    env["HOME"] = str(home)
    # Never the real ports: on a machine that is already set up, 8069/8080 are its real service and
    # llama-server, and this test pairs, unpairs and (in places) deletes. The app honours these
    # test-only variables (src-tauri/src/service.rs TEST_PORT_ENV).
    env["AIPOTLUCK_GUI_TEST_SERVICE_PORT"] = str(free_port())
    env["AIPOTLUCK_GUI_TEST_LLAMA_PORT"] = str(free_port())
    env.pop("WAYLAND_DISPLAY", None)  # the app must come up on the X display chosen below
    procs = []
    if args.visible:
        if not env.get("DISPLAY"):
            print("--visible needs DISPLAY", file=sys.stderr)
            return 2
    else:
        # -displayfd: Xvfb picks a free display number itself and writes it to us.
        rfd, wfd = os.pipe()
        procs.append(subprocess.Popen(
            ["Xvfb", "-displayfd", str(wfd), "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
            pass_fds=(wfd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        os.close(wfd)
        with os.fdopen(rfd) as r:
            number = r.readline().strip()
        if not number:
            print("Xvfb did not start", file=sys.stderr)
            return 2
        env["DISPLAY"] = f":{number}"
    port = free_port()
    procs.append(subprocess.Popen([driver, "--port", str(port), "--native-port", str(free_port())], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    wd = WD(f"http://127.0.0.1:{port}")
    steps = []
    known = []  # upstream outcomes the GUI correctly surfaced (e.g. a busy machine); reported, not failed
    try:
        wd.start(args.app)
        wd.wait_for("Set up this computer", 120, "1-setup-screen")
        page = wd.wait_for("Total", 120, "1-plan", absent="Checking")
        wd.shot("1-setup")
        for part in ("Client", "llama.cpp", "newt", "Model (starter)"):
            assert part in page, f"plan does not list {part!r}:\n{page}"
        lines = page.splitlines()
        unsized = [lines[i - 1] for i, line in enumerate(lines) if line.strip() == "—" and i]
        assert not unsized, (
            f"no size for {unsized} -- the app is showing it as unknown, which can also mean GitHub or "
            f"Hugging Face failed the lookup just now (see build/e2e/1-setup.png):\n{page}")
        steps.append("setup screen lists client, llama.cpp, newt and the starter model, each sized")

        model = None
        if not args.default_model:
            wd.click_button("Customize")
            wd.wait_for("Save changes", 30, "2-settings")
            wd.type_into("#model-hf", "not a model")
            wd.click_button("Save changes")
            page = wd.wait_for("isn’t a Hugging Face model id", 10, "2-invalid")
            assert "Save changes" in page or "SAVE CHANGES" in page, "settings page closed on a bad id"
            wd.shot("2-invalid")
            wd.type_into("#model-hf", CUSTOM_MODEL, clear=True)
            wd.click_button("Save changes")
            page = wd.wait_for(CUSTOM_MODEL, 30, "2-custom", absent="Checking")
            wd.shot("2-custom")
            assert "Model (starter)" not in page, f"customized model still labelled as the starter:\n{page}"
            row = page.split(CUSTOM_MODEL)[0].splitlines()[-1]
            assert "~" in row and "MB" in row.upper(), f"customized model was not sized:\n{page}"
            model = CUSTOM_MODEL
            steps.append(f"Customize refused a malformed id, then sized {CUSTOM_MODEL} ({row.split()[-2]} MB)")

        wd.click_button("Set up")
        t0 = time.time()
        wd.wait_for("Pair with AI Potluck", 1800, "3-install"); wd.shot("3-pair")
        steps.append(f"upstream installer finished via the GUI in {time.time() - t0:.0f}s")
        runtime = json.loads((home / ".config" / "aipotluck" / "runtime.json").read_text())
        assert Path(runtime["llama_cpp"]["server_binary"]).exists(), "installer did not leave a llama-server"
        assert runtime["logged_in"] is False
        if model:
            presets = (home / ".config" / "aipotluck" / "llama_presets.ini").read_text()
            assert f"[{model}]" in presets, f"installer did not size the customized model:\n{presets}"
            cached = sorted(p.name for p in (home / ".cache" / "huggingface" / "hub").glob("models--*"))
            repo = model.split(":")[0].replace("/", "--")
            assert cached == [f"models--{repo}"], f"installer pulled {cached}, not only {model}"
            steps.append(f"upstream pulled and sized exactly the customized model, and nothing else")

        wd.click_button("Paste instead")
        wd.type_into("textarea.paste", json.dumps(FAKE_PAIRING))
        wd.shot("4-pasted")
        page = wd.text()
        assert FAKE_PAIRING["tunnelSecret"] not in page, "secret visible on screen"
        wd.click_button("Pair")
        wd.wait_for("Sharing with AI Potluck", 300, "4-pair")
        runtime = json.loads((home / ".config" / "aipotluck" / "runtime.json").read_text())
        assert runtime["logged_in"] is True and runtime["tunnel"]["id"] == FAKE_PAIRING["tunnelId"]
        assert not list((home / ".local" / "share" / "aipotluck" / "gui-runtime").glob(".pairing-*.json")), \
            "pairing temp file was not cleaned up"
        steps.append("paired via upstream `cli login`; temp credentials file removed")

        page = wd.wait_for("Inference server", 60, "5-status")
        end = time.time() + 240
        while time.time() < end and ("Ready" not in page or "Can’t reach" not in page and "Can't reach" not in page):
            time.sleep(3); page = wd.text()
        wd.shot("5-running")
        assert "Running while this window is open" in page, (
            f"the app is not talking to the service it hosts on the test port -- is something else "
            f"answering there?\n{page}")
        assert "Ready" in page, f"inference server never reported Ready:\n{page}"
        assert "reach AI Potluck" in page, f"fake tunnel was not reported as unreachable:\n{page}"
        assert FAKE_PAIRING["tunnelSecret"] not in page
        steps.append("status: inference server Ready, fake tunnel honestly reported as not connected")

        if not args.skip_models:
            installed = model or page_model_default(home)
            repo = installed.split("/", 1)[1].split(":")[0]
            page = wd.wait_for(repo, 60, "6-models-list")
            assert "1 installed" in page.lower() or "1 INSTALLED" in page, f"model count missing:\n{page}"
            steps.append(f"models screen lists {installed}")

            wd.type_into("#add-model", "not a model")
            wd.click_button("Add")
            wd.wait_for("isn’t a Hugging Face model id", 10, "6-add-invalid")
            wd.type_into("#add-model", SECOND_MODEL, clear=True)
            wd.click_button("Add")
            page = wd.wait_for("Adding SmolLM2", 60, "6-add-started")
            assert "then a moment to size it" in page, f"no time hint while adding:\n{page}"
            wd.wait_for("MB download", 30, "6-add-size")  # the size, from upstream's own preflight
            time.sleep(2); wd.shot("6-adding")
            t0 = time.time()
            page = wd.wait_for("Added SmolLM2", 900, "6-add-done", absent="Adding SmolLM2")
            page = wd.wait_for("2 installed", 30, "6-add-listed")
            wd.shot("6-added")
            steps.append(f"added {SECOND_MODEL} through POST /models in {time.time() - t0:.0f}s, with progress shown")

            wd.click_button("Benchmark")
            page = wd.wait_for("Benchmarking every model", 30, "6-bench-started")
            assert "up to about 6 min for all 2" in page, f"no time hint while benchmarking:\n{page}"
            time.sleep(3); wd.shot("6-benchmarking")
            t0 = time.time()
            end = time.time() + 900
            while time.time() < end:
                page = wd.text()
                if "Benchmarking every model" not in page and ("Benchmark finished" in page or "Measured " in page):
                    break
                time.sleep(2)
            wd.shot("6-benchmarked")
            if "Benchmark finished" in page:
                assert "Not measured yet" not in page, f"a model is still unmeasured after the benchmark:\n{page}"
                steps.append(f"benchmarked both through POST /models/benchmark in {time.time() - t0:.0f}s; both scored")
            else:
                # Upstream declines to measure a busy machine rather than record a wrong score (on a
                # dev laptop, the real install's llama-server is often why). What the GUI owes the
                # user then is upstream's reason, on screen.
                assert "Measured " in page and ":" in page.split("Measured ", 1)[1], f"no outcome or reason shown:\n{page}"
                reason = page.split("Measured ", 1)[1].splitlines()[0]
                known.append(f"benchmark ran but upstream declined to measure: Measured {reason}")

            wd.click_css(f'button[aria-label="Remove {SECOND_MODEL}"]')
            wd.wait_for("and its downloaded weights", 10, "6-confirm"); wd.shot("6-confirm-delete")
            wd.click_button("Delete")
            end = time.time() + 60
            while time.time() < end:
                page = wd.text()
                if "1 INSTALLED" in page.upper() or "COULD NOT REMOVE IT" in page.upper():
                    break
                time.sleep(1)
            wd.shot("6-after-delete")
            # Check the model LIST, not the whole page: the success notice itself reads "Removed
            # ...Q8_0.", so a page-wide "Q8_0 not in page" fails exactly when the delete worked.
            listed = wd.js("return [...document.querySelectorAll('.model .model-name')].map(e => e.innerText).join('\\n')")
            assert "1 installed" in page.lower() and "Q8_0" not in listed, (
                f"deleted model still listed:\nlist: {listed!r}\n{page}")
            steps.append(f"deleted {SECOND_MODEL} through DELETE /models after confirming")

        wd.click_button("Unpair")
        wd.wait_for("Pair with AI Potluck", 120, "7-unpair"); wd.shot("7-unpaired")
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
        # Shutdown takes a moment (the service stops newt and llama-server cleanly), so give it up to
        # 30s; anything still there after that has really outlived the app.
        for _ in range(30):
            time.sleep(1)
            leftover = subprocess.run(["pgrep", "-af", str(home)], capture_output=True, text=True).stdout.strip()
            if not leftover:
                break
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
    for k in known:
        print("NOTE:", k)
    print(f"E2E PASSED -- screenshots in {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
