# macOS bring-up: findings in the upstream CLI and llama.cpp

Date: 2026-10-17. Host: Mac mini, Apple M5 Pro (18 cores, 64 GB), macOS 27.0 (26A425),
Command Line Tools for Xcode 27.0.
Upstream CLI pinned at `318da88` (also `origin/main` at the time of testing). llama.cpp `b10989`,
newt `1.18.1`.

How it was run: the GUI's own macOS release bundle (`tools/build.sh --release-target
macos-arm64`), with its bundled Python 3.12.15 and upstream archive unpacked into a scratch
`HOME`. Upstream's entry points were then run exactly as the GUI runs them:
- `python -m aipotluck.installer.install --backend auto --model-hf=…`;
- the launchd agent upstream installs;
- `cli login --credentials-file`, `cli logout`.

The real account was not touched.
Scripts: `build/mac-*.sh`, kept locally and not committed.

## Summary

| Area | Result |
|---|---|
| Installer on macOS (llama.cpp download, model pull, sizing, runtime.json, CLI shim) | **Works** |
| launchd user agent (`~/Library/LaunchAgents/com.aipotluck.aipotluck.plist`) | **Works**, though upstream still labels it "STUB, untested" |
| llama.cpp `b10989` macOS arm64 asset (Metal) | **Works**: Metal used, ~480 tok/s generation on SmolLM2-135M |
| Pairing (`cli login`) on macOS | **Blocked**: `newt_version.json` has placeholder sha256s for darwin (finding 1) |
| Memory-based ctx sizing on macOS | **Degraded**: "could not measure total system memory on this platform" (finding 2) |
| Model loading in the router right after `login` | Fine; the earlier timeout was a test artefact (finding 3) |

## 1. Blocker: pairing fails on every Mac (newt darwin checksums are placeholders)

`newt_version.json` at `318da88` has `"sha256": "UNVERIFIED_DOWNLOAD_AND_COMPUTE_BEFORE_USE"` for
`macos-arm64`, `macos-x64` and `windows-x64`. `newt_fetch.py` refuses such an entry, so on a Mac:

```
$ python -m aipotluck.installer.cli login --credentials-file …
[ERROR] aipotluck.cli: login failed: newt_version.json's 'macos-arm64' entry has never been
downloaded/verified on this platform -- see newt_version.json's own header comment before relying on it.
```

**Impact:** a Mac can install and run the service, but can never be paired with aipotluck.org,
from the CLI or the GUI. The GUI can't work around this without breaking the "never re-implement
the CLI" rule, and it shouldn't.

**Fix (upstream):** fill in the real values. Both were checked two independent ways:
- downloaded on the Mac and hashed with `shasum -a 256`;
- compared with the digests GitHub publishes for the `fosrl/newt` `1.18.1` release assets.

The two matched exactly.

| asset | sha256 |
|---|---|
| `newt_darwin_arm64` | `841c2ef858035a4fb01ffa619e1a56914fa5c3900cf9678e6a9758c9b9449da1` |
| `newt_darwin_amd64` | `9ddc85d3244cce9b96ce52a09e075df887f79343b5200cffb49bf1c459421ecc` |

`newt_darwin_arm64` is a Mach-O arm64 executable, prints `Newt version 1.18.1`, and needs no
quarantine workaround when downloaded by Python (no `com.apple.quarantine` xattr).

**Verified with the fix applied** (the values substituted into the scratch copy only):
- `cli login` fetched and verified newt, wrote the pairing, and restarted the launchd agent;
- `/status` then reported `logged_in: true`, llama-server `healthy: true`, and newt running;
- `cli logout` stopped both;
- unloading the agent left no `llama-server`, `newt` or service process running.

`windows-x64` has the same placeholder and needs the same treatment before Windows can pair.

## 2. Degraded: ctx sizing has no memory budget on macOS

`/status` → `runtime_params.models[…].tuning.ctx_size` on the Mac:

> could not measure total system memory on this platform -- sized to the model's own trained
> context (8192) with no memory-budget check

On a 64 GB Mac with a 135M model this is harmless. On a small Mac (8 GB) with a large model,
it disables the safeguard that keeps the KV cache inside 80% of RAM (CUR-1965). That's the
out-of-memory failure the sizing was built to prevent.

**Fix (upstream):** read total memory on macOS with `sysctl -n hw.memsize` (`diagnostics._total_memory_gb()` reads only `/proc/meminfo`). Without a fix, an oversized model may be held back as
"kept running out of memory" instead of being sized down.

## 3. Not a bug: first request after `login` timed out (artefact of the test setup)

After `cli login`, the first `/v1/chat/completions` request through the service's router got no
response within 120 s. The service's router logged "Loaded 0 cached model presets". The same
binary, preset and cache, started by hand, answered in ~2 s.

Cause: launchd starts the agent with the account's real `HOME` (`/Users/hermes`), not the
scratch `HOME` the test installed into, as confirmed with `ps eww`. So the router looked for the
model in the real account's Hugging Face cache, where there isn't one.

A normal install uses one `HOME` throughout, so this doesn't arise. There's nothing to report
upstream. It does mean macOS tests of the launchd path must use the real account, not a scratch
`HOME`.

## 4. Minor: launchd backend uses deprecated `launchctl load/unload`

`launchd.py` still calls `launchctl load -w` / `unload -w` / `start` / `stop`. These work on
macOS 27, but Apple has deprecated them in favour of `bootstrap` / `bootout` / `kickstart`, and
`load` reports some failures only with exit code 0. Low priority; the code also still describes
itself as "STUB … not tested on real macOS hardware", which can now be updated.

## llama.cpp: no issues

- The `macos-arm64` asset of `b10989` downloads, verifies, and runs with no quarantine prompt.
  It's ad-hoc signed, the same as Homebrew builds.
- Metal is used automatically: `llama-bench` reports backend `MTL,BLAS`. SmolLM2-135M Q4_K_M:
  pp512 ≈ 37,900 tok/s, tg32 ≈ 478 tok/s.
- A direct chat completion with `llama-server` returned a sensible reply at ~404 tok/s.
