#!/usr/bin/env python3
"""Which AI Potluck server one-click pairing talks to, decided by upstream's own code.

    python gui_server.py                       -> the server `cli login` would use with no flag
    python gui_server.py --server-url URL      -> URL as `cli login --server-url URL` would use it

Prints one JSON object: {"default", "effective", "from_env", "error"}. `effective` is upstream's
pairing.resolve_server_url() result (normalized: scheme://host[:port][/path], no trailing slash),
or null with `error` set to upstream's own message when it refuses the value (not http(s), or plain
http to anything but this machine). Never contacts the server. Run with cwd = upstream checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from aipotluck.installer import pairing  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", default=None)
    args = parser.parse_args()
    out = {
        "default": pairing.DEFAULT_SERVER_URL,
        "from_env": os.environ.get(pairing.SERVER_URL_ENV) or None,
        "effective": None,
        "error": None,
    }
    try:
        out["effective"] = pairing.resolve_server_url(args.server_url or None)
    except pairing.PairingError as exc:
        out["error"] = str(exc)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
