#!/usr/bin/env python3
"""Extract the *interface surface* of aipotluck-local-client from its own source.

Ported from aipotluck-local-client-android/tools/conformance/extract_surface.py and extended for
the GUI: per-method HTTP routes (including `_route()`-based ones the original missed), API error
codes and job lifecycle, binary pins, and the upstream internals the GUI calls directly.

Why AST and not the README: prose drifts silently and cannot go red. Every fact in
the emitted JSON is read out of a real declaration in the desktop repo -- an
`add_argument` call, a returned dict literal, an `if self.path == ...` comparison --
so a change that alters behaviour but not the docs is still caught.

This is deliberately conservative: it records what it found and where, and anything
it cannot parse it omits rather than guessing. Items it misses are exactly what the
coverage manifest's `unmatched_surface` check exists to surface.

Usage:
    extract_surface.py <path-to-desktop-checkout> [--out surface.json]
    extract_surface.py <path> --summary          # human-readable overview
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Any

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- helpers


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse(path: pathlib.Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _call_name(node: ast.Call) -> str:
    """`sub.add_parser` -> 'add_parser'; `parser.add_argument` -> 'add_argument'."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _str_arg(node: ast.Call, index: int = 0) -> str | None:
    if len(node.args) > index and isinstance(node.args[index], ast.Constant):
        value = node.args[index].value
        if isinstance(value, str):
            return value
    return None


def _kwarg(node: ast.Call, name: str) -> ast.expr | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _const_str(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _const_int(node: ast.expr | None) -> int | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, int) else None


#: Arithmetic upstream uses to express constants (`_LOG_TAIL_BYTES = 16 * 1024`). Without this the
#: extractor silently reports those as absent, which reads downstream as "upstream has no such
#: constant" -- a false negative that would quietly excuse a real difference.
_BIN_OPS = {
    ast.Mult: lambda a, b: a * b,
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def _number(node: ast.expr | None) -> int | float | None:
    """A numeric literal, or a constant expression built from numeric literals."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _number(node.left), _number(node.right)
        if left is not None and right is not None:
            return _BIN_OPS[type(node.op)](left, right)
    return None


def _literal(node: ast.expr | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return _number(node)


def _dict_keys(node: ast.Dict) -> list[str]:
    keys = []
    for key in node.keys:
        value = _const_str(key)
        if value is not None:
            keys.append(value)
    return keys


def _argv_element(element: ast.expr) -> dict[str, str]:
    """A literal argv token, or the source text of the expression that produces one."""
    if isinstance(element, ast.Constant) and isinstance(element.value, str):
        return {"kind": "literal", "value": element.value}
    try:
        return {"kind": "expression", "source": ast.unparse(element)}
    except Exception:  # pragma: no cover - unparseable is rare, but must not abort extraction
        return {"kind": "expression", "source": "<unknown>"}


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node  # type: ignore[return-value]
    return None


def _module_constants(tree: ast.Module) -> dict[str, Any]:
    """Top-level (and class-level) `NAME = <literal>` declarations."""
    found: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    literal = _literal(value)
                    if literal is not None:
                        found[target.id] = literal
                    elif isinstance(value, ast.Constant):
                        found[target.id] = value.value
    return found


# --------------------------------------------------------------------------- CLI


def _flags_from(parser_body: ast.AST, constants: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Every `add_argument(...)` inside (or reachable from) a parser definition.

    `constants` resolves defaults written as names (`default=DEFAULT_MODEL_HF`), which are common
    and otherwise recorded as None -- a false negative that would make a default look like it had
    been removed or never existed.
    """
    constants = constants or {}
    flags: dict[str, dict[str, Any]] = {}
    for node in ast.walk(parser_body):
        if not isinstance(node, ast.Call) or _call_name(node) != "add_argument":
            continue
        names = [
            a.value
            for a in node.args
            if isinstance(a, ast.Constant) and isinstance(a.value, str)
        ]
        if not names:
            continue
        canonical = next((n for n in names if n.startswith("--")), names[0])
        default_node = _kwarg(node, "default")
        default: Any = _literal(default_node)
        if default is None and isinstance(default_node, ast.Name):
            # `default=DEFAULT_MODEL_HF` -- the value is a module constant, not a literal.
            default = constants.get(default_node.id)

        flags[canonical] = {
            "names": names,
            "takes_value": _const_str(_kwarg(node, "action")) != "store_true",
            "type": getattr(_kwarg(node, "type"), "id", None),
            # The value itself, not repr() of it, so the baseline reads like the source.
            "default": default,
            "help": _const_str(_kwarg(node, "help")),
            "choices": _literal(_kwarg(node, "choices")),
            "required": bool(_literal(_kwarg(node, "required")) or False),
        }
    return flags


def _required_choices(flags: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The closed sets a caller can pass -- the part that breaks callers when it changes."""
    return {
        name: info["choices"]
        for name, info in flags.items()
        if info.get("choices")
    }


def extract_cli(repo: pathlib.Path) -> dict[str, Any]:
    cli_path = repo / "aipotluck" / "installer" / "cli.py"
    install_path = repo / "aipotluck" / "installer" / "install.py"
    out: dict[str, Any] = {"files": {}, "subcommands": {}, "install_flags": {}}

    tree = _parse(cli_path)
    if tree is None:
        return out
    out["files"]["cli.py"] = {"sha256": _sha256(cli_path)}

    # Shared flags live in their own builder and are attached via parents=[common].
    cli_constants = _module_constants(tree)
    common: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_common_args_parser":
            common = _flags_from(node, cli_constants)
            break
    out["shared_flags"] = common

    # `add_parser` returns a parser that is usually bound to a variable, with its own
    # `add_argument` calls made afterwards -- so flags cannot be found by walking the
    # add_parser call itself. Map variable -> subcommand name first, then attribute each
    # add_argument to whichever parser variable it was called on.
    var_to_command: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and _call_name(node.value) == "add_parser"
        ):
            name = _str_arg(node.value)
            if name:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_to_command[target.id] = name

    per_command: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in var_to_command.values()}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "add_argument":
            continue
        owner = node.func.value if isinstance(node.func, ast.Attribute) else None
        command = var_to_command.get(owner.id) if isinstance(owner, ast.Name) else None
        if command:
            per_command[command].update(_flags_from(node, cli_constants))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "add_parser":
            continue
        name = _str_arg(node)
        if not name:
            continue
        parents = _literal(_kwarg(node, "parents")) or []
        # Shared flags are attached via parents=[common]; a subcommand with no variable gets
        # exactly those and nothing else.
        merged = dict(common) if parents else {}
        merged.update(_flags_from(node, cli_constants))
        merged.update(per_command.get(name, {}))
        out["subcommands"][name] = {
            "help": _const_str(_kwarg(node, "help")),
            "inherits_shared_flags": bool(parents),
            "flags": merged,
            "choice_sets": _required_choices(merged),
        }

    install_tree = _parse(install_path)
    if install_tree is not None:
        out["files"]["install.py"] = {"sha256": _sha256(install_path)}
        install_constants = _module_constants(install_tree)
        for node in ast.walk(install_tree):
            if isinstance(node, ast.FunctionDef) and node.name in {"build_arg_parser", "build_parser"}:
                install_flags = _flags_from(node, install_constants)
                try:
                    install_flags.update(
                        _flags_from(
                            next(a for a in ast.walk(node) if isinstance(a, ast.Call) and _call_name(a) == "add_argument_group"),
                            install_constants,
                        )
                    )
                except StopIteration:
                    pass
                out["install_flags"] = install_flags
                out["install_choice_sets"] = _required_choices(install_flags)
                break
    return out


# --------------------------------------------------------------------------- service HTTP


def _is_route_expr(node: ast.expr) -> bool:
    """`self.path`, `self._route()`, or a local `route` variable -- the three ways upstream's
    handler names the request path. The Android port's original only knew `self.path`, which
    silently missed every route added after the handler grew a `_route()` helper (/models, /jobs)."""
    if isinstance(node, ast.Attribute) and node.attr == "path":
        return True
    if isinstance(node, ast.Call) and _call_name(node) == "_route":
        return True
    return isinstance(node, ast.Name) and node.id == "route"


def _route_literals_in(node: ast.AST) -> list[str]:
    """Every path a request path is compared against inside `node`: `== "/x"`, `in ("/x", "/y")`,
    and `.startswith("/x/")` (recorded as `/x/*`)."""
    found: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare) and _is_route_expr(sub.left):
            for op, comparator in zip(sub.ops, sub.comparators):
                if isinstance(op, (ast.NotIn, ast.In)) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                    values = [_const_str(e) for e in comparator.elts]
                else:
                    values = [_const_str(comparator)]
                found.extend(v for v in values if v and v.startswith("/"))
        elif (
            isinstance(sub, ast.Call)
            and _call_name(sub) == "startswith"
            and isinstance(sub.func, ast.Attribute)
            and _is_route_expr(sub.func.value)
        ):
            prefix = _str_arg(sub)
            if prefix and prefix.startswith("/"):
                found.append(prefix + "*")
    return sorted(set(found))


def _compared_path_literals(tree: ast.Module) -> list[str]:
    return _route_literals_in(tree)


def _routes_by_method(tree: ast.Module) -> dict[str, list[str]]:
    """{"GET": [...], "POST": [...], ...} from each `do_<METHOD>` handler."""
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("do_"):
            routes = _route_literals_in(node)
            if routes:
                out[node.name[3:]] = routes
    return out


def _json_keys_returned_to(tree: ast.Module, helper: str) -> list[str]:
    """Keys of a dict literal passed to `helper({...})` anywhere in the module."""
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == helper:
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    keys.extend(_dict_keys(arg))
                elif isinstance(arg, ast.IfExp):
                    # `{...} if cond else None` -- take both branches.
                    for branch in (arg.body, arg.orelse):
                        if isinstance(branch, ast.Dict):
                            keys.extend(_dict_keys(branch))
    return sorted(set(keys))


def extract_service(repo: pathlib.Path) -> dict[str, Any]:
    runner_path = repo / "aipotluck" / "service" / "runner.py"
    diag_path = repo / "aipotluck" / "diagnostics.py"
    out: dict[str, Any] = {"files": {}, "http_paths": [], "status_keys": [], "capabilities_keys": []}

    tree = _parse(runner_path)
    if tree is not None:
        out["files"]["runner.py"] = {"sha256": _sha256(runner_path)}
        out["http_paths"] = _compared_path_literals(tree)
        out["http_routes"] = _routes_by_method(tree)
        out["status_keys"] = _json_keys_returned_to(tree, "_write_json")
        constants = _module_constants(tree)
        out["default_port"] = constants.get("DEFAULT_PORT")
        out["default_models_max"] = constants.get("DEFAULT_MODELS_MAX")
        out["service_name"] = constants.get("SERVICE_NAME")
        out["redaction_marker"] = "<redacted>" if "<redacted>" in runner_path.read_text() else None
        out["llama_server_flags"] = _llama_arg_flags(tree)
        # The check the desktop client itself performs before starting anything.
        source = runner_path.read_text()
        out["login_gating"] = 'get("logged_in")' in source

    diag_tree = _parse(diag_path)
    if diag_tree is not None:
        out["files"]["diagnostics.py"] = {"sha256": _sha256(diag_path)}
        fingerprint = _find_function(diag_tree, "gather_fingerprint")
        if fingerprint is not None:
            for node in ast.walk(fingerprint):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                    out["capabilities_keys"] = sorted(set(_dict_keys(node.value)))
                    break
        diag_source = diag_path.read_text(encoding="utf-8")
        constants = _module_constants(diag_tree)
        out["fingerprint_version"] = constants.get("FINGERPRINT_VERSION")
        # NB: _module_constants already evaluates literals, so these must not be passed through
        # _literal again -- literal_eval expects source or an AST node, and silently returns None
        # for an already-evaluated tuple.
        out["runtime_params_router_fields"] = list(constants.get("_ROUTER_PARAM_FIELDS") or [])
        out["runtime_params_preset_keys"] = constants.get("_PRESET_KEY_TO_FIELD")
        params = _find_function(diag_tree, "runtime_params")
        if params is not None:
            params_source = ast.get_source_segment(diag_source, params) or ""
            out["runtime_params_has_reason_map"] = "read_tuning" in params_source
    return out


def _llama_arg_flags(runner_tree: ast.Module) -> list[str]:
    """Flag names passed to llama-server, from the function that builds its argv."""
    flags: list[str] = []
    for name in ("build_llama_server_args", "build_preset_args"):
        function = _find_function(runner_tree, name)
        if function is None:
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and _call_name(node) == "extend":
                for arg in node.args:
                    if isinstance(arg, ast.List):
                        flags.extend(
                            e.value
                            for e in arg.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.startswith("--")
                        )
            if isinstance(node, ast.List):
                flags.extend(
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.startswith("--")
                )
    return sorted(set(flags))


# --------------------------------------------------------------------------- tunnel


def extract_tunnel(repo: pathlib.Path) -> dict[str, Any]:
    path = repo / "aipotluck" / "service" / "newt_supervisor.py"
    tree = _parse(path)
    if tree is None:
        return {}
    source = path.read_text(encoding="utf-8")
    out: dict[str, Any] = {"files": {"newt_supervisor.py": {"sha256": _sha256(path)}}}

    # The exact argv newt is invoked with. Ordered by source line, and including `cmd += [...]`
    # (the health-file flag is added conditionally), because a flag that only appears on some
    # code paths still has to be accounted for.
    pieces: list[tuple[int, list[dict[str, str]]]] = []
    for node in ast.walk(tree):
        target_name = None
        value = None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
            value = node.value
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.List):
            target_name, value = node.target.id, node.value
        if target_name == "cmd" and value is not None:
            pieces.append((node.lineno, [_argv_element(e) for e in value.elts]))

    argv: list[dict[str, str]] = []
    for _, chunk in sorted(pieces, key=lambda item: item[0]):
        argv.extend(chunk)
    out["argv"] = argv
    out["flags"] = [
        element["value"]
        for element in argv
        if element["kind"] == "literal" and element["value"].startswith("--")
    ]

    constants = _module_constants(tree)
    out["backoff_schedule"] = constants.get("BACKOFF_SCHEDULE")
    out["stable_uptime_reset_seconds"] = constants.get("STABLE_UPTIME_RESET_SECONDS")
    out["poll_interval_seconds"] = constants.get("POLL_INTERVAL_SECONDS")
    out["connected_signal"] = constants.get("_TUNNEL_CONNECTED_SIGNAL")
    out["error_prefix"] = constants.get("_TUNNEL_ERROR_PREFIX")
    out["health_filename"] = constants.get("_HEALTH_FILENAME")
    out["health_ok_content"] = constants.get("_HEALTH_OK_FILE_CONTENT") or constants.get("_HEALTH_FILE_OK_CONTENT")
    out["log_tail_bytes"] = constants.get("_LOG_TAIL_BYTES")
    out["uses_health_file_flag"] = "--health-file" in source
    out["ports_health_file_fd"] = "WG_TUN_FD" in source
    return out


# --------------------------------------------------------------------------- runtime.json


def extract_runtime_config(repo: pathlib.Path) -> dict[str, Any]:
    """Config keys the service reads, gathered from real lookups rather than a doc."""
    keys: dict[str, set[str]] = {}
    for relative in (
        "aipotluck/service/runner.py",
        "aipotluck/service/llama_supervisor.py",
        "aipotluck/service/newt_supervisor.py",
        "aipotluck/installer/cli.py",
        "aipotluck/installer/model_pull.py",
        "aipotluck/installer/install.py",
    ):
        path = repo / relative
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            # runtime_config["x"] / cfg.get("x") / llama_cfg.get("x") / tunnel_cfg["x"]
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                key = _const_str(node.slice)
                if key:
                    keys.setdefault(path.name, set()).add(key)
            elif isinstance(node, ast.Call) and _call_name(node) == "get":
                # The owner may be a bare Name (`llama_cfg`) or an Attribute chain
                # (`self.runner.runtime_config`) -- checking only `.id` silently missed every
                # read in runner.py, including the login gate.
                owner = getattr(node.func, "value", None)
                name = getattr(owner, "id", None) or getattr(owner, "attr", "") or ""
                if name.endswith(("cfg", "config")):
                    key = _str_arg(node)
                    if key:
                        keys.setdefault(path.name, set()).add(key)
    return {name: sorted(values) for name, values in sorted(keys.items())}


# --------------------------------------------------------------------------- driver


#: Files whose contents the extraction depends on. If one of these cannot be parsed, the
#: extraction for that whole area comes back empty -- which is indistinguishable from "upstream
#: deleted it all" unless it is reported, and "upstream deleted everything" is exactly the kind of
#: alarming false signal that teaches people to ignore a check.
_WATCHED_FILES = (
    "aipotluck/installer/cli.py",
    "aipotluck/installer/install.py",
    "aipotluck/service/runner.py",
    "aipotluck/service/newt_supervisor.py",
    "aipotluck/diagnostics.py",
    "aipotluck/service/jobs.py",
    "aipotluck/service/model_ops.py",
    "aipotluck/service/aipotluck_service.py",
    "aipotluck/installer/layout.py",
    "aipotluck/installer/service/base.py",
)


def parse_errors(repo: pathlib.Path) -> dict[str, str]:
    """Any watched file that is missing or unparseable, with the reason."""
    problems: dict[str, str] = {}
    for relative in _WATCHED_FILES:
        path = repo / relative
        if not path.is_file():
            problems[relative] = "missing"
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            problems[relative] = f"SyntaxError at line {error.lineno}: {error.msg}"
        except OSError as error:
            problems[relative] = f"could not read: {error}"
    return problems


def extract_api(repo: pathlib.Path) -> dict[str, Any]:
    """The model/job API a GUI drives: machine-readable error codes and job lifecycle."""
    codes: set[str] = set()
    for path in sorted((repo / "aipotluck" / "service").glob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                value = _const_str(_kwarg(node, "code"))
                if value:
                    codes.add(value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if _const_str(key) == "code" and _const_str(value):
                        codes.add(_const_str(value))
    out: dict[str, Any] = {"error_codes": sorted(codes)}

    jobs = _parse(repo / "aipotluck" / "service" / "jobs.py")
    if jobs is not None:
        constants = _module_constants(jobs)
        out["job_states"] = sorted(
            v for k, v in constants.items() if k.isupper() and isinstance(v, str) and k in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}
        )
        to_dict = _find_function(jobs, "to_dict")
        if to_dict is not None:
            for node in ast.walk(to_dict):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                    out["job_keys"] = sorted(_dict_keys(node.value))

    ops = _parse(repo / "aipotluck" / "service" / "model_ops.py")
    if ops is not None:
        fn = _find_function(ops, "list_models")
        if fn is not None:
            keys: set[str] = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Dict):
                    keys.update(_dict_keys(node))
            out["list_models_keys"] = sorted(keys)
    return out


def extract_pins(repo: pathlib.Path) -> dict[str, Any]:
    """The pinned binaries the GUI ships in lockstep with -- it runs upstream's own fetch code, so
    a bumped tag or a new platform asset is something the GUI must notice, not re-implement."""
    out: dict[str, Any] = {}
    for name in ("llama_version.json", "newt_version.json", "llama_custom_builds.json"):
        path = repo / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        assets = data.get("assets") or {}
        out[name] = {
            "tag": data.get("tag"),
            "assets": sorted(assets),
            "unverified_assets": sorted(
                k for k, v in assets.items() if isinstance(v, dict) and "UNVERIFIED" in str(v.get("sha256", ""))
            ),
        }
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("requires-python"):
                out["requires_python"] = line.split("=", 1)[1].strip().strip('"')
            if line.strip().startswith("dependencies"):
                out["dependencies"] = line.split("=", 1)[1].strip()
    return out


def extract_gui_hooks(repo: pathlib.Path) -> dict[str, Any]:
    """Upstream internals this GUI calls directly (sidecar/gui_probe.py, src-tauri/src/runtime.rs).
    These aren't CLI surface for a person, but a rename here breaks the GUI just as surely."""
    out: dict[str, Any] = {}
    svc = _parse(repo / "aipotluck" / "service" / "aipotluck_service.py")
    if svc is not None:
        out["service_entry_flags"] = sorted(_flags_from(svc, _module_constants(svc)))
    lay = _parse(repo / "aipotluck" / "installer" / "layout.py")
    if lay is not None:
        fields: list[str] = []
        for node in ast.walk(lay):
            if isinstance(node, ast.ClassDef) and node.name == "Layout":
                fields = [s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
        out["layout_fields"] = sorted(fields)
        out["layout_functions"] = sorted(
            n.name for n in lay.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
        )
    base = _parse(repo / "aipotluck" / "installer" / "service" / "base.py")
    if base is not None:
        for node in ast.walk(base):
            if isinstance(node, ast.ClassDef) and node.name == "ServiceState":
                out["service_states"] = sorted(
                    _const_str(s.value) for s in node.body
                    if isinstance(s, ast.Assign) and _const_str(s.value)
                )
        out["has_get_service_manager"] = _find_function(base, "get_service_manager") is not None
    pd = _parse(repo / "aipotluck" / "installer" / "platform_detect.py")
    if pd is not None:
        out["has_detect_os"] = _find_function(pd, "detect_os") is not None
    perf = _parse(repo / "aipotluck" / "installer" / "model_perf.py")
    if perf is not None:
        # How long one model's benchmark may take; the models screen quotes it to the user.
        out["measure_budget_seconds"] = _module_constants(perf).get("PROBE_BUDGET_SECONDS")
    for module in ("install.py", "cli.py"):
        tree = _parse(repo / "aipotluck" / "installer" / module)
        if tree is None:
            continue
        fn = _find_function(tree, "setup_logging")
        fmt = None
        if fn is not None:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and _call_name(node) == "basicConfig":
                    fmt = _const_str(_kwarg(node, "format"))
        out[f"log_format.{module}"] = fmt
    return out


def extract(repo: pathlib.Path) -> dict[str, Any]:
    rev = _git_rev(repo)
    return {
        "api": extract_api(repo),
        "pins": extract_pins(repo),
        "gui_hooks": extract_gui_hooks(repo),
        "schema_version": SCHEMA_VERSION,
        "parse_errors": parse_errors(repo),
        "source_repo": repo.name,
        "source_commit": rev,
        "source_subject": _git_subject(repo),
        "cli": extract_cli(repo),
        "service": extract_service(repo),
        "tunnel": extract_tunnel(repo),
        "runtime_config_keys": extract_runtime_config(repo),
    }


def _git(repo: pathlib.Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_rev(repo: pathlib.Path) -> str | None:
    return _git(repo, "rev-parse", "HEAD")


def _git_subject(repo: pathlib.Path) -> str | None:
    return _git(repo, "log", "-1", "--pretty=%s")


def summarise(surface: dict[str, Any]) -> str:
    cli = surface.get("cli", {})
    service = surface.get("service", {})
    tunnel = surface.get("tunnel", {})
    lines = [
        f"source: {surface.get('source_repo')} @ {(surface.get('source_commit') or '?')[:9]}  {surface.get('source_subject') or ''}",
        "",
        f"subcommands ({len(cli.get('subcommands', {}))}):",
    ]
    for name, info in sorted(cli.get("subcommands", {}).items()):
        flags = sorted(info.get("flags", {}))
        lines.append(f"  {name:8} {'shared+' if info.get('inherits_shared_flags') else '      '}{len(flags):2} flags: {', '.join(flags)}")
    lines.append(f"  shared flags: {', '.join(sorted(cli.get('shared_flags', {})))}")
    lines.append(f"  install flags ({len(cli.get('install_flags', {}))}): {', '.join(sorted(cli.get('install_flags', {})))}")
    lines.append("")
    lines.append(f"service http paths: {', '.join(service.get('http_paths', []))}")
    for method, routes in sorted((service.get("http_routes") or {}).items()):
        lines.append(f"  {method:6} {', '.join(routes)}")
    api = surface.get("api", {})
    lines.append(f"api error codes: {', '.join(api.get('error_codes', []))}")
    lines.append(f"job states: {', '.join(api.get('job_states', []))}")
    for name, pin in sorted((surface.get('pins') or {}).items()):
        if isinstance(pin, dict):
            lines.append(f"pin {name}: tag={pin.get('tag')} assets={len(pin.get('assets', []))} unverified={pin.get('unverified_assets')}")
    lines.append(f"service /status keys: {', '.join(service.get('status_keys', []))}")
    lines.append(f"service default port: {service.get('default_port')}  service name: {service.get('service_name')}")
    lines.append(f"llama-server flags: {', '.join(service.get('llama_server_flags', []))}")
    lines.append(f"login gating present: {service.get('login_gating')}")
    lines.append(f"/capabilities keys: {', '.join(service.get('capabilities_keys', []))}")
    lines.append("")
    rendered = [
        element["value"] if element["kind"] == "literal" else f"<{element['source']}>"
        for element in tunnel.get("argv", [])
    ]
    lines.append(f"newt argv: {' '.join(rendered)}")
    lines.append(f"newt flags: {', '.join(tunnel.get('flags', []))}")
    lines.append(f"newt health file: {tunnel.get('health_filename')} (ok content={tunnel.get('health_ok_content')!r})")
    lines.append(f"newt backoff: {tunnel.get('backoff_schedule')}  stable reset: {tunnel.get('stable_uptime_reset_seconds')}s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", type=pathlib.Path, help="path to an aipotluck-local-client checkout")
    parser.add_argument("--out", type=pathlib.Path, help="write the surface JSON here")
    parser.add_argument("--summary", action="store_true", help="print a human-readable overview")
    args = parser.parse_args(argv)

    if not (args.repo / "aipotluck").is_dir():
        print(f"not an aipotluck-local-client checkout: {args.repo}", file=sys.stderr)
        return 2

    surface = extract(args.repo)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    if args.summary or not args.out:
        print(summarise(surface))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
