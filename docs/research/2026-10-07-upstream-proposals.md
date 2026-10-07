# Upstream proposals from building the models screen (2026-10-07)

**Status (upstream 318da88, same day):** 1 fixed (dcfa88d, delete through a scratch router),
3 done (8e31548, byte progress in the pull job), 4 fixed (f4560eb, the secret goes to newt
through its environment). 2 (the misleading `delete_failed` wording) is still open.

Found while building the GUI's models screen against `currentai-org/aitpotluck-local-client` at
`2ac2591` (also `origin/main` on that date). Per this repo's rules the fixes belong upstream; none
of these has been filed. Each was reproduced on a throwaway install, not a real one.

## 1. `remove` fails for every model that has a preset (bug)

`model_ops.remove` → `delete_cached_model` asks the running router to delete
(`DELETE <router>/models?model=…`). llama-server b10989 refuses for a model defined by
`--models-preset`:

```
HTTP/1.1 500 Internal Server Error
{"error":{"code":500,"message":"model name=bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M is not removable (not from cache)","type":"server_error"}}
```

`pull` (and the service's startup backfill) gives every model a preset, so in practice nothing can
be removed, from the CLI (`aipotluck-local-client remove`) or over HTTP. Upstream's tests mock the
router, so they don't see it.

Repro: install, `pull` any model, start the service logged in so the router runs, then
`curl -XDELETE "localhost:8069/models?model=<urlencoded id>"` → 503 `delete_failed`.

Possible fixes: drop the model's preset section and reload the router before deleting, or ask
llama.cpp for a router delete that also accepts preset-defined models that live in the cache.

## 2. `delete_failed` says the service wasn't reachable when it was (message)

The 503 above reads "Could not remove it -- the service wasn't reachable", but the router answered,
with a 500 and a reason. `delete_cached_model` treats `HTTPError` (a subclass of `URLError`) as
unreachable. Passing the router's own message through would make the failure self-explanatory.

## 3. Byte-level progress for a pull's download (feature)

A pull job reports steps (`downloading …`, `sizing …`, `screening …`, `measuring …`) but nothing
during the download itself, which is the long part for a real model. The GUI shows the step, an
elapsed clock and the expected size (from `model_preflight`), but can't show a percentage without
re-implementing llama.cpp's cache-path resolution. A periodic progress entry with bytes received
(and total, when known) would let every client show a real progress bar.

## 4. The tunnel secret is on newt's command line (security)

`newt_supervisor` starts newt with `--secret <secret>`, so any local user can read it with `ps`.
This repo keeps the secret off argv on its side (pairing goes through a 0600 file). If newt can read
the secret from a file or the environment, the supervisor should pass it that way.
