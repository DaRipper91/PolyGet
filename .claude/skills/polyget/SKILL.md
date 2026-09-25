---
name: polyget
description: Check, search, and plan package updates across every package manager on this machine (DNF, Pacman, APT, Flatpak, npm, Cargo, Pipx, gem, and more) through PolyGet's headless CLI. Use when the user asks what's outdated, wants to update or install something, asks which manager owns or provides a package, wants a security audit of installed packages, or asks about repos/remotes or past upgrades.
---

# PolyGet CLI

PolyGet wraps every installed package manager behind one CLI. Always call it by absolute path
(the `polyget` fish function isn't visible to non-fish shells):

```bash
PG="/home/daripper/Projects/PolyGet/.venv/bin/python /home/daripper/Projects/PolyGet/run.py"
$PG <command> --json
```

Always pass `--json` and parse stdout. stderr carries progress and child-process output.
Exit codes: `0` ok · `1` at least one manager failed (the JSON still has partial results, so
report both) · `2` usage error (the JSON has an `error` key naming the valid managers).

## Read-only commands (safe to run freely)

| Command | Returns |
|---|---|
| `managers [--all]` | detected managers: name, category, available, supports_repos |
| `outdated [-m NAME]... [--include-ignored]` | `{updates: [{manager,name,current,new}], managers: {NAME: {ok,count\|error}}}` |
| `installed [-m NAME]...` | `{NAME: [package, ...]}` |
| `search QUERY [-m NAME]... [--limit N]` | `{results: [{manager,id,name,version,description}], errors}` |
| `audit [-m NAME]...` | `[{manager,name,severity,advisory}]` (npm/cargo/pip-audit style) |
| `repos [-m NAME]...` | `[{manager,id,name,url,enabled}]` |
| `history [--limit N]` | past upgrades: timestamp, manager, packages, success |
| `catalog` | every known manager, installed or not, with its distro-specific self-install command |
| `ignore list` | packages excluded from upgrades |

`-m` is repeatable and case-insensitive (`-m dnf -m flatpak`). A full `outdated` scan takes
a few seconds; filter with `-m` when the user only cares about one manager.

## Commands that change the system

`upgrade [-m NAME]... [PKG...]`, `install -m NAME PKG...`, `sync [-m NAME]...`, and
`ignore add|remove MANAGER PKG`.

- Without `--yes`, `upgrade`/`install`/`sync` **only print the plan** (`executed: false`, with
  each step's exact argv). Run them that way first and show the user the plan.
- Do not add `--yes` yourself unless the user explicitly asked you to perform that exact
  upgrade/install. When a step starts with `pkexec` (DNF, Pacman, APT, some npm setups) it needs
  an interactive polkit prompt, so ask the user to run it themselves by typing
  `! polyget upgrade -m dnf --yes` in the prompt.
- `upgrade` with no package names upgrades everything `outdated` reports minus ignored packages.
  Naming packages requires exactly one `-m`.
- `ignore add/remove` edits `~/.config/polyget/ignored_packages.json`, which the GUI shares.
  Confirm with the user before changing it.

## Reporting

- Group results by manager and give counts first ("DNF 142, NPM 6, Cargo 1; pnpm check failed").
- Always surface managers whose check failed, with the error. A failed check is not the same as
  "up to date".
- DNF reports `current` as `Installed` (no old version available); say so rather than inventing
  one.
