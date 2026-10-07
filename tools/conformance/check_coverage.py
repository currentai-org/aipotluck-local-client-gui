#!/usr/bin/env python3
"""Compare this project's declared coverage against aipotluck-local-client's real interface surface.

Ported from aipotluck-local-client-android/tools/conformance/check_coverage.py; extended to
normalise the GUI-specific areas extract_surface.py adds (http_routes, api, pins, gui_hooks).

Three questions, in this order, because each one can make the next meaningless:

1. **Is the baseline stale?** Diff a fresh extraction against the committed
   `conformance/upstream-surface.json`. Anything added, removed or changed upstream appears here.
2. **Is every upstream item accounted for?** Every leaf in the normalised surface must be matched
   by an entry in `conformance/coverage.json` -- exactly, or by a group wildcard. An unmatched
   item is an undecided item, and that fails the check.
3. **Is the manifest still honest?** Entries pointing at surface that no longer exists are stale;
   `todo` entries are outstanding work.

Exit codes: 0 clean, 1 drift or undecided items, 2 usage/IO error.

Usage:
    check_coverage.py --surface fresh.json [--update-baseline] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

STATUSES = {"implemented", "partial", "not_applicable", "todo"}

#: A flag is one interface fact, not six. Collapsing its argparse properties into a single
#: signature string means a flag's whole shape is one reviewable leaf, and adding a flag is one
#: added leaf rather than seven.
_FLAG_PROPERTIES = ("choices", "default", "required", "takes_value", "type")


def _flag_signature(info: dict[str, Any]) -> str:
    parts = []
    if info.get("takes_value"):
        parts.append(f"<{info.get('type') or 'str'}>")
    else:
        parts.append("(flag)")
    if info.get("required"):
        parts.append("required")
    if info.get("default") is not None:
        parts.append(f"default={info['default']!r}")
    choices = info.get("choices")
    if choices:
        parts.append("choices=" + "|".join(str(c) for c in choices))
    return " ".join(parts)


def normalize(surface: dict[str, Any]) -> dict[str, Any]:
    """Rewrite the extraction into reviewable leaves.

    Also drops what carries no interface meaning, so "upstream drift" stays a signal someone can
    act on: a reworded `--help` string or a changed file hash is not a reason to touch this
    project, and a check that cries wolf on prose stops being read.
    """
    # `source_repo`/`source_commit` are deliberately absent: they are provenance for the report,
    # not interface surface, and including them would make every upstream commit "drift".
    out: dict[str, Any] = {"schema_version": surface.get("schema_version")}
    # (`parse_errors` is deliberately not carried through: it is a tooling condition handled by the
    # caller before any comparison happens, not something to classify in the manifest.)

    cli = surface.get("cli", {})
    cli_out: dict[str, Any] = {}

    def flags(container: dict[str, Any]) -> dict[str, str]:
        return {name: _flag_signature(info) for name, info in sorted(container.items())}

    if cli.get("shared_flags"):
        cli_out["shared_flags"] = flags(cli["shared_flags"])
    if cli.get("install_flags"):
        cli_out["install_flags"] = flags(cli["install_flags"])
    # install_choice_sets duplicates install_flags' own choices -- dropped as redundant.
    if cli.get("subcommands"):
        cli_out["subcommands"] = {
            name: {
                "flags": flags(info.get("flags", {})),
                "inherits_shared_flags": info.get("inherits_shared_flags"),
            }
            for name, info in sorted(cli["subcommands"].items())
        }
    if cli_out:
        out["cli"] = cli_out

    service = surface.get("service", {})
    out["service"] = {
        # http_paths is not carried: http_routes (per method) supersedes it, and a route listed
        # twice would have to be classified twice.
        "status_keys": sorted(service.get("status_keys", [])),
        "capabilities_keys": sorted(service.get("capabilities_keys", [])),
        "default_port": service.get("default_port"),
        "service_name": service.get("service_name"),
        "default_models_max": service.get("default_models_max"),
        "fingerprint_version": service.get("fingerprint_version"),
        "llama_server_flags": sorted(service.get("llama_server_flags", [])),
        "login_gating": service.get("login_gating"),
        "redaction_marker": service.get("redaction_marker"),
        "runtime_params_router_fields": sorted(service.get("runtime_params_router_fields") or []),
        "runtime_params_preset_keys": sorted((service.get("runtime_params_preset_keys") or {}).keys()),
        "runtime_params_has_reason_map": service.get("runtime_params_has_reason_map"),
    }

    tunnel = surface.get("tunnel", {})
    argv = tunnel.get("argv", [])
    out["tunnel"] = {
        # One leaf for the whole invocation: the argument *order* is part of the interface, and a
        # reordered argv should show as one changed item, not as nine.
        "argv": " ".join(
            element["value"] if element.get("kind") == "literal" else f"<{element.get('source')}>"
            for element in argv
        ),
        "flags": sorted(tunnel.get("flags", [])),
        "health_filename": tunnel.get("health_filename"),
        "health_ok_content": tunnel.get("health_ok_content"),
        "connected_signal": tunnel.get("connected_signal"),
        "error_prefix": tunnel.get("error_prefix"),
        "backoff_schedule": " ".join(str(x) for x in (tunnel.get("backoff_schedule") or [])),
        "stable_uptime_reset_seconds": tunnel.get("stable_uptime_reset_seconds"),
        "poll_interval_seconds": tunnel.get("poll_interval_seconds"),
        "log_tail_bytes": tunnel.get("log_tail_bytes"),
        "uses_health_file_flag": tunnel.get("uses_health_file_flag"),
    }

    out["service"]["http_routes"] = {
        method: sorted(routes) for method, routes in sorted((service.get("http_routes") or {}).items())
    }

    api = surface.get("api", {})
    out["api"] = {
        "error_codes": sorted(api.get("error_codes", [])),
        "job_states": sorted(api.get("job_states", [])),
        "job_keys": sorted(api.get("job_keys", [])),
        "list_models_keys": sorted(api.get("list_models_keys", [])),
    }

    # Pins: the tag is one leaf (a bump is one changed item), each asset key one leaf (a new
    # platform is one added item), and each still-unverified checksum one leaf (filling it in is a
    # removed item -- exactly the event that unblocks pairing on that platform).
    pins = surface.get("pins", {})
    out["pins"] = {}
    for name, pin in sorted(pins.items()):
        if isinstance(pin, dict):
            out["pins"][name] = {
                "tag": pin.get("tag"),
                "assets": sorted(pin.get("assets", [])),
                "unverified_assets": sorted(pin.get("unverified_assets", [])),
            }
        else:
            out["pins"][name] = pin

    out["gui_hooks"] = dict(sorted((surface.get("gui_hooks") or {}).items()))

    out["runtime_config_keys"] = {
        filename: sorted(keys)
        for filename, keys in sorted((surface.get("runtime_config_keys") or {}).items())
    }
    return out


def flatten(surface: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Every leaf keyed by dotted path.

    Lists of scalars become one leaf per element, so a new CLI flag or HTTP path is a new leaf and
    cannot hide inside an otherwise-unchanged list.
    """
    leaves: dict[str, Any] = {}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            if all(not isinstance(item, (dict, list)) for item in node):
                for item in node:
                    walk(item, f"{path}.{item}")
            else:
                for index, item in enumerate(node):
                    walk(item, f"{path}.{index}")
        else:
            leaves[path] = node

    walk(surface, prefix)
    return leaves


# --------------------------------------------------------------------------- manifest


def match_manifest(
    leaves: dict[str, Any], manifest: dict[str, Any]
) -> tuple[dict[str, str], list[str], list[str]]:
    """(classification per leaf, undecided leaves, manifest rules that matched nothing)."""
    rules: dict[str, dict[str, Any]] = manifest.get("surface_review", {})

    classification: dict[str, str] = {}
    used_rules: set[str] = set()
    undecided: list[str] = []

    for key in leaves:
        if key in rules:
            classification[key] = rules[key]["status"]
            used_rules.add(key)
            continue
        candidates = [rule for rule in rules if rule.endswith("*") and key.startswith(rule[:-1])]
        if candidates:
            best = max(candidates, key=len)
            classification[key] = rules[best]["status"]
            used_rules.add(best)
        else:
            undecided.append(key)

    return classification, sorted(undecided), sorted(set(rules) - used_rules)


def note_for(manifest: dict[str, Any], key: str) -> str:
    rules = manifest.get("surface_review", {})
    if key in rules:
        return rules[key].get("note", "")
    candidates = [rule for rule in rules if rule.endswith("*") and key.startswith(rule[:-1])]
    return rules[max(candidates, key=len)].get("note", "") if candidates else ""


def wildcard_absorptions(leaves: dict[str, Any], manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Which leaves each wildcard currently absorbs.

    Printed on a baseline update so a group rule can never silently swallow a newly-added upstream
    feature -- the exact failure a wildcard introduces.
    """
    rules = manifest.get("surface_review", {})
    absorbed: dict[str, list[str]] = {rule: [] for rule in rules if rule.endswith("*")}
    for key in leaves:
        if key in rules:
            continue
        candidates = [rule for rule in absorbed if key.startswith(rule[:-1])]
        if candidates:
            absorbed[max(candidates, key=len)].append(key)
    return {rule: sorted(items) for rule, items in absorbed.items() if items}


# --------------------------------------------------------------------------- diff


def diff(baseline: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    old = flatten(normalize(baseline))
    new = flatten(normalize(fresh))
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(key for key in set(old) & set(new) if old[key] != new[key]),
    }


def _render_diff(drift: dict[str, Any], baseline: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    old = flatten(normalize(baseline))
    new = flatten(normalize(fresh))
    lines: list[str] = []
    for label, keys in (("ADDED upstream", drift["added"]), ("REMOVED upstream", drift["removed"])):
        if keys:
            lines.append(f"  {label} ({len(keys)}):")
            for key in keys:
                lines.append(f"    {'+' if label.startswith('ADDED') else '-'} {key}")
    if drift["changed"]:
        lines.append(f"  CHANGED upstream ({len(drift['changed'])}):")
        for key in drift["changed"]:
            lines.append(f"    ~ {key}\n        was: {old.get(key)}\n        now: {new.get(key)}")
    return lines


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--surface", type=pathlib.Path, required=True, help="freshly extracted surface JSON")
    parser.add_argument("--baseline", type=pathlib.Path, default=pathlib.Path("conformance/upstream-surface.json"))
    parser.add_argument("--manifest", type=pathlib.Path, default=pathlib.Path("conformance/coverage.json"))
    parser.add_argument("--update-baseline", action="store_true", help="replace the baseline with the fresh surface")
    parser.add_argument("--quiet", action="store_true", help="only print problems")
    args = parser.parse_args(argv)

    fresh = json.loads(args.surface.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    # Checked before anything else: an unreadable upstream file produces an empty surface for that
    # area, which would otherwise be reported as "upstream removed 47 items" -- a false alarm that
    # looks exactly like a real one, and the fastest way to teach someone to ignore this tool.
    parse_errors = fresh.get("parse_errors") or {}
    if parse_errors:
        print("COULD NOT READ UPSTREAM -- this is a tooling problem, not drift:", file=sys.stderr)
        for name, reason in sorted(parse_errors.items()):
            print(f"  {name}: {reason}", file=sys.stderr)
        print("\nFix the checkout (or the extractor), then re-run. Nothing was compared.", file=sys.stderr)
        return 2

    bad = sorted({rule.get("status") for rule in manifest.get("surface_review", {}).values()} - STATUSES)
    if bad:
        print(f"coverage.json has unknown statuses: {bad} (allowed: {sorted(STATUSES)})", file=sys.stderr)
        return 2

    baseline_exists = args.baseline.exists()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if baseline_exists else fresh
    drift = diff(baseline, fresh) if baseline_exists else {"added": [], "removed": [], "changed": []}

    leaves = flatten(normalize(fresh))
    classification, undecided, stale = match_manifest(leaves, manifest)

    problems = 0
    out: list[str] = []
    fresh_rev = (fresh.get("source_commit") or "?")[:9]
    base_rev = (baseline.get("source_commit") or "?")[:9]

    if args.update_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        out.append(f"baseline updated -> {args.baseline}")
        out.append(f"  now pinned to {fresh.get('source_repo')} @ {fresh_rev}  {fresh.get('source_subject') or ''}")

    if baseline_exists and any(drift.values()):
        problems += 1
        out.append("")
        out.append(f"UPSTREAM DRIFT ({base_rev} -> {fresh_rev}):")
        out.extend(_render_diff(drift, baseline, fresh))
        out.append("")
        out.append("  For each item: implement it, or record in the manifest why it does not apply.")
        out.append("  Then re-run with --update-baseline to accept the new upstream surface.")

    if undecided:
        problems += 1
        out.append("")
        out.append(f"UNDECIDED SURFACE ITEMS ({len(undecided)}) -- nothing in {args.manifest} covers these:")
        for key in undecided:
            out.append(f"    ? {key}")
        out.append("")
        out.append("  Classify each as implemented / partial / not_applicable / todo, with a note.")
        out.append("  An item nobody decided about is how this project silently falls behind.")

    if stale:
        problems += 1
        out.append("")
        out.append(f"STALE MANIFEST RULES ({len(stale)}) -- matched nothing in the upstream surface:")
        for key in stale:
            out.append(f"    x {key}")
        out.append("  Upstream removed or renamed these. Fix or delete the entries, so the manifest keeps")
        out.append("  meaning what it says.")

    by_status: dict[str, list[str]] = {}
    for key, status in classification.items():
        by_status.setdefault(status, []).append(key)

    if not args.quiet:
        out.insert(0, f"upstream: {fresh.get('source_repo')} @ {fresh_rev}  {fresh.get('source_subject') or ''}")
        out.append("")
        out.append(f"COVERAGE ({len(classification)} surface items, {len(undecided)} undecided):")
        for status in ("implemented", "partial", "not_applicable", "todo"):
            out.append(f"  {status:15} {len(by_status.get(status, [])):3}")

        for status in ("todo", "partial"):
            keys = by_status.get(status, [])
            if not keys:
                continue
            out.append("")
            out.append(f"  {status}:")
            for key in sorted(keys):
                note = note_for(manifest, key)
                out.append(f"    - {key}{f'   [{note}]' if note else ''}")

        absorbed = wildcard_absorptions(leaves, manifest)
        if absorbed:
            out.append("")
            out.append("GROUP RULES (a wildcard also silently covers anything new beneath it):")
            for rule, items in sorted(absorbed.items()):
                out.append(f"  {rule}  -> covers {len(items)} items now")

    out.append("")
    out.append("RESULT: " + ("OK -- no drift, every upstream item classified" if problems == 0
                             else f"{problems} issue(s) need attention"))
    print("\n".join(out))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
