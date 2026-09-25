"""Non-interactive command-line interface for scripting and AI agents.

Every subcommand prints a human-readable table by default, or a single JSON document on stdout
with `--json`. Progress and child-process output always go to stderr, so `--json` stdout stays
machine-parseable. Commands that change the system (upgrade, install, sync) only print the exact
command they would run unless `--yes` is passed.

Exit codes: 0 success, 1 a manager or command failed, 2 usage error (unknown manager, bad args).
"""

import argparse
import asyncio
import json
import subprocess
import sys
from typing import Any

from app.core.manager import PackageManager, describe_error, discover_managers, get_all_managers

VERSION = "1.0.0"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

COMMANDS = (
    "managers", "outdated", "installed", "search", "audit", "repos",
    "upgrade", "install", "sync", "history", "ignore", "catalog",
)


class UsageError(Exception):
    """Raised for bad user input that should exit with EXIT_USAGE."""


# --- Output helpers ---------------------------------------------------------------------------

def _emit(args: argparse.Namespace, payload: Any, human: str) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(human)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _cell(value: Any, max_width: int = 70) -> str:
    text = str(value)
    return text if len(text) <= max_width else text[: max_width - 1] + "…"


def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Plain aligned table for human output; --json keeps full, untruncated values."""
    if not rows:
        return "(none)"
    cells = [{c: _cell(r.get(c, "")) for c in columns} for r in rows]
    widths = {c: max(len(c), *(len(r[c]) for r in cells)) for c in columns}
    lines = ["  ".join(c.upper().ljust(widths[c]) for c in columns).rstrip()]
    for r in cells:
        lines.append("  ".join(r[c].ljust(widths[c]) for c in columns).rstrip())
    return "\n".join(lines)


# --- Manager selection ------------------------------------------------------------------------

def _select_managers(names: list[str] | None, available_only: bool = True) -> list[PackageManager]:
    """Resolve --manager values (case-insensitive) against discovered drivers.

    With no names, returns every available manager. An unknown or unavailable name is a usage
    error rather than a silent skip, so a typo can't masquerade as "no updates".
    """
    pool = discover_managers() if available_only else get_all_managers()
    if not names:
        return pool
    by_name = {m.name.lower(): m for m in pool}
    selected = []
    for name in names:
        mgr = by_name.get(name.lower())
        if mgr is None:
            known = sorted(m.name for m in get_all_managers())
            state = "not installed on this system" if name.lower() in {k.lower() for k in known} else "unknown"
            raise UsageError(f"Manager '{name}' is {state}. Known managers: {', '.join(known)}")
        selected.append(mgr)
    return selected


def _single_manager(name: str) -> PackageManager:
    return _select_managers([name])[0]


async def _gather_per_manager(managers: list[PackageManager], method: str, *call_args) -> dict[str, dict]:
    """Run one async driver method across managers concurrently, capturing per-manager errors."""

    async def run_one(mgr: PackageManager) -> tuple[str, dict]:
        try:
            result = await getattr(mgr, method)(*call_args)
            return mgr.name, {"ok": True, "result": result}
        except NotImplementedError as e:
            return mgr.name, {"ok": False, "unsupported": True, "error": describe_error(e)}
        except Exception as e:
            return mgr.name, {"ok": False, "error": describe_error(e)}

    pairs = await asyncio.gather(*(run_one(m) for m in managers))
    return dict(pairs)


# --- Command execution ------------------------------------------------------------------------

def _run_command(cmd: list[str], args: argparse.Namespace) -> int:
    """Execute a driver-built argument list (never through a shell) and return its exit code.

    In --json mode the child's stdout is redirected to stderr so it can't corrupt the JSON
    document printed on stdout.
    """
    _log(f"$ {' '.join(cmd)}")
    if cmd and cmd[0] == "pkexec" and not sys.stdin.isatty():
        _log("warning: pkexec needs a polkit agent or a TTY; without one this will fail. "
             "Run the command from an interactive terminal instead.")
    try:
        proc = subprocess.run(cmd, stdout=sys.stderr if args.json else None, check=False)
    except FileNotFoundError as e:
        _log(f"error: {describe_error(e)}")
        return 127
    return proc.returncode


def _plan_or_execute(args: argparse.Namespace, steps: list[dict[str, Any]], record: bool = False) -> int:
    """Print the planned commands, and run them only when --yes was given."""
    if not steps:
        _emit(args, {"executed": False, "steps": []}, "Nothing to do.")
        return EXIT_OK

    if not args.yes:
        human = "Would run (pass --yes to execute):\n" + "\n".join(
            f"  [{s['manager']}] {' '.join(s['command'])}" for s in steps
        )
        _emit(args, {"executed": False, "steps": steps}, human)
        return EXIT_OK

    failed = False
    for step in steps:
        code = _run_command(step["command"], args)
        step["returncode"] = code
        step["success"] = code == 0
        failed |= code != 0
        if record:
            from app.core.history_store import record_upgrade
            record_upgrade(step["manager"], step.get("packages", []), code == 0)

    human = "\n".join(
        f"{'ok  ' if s['success'] else 'FAIL'} [{s['manager']}] exit {s['returncode']}" for s in steps
    )
    _emit(args, {"executed": True, "steps": steps}, human)
    return EXIT_FAILED if failed else EXIT_OK


# --- Subcommands ------------------------------------------------------------------------------

def cmd_managers(args: argparse.Namespace) -> int:
    managers = get_all_managers() if args.all else discover_managers()
    rows = [
        {
            "name": m.name,
            "category": m.category,
            "available": m.is_available(),
            "supports_repos": m.supports_repos,
        }
        for m in managers
    ]
    _emit(args, rows, _table(rows, ["name", "category", "available", "supports_repos"]))
    return EXIT_OK


async def _scan_outdated(managers: list[PackageManager], include_ignored: bool) -> tuple[dict, list[dict]]:
    from app.core.ignore_store import IgnoreStore

    store = IgnoreStore()
    results = await _gather_per_manager(managers, "check_updates")
    for name, res in results.items():
        if not res["ok"]:
            continue
        updates = []
        for pkg in res["result"]:
            pkg = dict(pkg)
            pkg["ignored"] = store.is_ignored(name, pkg.get("name", ""))
            if include_ignored or not pkg["ignored"]:
                updates.append(pkg)
        res["result"] = updates
    rows = [
        {"manager": name, **pkg}
        for name, res in results.items() if res["ok"]
        for pkg in res["result"]
    ]
    return results, rows


def _errors_text(results: dict[str, dict]) -> str:
    lines = [f"! {name}: {res['error']}" for name, res in results.items() if not res["ok"]]
    return ("\n" + "\n".join(lines)) if lines else ""


def cmd_outdated(args: argparse.Namespace) -> int:
    managers = _select_managers(args.manager)
    results, rows = asyncio.run(_scan_outdated(managers, args.include_ignored))
    payload = {
        "updates": rows,
        "managers": {
            n: ({"ok": True, "count": len(r["result"])} if r["ok"] else {"ok": False, "error": r["error"]})
            for n, r in results.items()
        },
    }
    columns = ["manager", "name", "current", "new"] + (["ignored"] if args.include_ignored else [])
    _emit(args, payload, _table(rows, columns) + _errors_text(results))
    return EXIT_FAILED if any(not r["ok"] for r in results.values()) else EXIT_OK


def cmd_installed(args: argparse.Namespace) -> int:
    managers = _select_managers(args.manager)
    results = asyncio.run(_gather_per_manager(managers, "list_installed"))
    payload = {n: (r["result"] if r["ok"] else {"error": r["error"]}) for n, r in results.items()}
    rows = [{"manager": n, "name": p} for n, r in results.items() if r["ok"] for p in r["result"]]
    _emit(args, payload, _table(rows, ["manager", "name"]) + _errors_text(results))
    return EXIT_FAILED if any(not r["ok"] for r in results.values()) else EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    managers = _select_managers(args.manager)
    results = asyncio.run(_gather_per_manager(managers, "search_packages", args.query))
    rows = []
    for name, res in results.items():
        if res["ok"]:
            rows.extend({"manager": name, **pkg} for pkg in res["result"][: args.limit])
    # Managers with no search support are expected, not failures.
    errors = {n: r for n, r in results.items() if not r["ok"] and not r.get("unsupported")}
    _emit(
        args,
        {"results": rows, "errors": {n: r["error"] for n, r in errors.items()}},
        _table(rows, ["manager", "id", "version", "description"]) + _errors_text(errors),
    )
    return EXIT_FAILED if errors else EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    managers = _select_managers(args.manager)
    results = asyncio.run(_gather_per_manager(managers, "check_vulnerabilities"))
    rows = [{"manager": n, **v} for n, r in results.items() if r["ok"] for v in r["result"]]
    _emit(args, rows, _table(rows, ["manager", "name", "severity", "advisory"]) + _errors_text(results))
    return EXIT_FAILED if any(not r["ok"] for r in results.values()) else EXIT_OK


def cmd_repos(args: argparse.Namespace) -> int:
    managers = [m for m in _select_managers(args.manager) if m.supports_repos]
    results = asyncio.run(_gather_per_manager(managers, "list_repos"))
    rows = [{"manager": n, **repo} for n, r in results.items() if r["ok"] for repo in r["result"]]
    _emit(args, rows, _table(rows, ["manager", "id", "enabled", "name", "url"]) + _errors_text(results))
    return EXIT_FAILED if any(not r["ok"] for r in results.values()) else EXIT_OK


def cmd_upgrade(args: argparse.Namespace) -> int:
    if args.packages and len(args.manager or []) != 1:
        raise UsageError("Naming specific packages requires exactly one --manager.")
    managers = _select_managers(args.manager)

    if args.packages:
        targets = {managers[0].name: list(args.packages)}
        scan_failed = False
    else:
        # Scan first so the upgrade targets exactly what `outdated` reports (minus ignored
        # packages), the same way the GUI's batch upgrade passes its selected packages.
        results, rows = asyncio.run(_scan_outdated(managers, include_ignored=False))
        scan_failed = any(not r["ok"] for r in results.values())
        for name, res in results.items():
            if not res["ok"]:
                _log(f"! {name}: skipped, update check failed: {res['error']}")
        targets = {}
        for row in rows:
            targets.setdefault(row["manager"], []).append(row["name"])

    by_name = {m.name: m for m in managers}
    steps = [
        {"manager": name, "packages": pkgs, "command": by_name[name].get_upgrade_command(pkgs)}
        for name, pkgs in targets.items()
    ]
    code = _plan_or_execute(args, steps, record=True)
    return EXIT_FAILED if scan_failed else code


def cmd_install(args: argparse.Namespace) -> int:
    mgr = _single_manager(args.manager)
    steps = [
        {"manager": mgr.name, "packages": [pkg], "command": mgr.get_install_command(pkg)}
        for pkg in args.packages
    ]
    return _plan_or_execute(args, steps)


def cmd_sync(args: argparse.Namespace) -> int:
    steps = []
    for mgr in _select_managers(args.manager):
        cmd = mgr.get_sync_command()
        if cmd:
            steps.append({"manager": mgr.name, "command": cmd})
    return _plan_or_execute(args, steps)


def cmd_history(args: argparse.Namespace) -> int:
    from datetime import datetime
    from app.core.history_store import load_history

    records = load_history(limit=args.limit)
    rows = [
        {
            "time": datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M"),
            "manager": r.get("manager", ""),
            "success": r.get("success"),
            "packages": ", ".join(r.get("packages") or []) or "(all)",
        }
        for r in records
    ]
    _emit(args, records, _table(rows, ["time", "manager", "success", "packages"]))
    return EXIT_OK


def cmd_ignore(args: argparse.Namespace) -> int:
    from app.core.ignore_store import IgnoreStore

    store = IgnoreStore()
    if args.action in ("add", "remove"):
        if not args.manager or not args.package:
            raise UsageError(f"'ignore {args.action}' needs a manager and a package.")
        # Store the driver's canonical name so the GUI's lookups match.
        name = _select_managers([args.manager], available_only=False)[0].name
        (store.add if args.action == "add" else store.remove)(name, args.package)
    rows = [{"manager": m, "package": p} for m, p in store.all_entries()]
    _emit(args, rows, _table(rows, ["manager", "package"]))
    return EXIT_OK


def cmd_catalog(args: argparse.Namespace) -> int:
    from app.core.catalog import load_catalog

    rows = [
        {
            "id": e.id,
            "name": e.name,
            "category": e.category,
            "installed": e.installed,
            "has_driver": e.has_driver,
            "self_install": e.get_self_install_command(),
        }
        for e in load_catalog()
    ]
    human_rows = [{**r, "self_install": " ".join(r["self_install"] or [])} for r in rows]
    _emit(args, rows, _table(human_rows, ["id", "category", "installed", "has_driver", "self_install"]))
    return EXIT_OK


# --- Parser -----------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # --json is accepted before or after the subcommand. SUPPRESS on the subparser copy keeps
    # an omitted sub-level flag from overwriting a root-level `polyget --json <cmd>`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="print one JSON document on stdout")

    parser = argparse.ArgumentParser(
        prog="polyget",
        description="Unified package management across every installed backend. "
                    "Run with no arguments for the GUI, or --tui for the terminal UI.",
        epilog="Exit codes: 0 ok, 1 a manager/command failed, 2 usage error.",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON document on stdout")
    parser.add_argument("--version", action="version", version=f"polyget {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str, func, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text, parents=[common])
        p.set_defaults(func=func)
        return p

    def manager_filter(p: argparse.ArgumentParser) -> None:
        p.add_argument("-m", "--manager", action="append",
                       help="limit to this manager (repeatable; case-insensitive)")

    def confirm(p: argparse.ArgumentParser) -> None:
        p.add_argument("-y", "--yes", action="store_true",
                       help="actually run the commands (default: print them only)")

    p = add("managers", cmd_managers, "list package managers detected on this system")
    p.add_argument("--all", action="store_true", help="include drivers whose binary is missing")

    p = add("outdated", cmd_outdated, "list available updates across managers")
    manager_filter(p)
    p.add_argument("--include-ignored", action="store_true", help="also show ignored packages")

    p = add("installed", cmd_installed, "list installed packages")
    manager_filter(p)

    p = add("search", cmd_search, "search package sources")
    p.add_argument("query")
    manager_filter(p)
    p.add_argument("--limit", type=int, default=20, help="max results per manager (default 20)")

    p = add("audit", cmd_audit, "list known security advisories for installed packages")
    manager_filter(p)

    p = add("repos", cmd_repos, "list configured repositories/remotes")
    manager_filter(p)

    p = add("upgrade", cmd_upgrade, "upgrade outdated packages (skips ignored ones)")
    manager_filter(p)
    p.add_argument("packages", nargs="*", help="specific packages (requires one --manager)")
    confirm(p)

    p = add("install", cmd_install, "install packages with one manager")
    p.add_argument("-m", "--manager", required=True)
    p.add_argument("packages", nargs="+")
    confirm(p)

    p = add("sync", cmd_sync, "refresh repository metadata")
    manager_filter(p)
    confirm(p)

    p = add("history", cmd_history, "show the upgrade history log")
    p.add_argument("--limit", type=int, default=50)

    p = add("ignore", cmd_ignore, "manage packages excluded from upgrades")
    p.add_argument("action", choices=["list", "add", "remove"], nargs="?", default="list")
    p.add_argument("manager", nargs="?")
    p.add_argument("package", nargs="?")

    add("catalog", cmd_catalog, "list every cataloged manager, installed or not")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        _log(f"error: {e}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        return 130
