#!/usr/bin/env python3
"""Pixel Control Deck — Native Termux repository & APT walkthrough with keyboard and mouse controls.
Optimized for Google Pixel 10 Pro (Tensor G5 blazer · aarch64 · Android 17).

Walks APT configuration options (safety, speed, mobile memory/storage preservation)
and curated Termux package repositories with category filters, live reachability checks,
side-by-side diff review, and a Zero-Trust Dry-Run Gate.

  python3 pixel-deck.py                   # interactive TUI
  python3 pixel-deck.py --live            # probe mirror & repo reachability
  python3 pixel-deck.py --plan            # print proposed diff without launching curses
  python3 pixel-deck.py --mode repos      # jump straight to repository cards
"""
import argparse
import curses
import datetime
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path

TERMUX_PREFIX = "/data/data/com.termux/files/usr"
DEFAULT_CONF = f"{TERMUX_PREFIX}/etc/apt/apt.conf.d/99pixel-deck" if os.path.isdir(TERMUX_PREFIX) else "/etc/apt/apt.conf.d/99pixel-deck"
DEFAULT_SOURCES_DIR = f"{TERMUX_PREFIX}/etc/apt/sources.list.d" if os.path.isdir(TERMUX_PREFIX) else "/etc/apt/sources.list.d"
DEFAULT_SOURCES_LIST = f"{TERMUX_PREFIX}/etc/apt/sources.list" if os.path.isdir(TERMUX_PREFIX) else "/etc/apt/sources.list"
DEFAULT_STAGE_DIR = os.path.expanduser("~/.local/state/configure-apt")
CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "termux-repos.catalog")

# Repositories that are permanently required
REQUIRED = {"termux-main"}
REFUSED = set()  # Restrictions removed per user directive; all repositories permissible with advisory warnings

REFUSED_REASONS = {
    "debian-raw-ppa": "Ubuntu PPAs link against GNU C Library (glibc) and hardcode /usr paths incompatible with Android Bionic libc. Use glibc-repo or PRoot Debian instead.",
    "pacman-termux-repo": "Da-pixel-10-pro is strictly an APT-managed Termux installation. Co-installing pacman repos corrupts the dpkg status database.",
    "x86_64-foreign-repos": "da-pixel-10-pro runs Google Tensor G5 (aarch64). x86_64 binaries cannot execute natively.",
    "unsigned-http-repo": "Zero-Trust policy: Repositories lacking signed Release files or OpenPGP verification are rejected.",
}

# APT options: (key, group, type, default, explanation, choices, validate)
OPTIONS = [
    ("Acquire::AllowInsecureRepositories", "Safety", "bool", "false",
     "Zero-Trust Signature Gate. If false, apt strictly refuses repositories lacking OpenPGP signatures. Never set to true on da-pixel-10-pro.",
     "false/true", None),
    ("Acquire::Check-Valid-Until", "Safety", "bool", "true",
     "Enforce Release file freshness. Prevents replay attacks from compromised mirrors or stale caches.",
     "true/false", None),
    ("Acquire::Languages", "Speed", "text", "none",
     "Skip translation file downloads (Translation-en, etc.). Cuts cellular bandwidth and reduces I/O on Android flash storage.",
     "none / environment", None),
    ("Acquire::http::Pipeline-Depth", "Speed", "int:0:20", "5",
     "Number of concurrent HTTP requests pipelined over a single keepalive connection. Accelerates package index refreshes.",
     "0/5/10/20", None),
    ("Acquire::http::Timeout", "Speed", "int:5:120", "20",
     "Connection timeout in seconds. Optimized for mobile network handoffs and carrier latency on Tensor G5.",
     "10/20/30/60", None),
    ("Acquire::Retries", "Speed", "int:0:10", "3",
     "Automatic retry count for interrupted downloads on intermittent cellular/Wi-Fi transitions.",
     "1/3/5", None),
    ("APT::Install-Recommends", "Memory & Flash", "bool", "false",
     "Do not automatically install Recommended dependencies. Crucial for Tensor G5 userland ceiling (~2.5-3.0 GB headroom).",
     "false/true", None),
    ("APT::Install-Suggests", "Memory & Flash", "bool", "false",
     "Do not pull Suggested packages. Prevents memory bloat and package database sprawl.",
     "false/true", None),
    ("APT::Clean-Installed", "Memory & Flash", "bool", "true",
     "Purge downloaded deb packages from cache archives immediately after installation to save device storage.",
     "true/false", None),
    ("APT::Color", "Candy", "bool", "1",
     "Enable high-visibility ANSI color grading in terminal package listings and prompts.",
     "1/0", None),
]

RECOMMENDED = {
    "Acquire::AllowInsecureRepositories": "false",
    "Acquire::Check-Valid-Until": "true",
    "Acquire::Languages": "none",
    "Acquire::http::Pipeline-Depth": "5",
    "Acquire::http::Timeout": "20",
    "Acquire::Retries": "3",
    "APT::Install-Recommends": "false",
    "APT::Install-Suggests": "false",
    "APT::Clean-Installed": "true",
    "APT::Color": "1",
}


# ---------------------------------------------------------------- catalog ---
class CatalogEntry:
    def __init__(self, name, fields):
        self.name = name
        self.cat = fields.get("cat", "Other")
        self.kind = fields.get("kind", "")
        self.ids = fields.get("ids", "")
        self.id_list = [i for i in self.ids.split() if i]
        self.pkg = fields.get("pkg", "")
        self.url = fields.get("url", "")
        self.top = fields.get("top", "")
        self.info = fields.get("info", "")
        self.warn = fields.get("warn", "")
        self.setup = fields.get("setup", "")
        self.testing = fields.get("testing", "no") == "yes"
        self.required = fields.get("required", "no") == "yes"
        self.needs_root = fields.get("needs-root", "no") == "yes"
        self.needs = fields.get("needs", "")

    def is_refused(self):
        return False

    def has_warning(self):
        return bool(self.warn or "REFUSED" in self.setup or self.name in REFUSED_REASONS)

    def warning_text(self):
        if self.warn:
            return self.warn
        if "REFUSED" in self.setup:
            return self.setup
        return REFUSED_REASONS.get(self.name, "")

    def is_required(self):
        return self.required or self.name in REQUIRED

    def is_testing(self):
        return self.testing

    def display_status(self, is_on):
        if self.is_required():
            return "REQ"
        if not is_on:
            return "OFF"
        if self.needs_root:
            return "RSH"
        if self.has_warning():
            return "WRN"
        if self.is_testing():
            return "TST"
        return "ON "


def load_catalog(path):
    entries = {}
    if not os.path.exists(path):
        return entries
    name = None
    fields = {}
    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                if name is not None and fields:
                    entries[name] = CatalogEntry(name, fields)
                    name = None
                    fields = {}
                continue
            m = re.match(r"^\[([^\]]+)\]$", stripped)
            if m:
                if name is not None and fields:
                    entries[name] = CatalogEntry(name, fields)
                name = m.group(1)
                fields = {}
                continue
            kv = re.match(r"^([A-Za-z0-9_-]+):[ \t]?(.*)$", stripped)
            if kv and name is not None:
                k, v = kv.group(1), kv.group(2)
                if k in fields:
                    fields[k] += "\n" + v
                else:
                    fields[k] = v
    if name is not None and fields:
        entries[name] = CatalogEntry(name, fields)
    return entries


# ---------------------------------------------------------------- config ---
class AptConf:
    """View of 99pixel-deck apt.conf options."""
    def __init__(self, text=""):
        self.orig = text
        self.values = {}
        self._scan()

    def _scan(self):
        for line in self.orig.splitlines():
            line = line.strip()
            if line.startswith("//") or line.startswith("#") or not line:
                continue
            m = re.match(r'^([A-Za-z0-9_:-]+)\s+"?([^";]+)"?;', line)
            if m:
                self.values[m.group(1)] = m.group(2)

    def value(self, key):
        return self.values.get(key)

    def render(self, overrides):
        out = [
            "// 99pixel-deck — Managed by pixel-deck for da-pixel-10-pro",
            "// Architecture: aarch64 (Tensor G5 blazer) · Termux Userland",
            "",
        ]
        groups = {}
        for key, group, _, default, _, _, _ in OPTIONS:
            groups.setdefault(group, []).append(key)

        curr = dict(self.values, **overrides)
        for group, keys in groups.items():
            out.append(f"// --- {group} ---")
            for k in keys:
                val = curr.get(k, RECOMMENDED.get(k, "false"))
                out.append(f'{k} "{val}";')
            out.append("")

        out.append("// --- Unattended DPkg Safety ---")
        out.append('DPkg::Options {')
        out.append('    "--force-confdef";')
        out.append('    "--force-confold";')
        out.append('};')
        out.append("")
        return "\n".join(out)


def scan_termux_repos(sources_dir, sources_list):
    """Scan sources.list and sources.list.d/*.list to find active repository identifiers."""
    active = set()
    # Check main sources.list
    if os.path.isfile(sources_list):
        try:
            with open(sources_list) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("deb") and not line.startswith("#"):
                        active.add("termux-main")
                        if "packages-cf.termux.dev" in line:
                            active.add("termux-main-cf")
                            active.add("mirror-cloudflare")
                        elif "packages.termux.dev" in line:
                            active.add("termux-main-direct")
                            active.add("mirror-direct")
        except OSError:
            pass

    # Check sources.list.d
    if os.path.isdir(sources_dir):
        for path in Path(sources_dir).glob("*.list"):
            active.add(path.stem)
            try:
                txt = path.read_text()
                for line in txt.splitlines():
                    if line.strip().startswith("deb"):
                        active.add(path.stem)
                        # Also check if any known identifier is inside the file
                        for token in line.split():
                            active.add(token)
            except OSError:
                pass

    # Check installed repo packages via dpkg-query if available
    if shutil.which("dpkg-query"):
        try:
            cmd = ["dpkg-query", "-W", "-f=${Package} ${Status}\n"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "install ok installed" in line:
                        pkg = line.split()[0]
                        active.add(pkg)
        except Exception:
            pass

    return active


# ---------------------------------------------------------------- state ---
class State:
    def __init__(self, conf_path, sources_dir, sources_list, catalog_path, live=False):
        self.conf_path = conf_path
        self.sources_dir = sources_dir
        self.sources_list = sources_list
        self.catalog = load_catalog(catalog_path)
        conf_text = ""
        if os.path.isfile(conf_path):
            try:
                with open(conf_path) as f:
                    conf_text = f.read()
            except OSError:
                pass
        self.apt_conf = AptConf(conf_text)
        self.active_repos = scan_termux_repos(sources_dir, sources_list)
        self.live = live
        self.live_status = {}

        # Initial baseline computation
        self.initial_repo_state = {}
        for n, ent in self.catalog.items():
            if ent.name == "termux-main":
                is_act = True
            else:
                is_act = (
                    n in self.active_repos
                    or (bool(ent.pkg) and ent.pkg in self.active_repos)
                    or any(i in self.active_repos for i in ent.id_list)
                    or os.path.isfile(os.path.join(sources_dir, f"{n}.list"))
                )
            self.initial_repo_state[n] = is_act

        # Auto-discover any external .list files in sources_dir not in catalog
        if os.path.isdir(sources_dir):
            for path in Path(sources_dir).glob("*.list"):
                repo_stem = path.stem
                if repo_stem not in self.catalog:
                    first_line = ""
                    try:
                        for l in path.read_text().splitlines():
                            if l.strip().startswith("deb"):
                                first_line = l.strip()
                                break
                    except OSError:
                        pass
                    custom_ent = CatalogEntry(repo_stem, {
                        "cat": "Custom Repositories",
                        "kind": "listfile",
                        "url": first_line or "deb https://... stable main",
                        "ids": repo_stem,
                        "info": f"Custom repository detected from {path.name}",
                        "top": first_line or repo_stem,
                    })
                    self.catalog[repo_stem] = custom_ent
                    self.initial_repo_state[repo_stem] = True

        self.repo_state = dict(self.initial_repo_state)
        self.initial_options = {k: self.apt_conf.value(k) or RECOMMENDED.get(k, "") for k, _, _, _, _, _, _ in OPTIONS}
        self.options = {}
        self.reviewed = False
        self.quitting = False

    def is_on(self, name):
        return self.repo_state.get(name, False)

    def toggle(self, name):
        ent = self.catalog.get(name)
        if not ent:
            return f"[{name}] is not in the catalog."
        if ent.is_required() and self.is_on(name):
            return f"[{name}] is required for Termux base operations and cannot be disabled."
        self.repo_state[name] = not self.repo_state[name]
        self.reviewed = False
        if self.repo_state[name] and ent.has_warning():
            return f"Advisory for [{name}]: {ent.warning_text()}"
        return ""

    def add_custom_repo(self, name, deb_line, cat="Custom Repositories", info="User-defined custom APT repository"):
        clean_name = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-")
        if not clean_name:
            return False, "Invalid repository name (use alphanumeric, dash, underscore)."
        deb_line = deb_line.strip()
        if not deb_line.startswith("deb"):
            deb_line = f"deb {deb_line}"
        if not re.search(r"\[[^\]]+\]", deb_line):
            deb_line = deb_line.replace("deb ", "deb [trusted=yes] ", 1)
        fields = {
            "cat": cat,
            "kind": "listfile",
            "url": deb_line,
            "ids": clean_name,
            "info": info,
            "top": deb_line,
        }
        ent = CatalogEntry(clean_name, fields)
        self.catalog[clean_name] = ent
        self.initial_repo_state[clean_name] = False
        self.repo_state[clean_name] = True
        self.reviewed = False
        return True, f"Custom repository [{clean_name}] staged and enabled."

    def set_option(self, key, value):
        self.options[key] = str(value)
        self.reviewed = False

    def unset_option(self, key):
        self.options.pop(key, None)
        self.reviewed = False

    def option_value(self, key):
        if key in self.options:
            return self.options[key]
        return self.apt_conf.value(key) or RECOMMENDED.get(key, "")

    def proposed_conf(self):
        return self.apt_conf.render(self.options)

    def diff_text(self):
        old = self.apt_conf.orig.splitlines(keepends=True)
        new = self.proposed_conf().splitlines(keepends=True)
        diff = list(difflib.unified_diff(old, new, fromfile="current/apt.conf", tofile="proposed/apt.conf"))
        return "".join(diff)

    def changes_count(self):
        count = 0
        for k, v in self.options.items():
            if v != self.initial_options.get(k, ""):
                count += 1
        for n, on in self.repo_state.items():
            if on != self.initial_repo_state.get(n, False):
                count += 1
        return count

    def fingerprint(self):
        data = self.proposed_conf() + "\n"
        for n in sorted(self.repo_state):
            data += f"{n}:{self.repo_state[n]}\n"
        return hashlib.sha256(data.encode()).hexdigest()

    def repo_cmds(self, name, enable):
        ent = self.catalog.get(name)
        if not ent:
            return []
        cmds = []
        if ent.kind == "pkg" and ent.pkg:
            if enable:
                cmds.append(f"pkg install -y {ent.pkg}")
            else:
                cmds.append(f"pkg uninstall -y {ent.pkg}")
        elif ent.kind == "listfile":
            listfile = os.path.join(self.sources_dir, f"{name}.list")
            if enable:
                url = ent.url or "https://deb.torproject.org/torproject.org"
                if url.startswith("deb"):
                    cmds.append(f"printf '{url}\\n' > \"{listfile}\"")
                else:
                    cmds.append(f"printf 'deb {url} stable main\\n' > \"{listfile}\"")
            else:
                cmds.append(f"rm -f \"{listfile}\"")
        elif ent.kind == "mirror":
            if enable:
                mirror_map = {
                    "termux-main-cf": "https://packages-cf.termux.dev/apt/termux-main",
                    "termux-main-direct": "https://packages.termux.dev/apt/termux-main",
                    "grimler-mirror": "https://grimler.se/termux/termux-main",
                    "fcix-mirror": "https://mirror.fcix.net/termux/termux-main",
                    "bfsu-mirror": "https://mirrors.bfsu.edu.cn/termux/apt/termux-main",
                    "tuna-mirror": "https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main",
                    "librehat-mirror": "https://termux.librehat.com/apt/termux-main",
                }
                url = mirror_map.get(name)
                if url:
                    cmds.append(f"sed -i -E 's|https://[^ ]+/apt/termux-main|{url}|g' \"{self.sources_list}\"")
        return cmds

    def check_live(self, name):
        if name in self.live_status:
            return self.live_status[name]
        ent = self.catalog.get(name)
        if not ent:
            self.live_status[name] = "not in catalog"
            return self.live_status[name]

        # Determine target probe URL
        probe_url = ""
        if ent.url:
            parts = ent.url.split()
            for part in parts:
                if part.startswith("http://") or part.startswith("https://"):
                    probe_url = part
                    break
        elif ent.name in ("termux-main", "termux-main-cf"):
            probe_url = "https://packages-cf.termux.dev/apt/termux-main/dists/stable/Release"
        elif ent.name == "termux-main-direct":
            probe_url = "https://packages.termux.dev/apt/termux-main/dists/stable/Release"
        elif ent.name == "grimler-mirror":
            probe_url = "https://grimler.se/termux/termux-main/dists/stable/Release"
        elif ent.name == "fcix-mirror":
            probe_url = "https://mirror.fcix.net/termux/termux-main/dists/stable/Release"
        elif ent.name == "bfsu-mirror":
            probe_url = "https://mirrors.bfsu.edu.cn/termux/apt/termux-main/dists/stable/Release"
        elif ent.name == "tuna-mirror":
            probe_url = "https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main/dists/stable/Release"
        elif ent.name == "librehat-mirror":
            probe_url = "https://termux.librehat.com/apt/termux-main/dists/stable/Release"
        elif ent.name == "its-pointless":
            probe_url = "https://its-pointless.github.io/files/24/dists/termux/Release"
        elif ent.name == "termux-x11":
            probe_url = "https://packages-cf.termux.dev/apt/termux-x11/dists/x11/Release"
        elif ent.name == "termux-root":
            probe_url = "https://packages-cf.termux.dev/apt/termux-root/dists/root/Release"
        elif ent.name == "tur-repo":
            probe_url = "https://tur.kcubeterm.com/tur-packages/dists/tur/Release"
        elif ent.name == "science-repo":
            probe_url = "https://packages-cf.termux.dev/apt/termux-science/dists/science/Release"
        elif ent.name == "game-repo":
            probe_url = "https://packages-cf.termux.dev/apt/termux-games/dists/games/Release"

        if not probe_url:
            self.live_status[name] = "Reachable (Local package)"
            return self.live_status[name]

        try:
            req = urllib.request.Request(
                probe_url,
                headers={"User-Agent": "curl/8.0.0"},
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                code = getattr(resp, "status", 200)
                if code in (200, 301, 302):
                    self.live_status[name] = f"Reachable (HTTP {code})"
                else:
                    self.live_status[name] = f"HTTP {code}"
        except Exception as e:
            self.live_status[name] = f"Unreachable ({type(e).__name__})"
        return self.live_status[name]

    def stage_plan(self, stage_dir):
        os.makedirs(stage_dir, exist_ok=True)
        staged_conf = os.path.join(stage_dir, "apt.conf.staged")
        plan_file = os.path.join(stage_dir, "repo-plan.txt")
        orig_file = os.path.join(stage_dir, "apt.conf.orig")

        with open(staged_conf, "w") as f:
            f.write(self.proposed_conf() + "\n")
        with open(orig_file, "w") as f:
            f.write(self.apt_conf.orig)

        lines = []
        for n, on in sorted(self.repo_state.items()):
            was_on = self.initial_repo_state.get(n, False)
            if on != was_on:
                act = "enable" if on else "disable"
                lines.append(f"{n} {act}")
        with open(plan_file, "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))

    def apply_changes(self, log=print, confirm=lambda prompt: "y", dry_run=False):
        stage_dir = os.environ.get("STAGE_DIR", DEFAULT_STAGE_DIR)
        self.stage_plan(stage_dir)
        new_conf = self.proposed_conf()
        path = self.conf_path

        log("Pixel Control Deck — Zero-Trust Dry-Run Gate & Staging Verification")
        if not self.reviewed and not dry_run:
            log("Review the complete staged diff before applying.")
            return False

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{path}.bak-{stamp}"

        if dry_run:
            log(f"[dry-run] Staged configuration written to {stage_dir}")
            log(f"[dry-run] Changes staged: {self.changes_count()}")
            log("[dry-run] Dry run PASSED.")
            return True

        # 1. Back up current configuration if exists
        had_conf = os.path.isfile(path)
        try:
            if had_conf:
                shutil.copy2(path, backup)
                log(f"✓ Backup created: {backup}")
        except Exception as e:
            log(f"!! Backup failed: {e}")
            return False

        # 2. Install new configuration atomically
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with tempfile.NamedTemporaryFile("w", delete=False) as tf:
                tf.write(new_conf + "\n")
                tmp_path = tf.name
            shutil.move(tmp_path, path)
            os.chmod(path, 0o644)
            log(f"✓ Installed {path}")
        except Exception as e:
            log(f"!! Install failed: {e}")
            return False

        # 3. Apply repository mutations; the first failure aborts and restores the config
        failed = None
        for n, on in sorted(self.repo_state.items()):
            was_on = self.initial_repo_state.get(n, False)
            if on == was_on:
                continue
            act_str = "enable" if on else "disable"
            log(f"Executing: {act_str} [{n}]...")
            for cmd in self.repo_cmds(n, on):
                log(f"+ {cmd}")
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if res.returncode != 0:
                    failed = (n, cmd, res.returncode, res.stderr.strip())
                    break
            if failed:
                break

        if failed:
            n, cmd, rc, err = failed
            log(f"!! [{n}] command exited with code {rc}: {cmd}")
            if err:
                log(f"   {err}")
            try:
                if had_conf:
                    shutil.copy2(backup, path)
                    log(f"!! Restored previous configuration from {backup}")
                elif os.path.isfile(path):
                    os.remove(path)
                    log(f"!! Removed {path} (it did not exist before this apply)")
            except OSError as e:
                log(f"!! Could not restore configuration: {e}")
            log("!! Repository changes made before the failure are NOT rolled back; check `pkg list-installed`.")
            return False

        log("✓ All repository mutations complete.")
        return True


# ---------------------------------------------------------------- curses UI ---
class DeckApp:
    def __init__(self, stdscr, state, initial_tab=0):
        self.stdscr = stdscr
        self.state = state
        self.tab = initial_tab  # 0: Options, 1: Repos, 2: Review
        self.opt_idx = 0
        self.repo_idx = 0
        self.cat_idx = 0
        self.diff_offset = 0
        self.search_query = ""
        self.status_msg = ""
        self.show_help = False

        self.categories = []
        self._refresh_categories()

        self.visible_repos = []
        self._update_visible_repos()

    def _refresh_categories(self):
        cats_order = [
            "All",
            "Official & Core Overlays",
            "Community & User Repos (TUR)",
            "Security & Infrastructure",
            "Dev, Toolchains & Scientific",
            "Experimental & Hardware Overlays",
            "Custom Repositories",
        ]
        present_cats = {e.cat for e in self.state.catalog.values()}
        ordered = ["All"] + [c for c in cats_order[1:] if c in present_cats]
        for c in sorted(present_cats):
            if c not in ordered:
                ordered.append(c)
        self.categories = ordered
        if self.cat_idx >= len(self.categories):
            self.cat_idx = 0

    def _update_visible_repos(self):
        res = []
        cur_cat = self.categories[self.cat_idx]
        for name, ent in sorted(self.state.catalog.items()):
            if cur_cat != "All" and ent.cat != cur_cat:
                continue
            if self.search_query:
                q = self.search_query.lower()
                if q not in name.lower() and q not in ent.info.lower() and q not in ent.top.lower() and q not in ent.cat.lower():
                    continue
            res.append(name)
        self.visible_repos = res
        if self.repo_idx >= len(self.visible_repos):
            self.repo_idx = max(0, len(self.visible_repos) - 1)

    def run(self):
        try:
            curses.curs_set(0)
        except (curses.error, OSError):
            pass
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except (curses.error, OSError):
            pass

        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)     # Cyan / Headers
            curses.init_pair(2, curses.COLOR_GREEN, -1)    # Green / ON / Success
            curses.init_pair(3, curses.COLOR_RED, -1)      # Red / Refused / Alert
            curses.init_pair(4, curses.COLOR_YELLOW, -1)   # Yellow / Warning / Needs Root
            curses.init_pair(5, curses.COLOR_MAGENTA, -1)  # Magenta / Cursor
            curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)  # Blue bar

        while not self.state.quitting:
            self.draw()
            ch = self.stdscr.getch()
            self.handle_input(ch)

    def safe_addstr(self, y, x, text, attr=0):
        max_y, max_x = self.stdscr.getmaxyx()
        if 0 <= y < max_y and 0 <= x < max_x:
            avail = max_x - x
            if avail > 0:
                try:
                    self.stdscr.addstr(y, x, text[:avail], attr)
                except curses.error:
                    pass

    def draw(self):
        self.stdscr.clear()
        max_y, max_x = self.stdscr.getmaxyx()
        if max_y < 14 or max_x < 70:
            self.safe_addstr(0, 0, "Terminal window too small for Pixel Control Deck (min 70x14).")
            self.stdscr.refresh()
            return

        # Title bar with hardware badges
        title = " Pixel Control Deck "
        badge = " [da-pixel-10-pro · Tensor G5 blazer · aarch64 · Android 17] "
        pad = max_x - len(title) - len(badge)
        bar = title + (" " * max(0, pad)) + badge
        self.safe_addstr(0, 0, bar[:max_x], curses.color_pair(6) | curses.A_BOLD)

        # Tabs bar
        tabs = [
            (" [1] Options ", 0),
            (" [2] Repositories ", 1),
            (" [3] Review & Apply ", 2),
        ]
        col = 2
        for label, idx in tabs:
            if self.tab == idx:
                self.safe_addstr(1, col, label, curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
            else:
                self.safe_addstr(1, col, label, curses.A_DIM)
            col += len(label) + 2

        # Changes indicator
        changes = self.state.changes_count()
        if changes > 0:
            ch_str = f" [Staged Changes: {changes}] "
            self.safe_addstr(1, max_x - len(ch_str) - 2, ch_str, curses.color_pair(2) | curses.A_BOLD)
        else:
            ch_str = " [No Changes] "
            self.safe_addstr(1, max_x - len(ch_str) - 2, ch_str, curses.A_DIM)

        self.safe_addstr(2, 0, "─" * (max_x - 1), curses.A_DIM)

        # Tab content
        if self.tab == 0:
            self.draw_options(3, max_y - 3, max_x)
        elif self.tab == 1:
            self.draw_repos(3, max_y - 3, max_x)
        else:
            self.draw_review(3, max_y - 3, max_x)

        # Help modal if triggered
        if self.show_help:
            self.draw_help_modal(max_y, max_x)

        # Status footer
        self.safe_addstr(max_y - 3, 0, "─" * (max_x - 1), curses.A_DIM)
        if self.status_msg:
            self.safe_addstr(max_y - 2, 2, self.status_msg[:max_x - 4], curses.color_pair(3) | curses.A_BOLD)
        elif self.tab == 1:
            hints = " [Tab/1-3] Tabs  [↑/↓] Navigate  [Space/Enter] Toggle  [+] Add Custom Repo  [c] Cat  [/] Search  [l] Live  [?] Help  [q] Quit "
            self.safe_addstr(max_y - 2, 2, hints[:max_x - 4], curses.A_DIM)
        else:
            hints = " [Tab/1-3] Tabs  [↑/↓] Navigate  [Space/Enter] Toggle/Edit  [r] Recom  [u] Unset  [l] Live  [/] Search  [?] Help  [q] Quit "
            self.safe_addstr(max_y - 2, 2, hints[:max_x - 4], curses.A_DIM)

        self.stdscr.refresh()

    def draw_options(self, top, bottom, max_x):
        split = max(42, max_x // 2)
        height = bottom - top

        self.safe_addstr(top, 2, "APT & Mirror Configuration (99pixel-deck)", curses.color_pair(1) | curses.A_BOLD)

        last_group = ""
        row = top + 2
        for i, (key, group, _, _, _, _, _) in enumerate(OPTIONS):
            if row >= bottom:
                break
            if group != last_group:
                last_group = group
                self.safe_addstr(row, 2, f"// --- {group} ---", curses.color_pair(1) | curses.A_DIM)
                row += 1
                if row >= bottom:
                    break

            val = self.state.option_value(key)
            rec = RECOMMENDED.get(key, "")
            is_rec = (val == rec)
            is_overridden = key in self.state.options

            marker = "  "
            attr = curses.A_NORMAL
            if i == self.opt_idx:
                marker = "› "
                attr = curses.color_pair(5) | curses.A_BOLD

            val_color = curses.color_pair(2) if is_rec else (curses.color_pair(4) if is_overridden else curses.A_NORMAL)
            line_key = f"{marker}{key:<30} = "
            self.safe_addstr(row, 2, line_key[:split - 12], attr)
            self.safe_addstr(row, 2 + len(line_key), f"{val:<8}", val_color | curses.A_BOLD)
            row += 1

        # Vertical divider
        for r in range(top, bottom):
            self.safe_addstr(r, split, "│", curses.A_DIM)

        # Right pane: Option Details
        if 0 <= self.opt_idx < len(OPTIONS):
            key, group, otype, default, expl, choices, _ = OPTIONS[self.opt_idx]
            cur_val = self.state.option_value(key)
            rec_val = RECOMMENDED.get(key, "")

            col = split + 3
            self.safe_addstr(top, col, f"Option: {key}", curses.color_pair(1) | curses.A_BOLD)
            self.safe_addstr(top + 1, col, f"Group:  {group}    Type: {otype}", curses.A_DIM)
            self.safe_addstr(top + 2, col, f"Current: {cur_val}    Recommended: {rec_val}", curses.color_pair(2) | curses.A_BOLD)
            self.safe_addstr(top + 3, col, f"Choices: {choices}", curses.A_DIM)

            self.safe_addstr(top + 5, col, "Explanation:", curses.A_BOLD)
            wrap_w = max_x - col - 4
            wrapped = textwrap.wrap(expl, width=wrap_w)
            for j, wline in enumerate(wrapped[:height - 7]):
                self.safe_addstr(top + 6 + j, col, wline)

    def draw_repos(self, top, bottom, max_x):
        split = max(44, max_x // 2 - 2)
        height = bottom - top

        # Header with category & search filter chips
        cur_cat = self.categories[self.cat_idx]
        chips = f"Filter: [{cur_cat}] (c to cycle)   Search: '{self.search_query}' (/ to search, x to clear)"
        self.safe_addstr(top, 2, chips[:max_x - 4], curses.color_pair(1) | curses.A_BOLD)

        # Left list: Repositories
        list_h = height - 2
        start_idx = 0
        if self.repo_idx >= list_h:
            start_idx = self.repo_idx - list_h + 1

        for idx, name in enumerate(self.visible_repos[start_idx:start_idx + list_h]):
            i = start_idx + idx
            row = top + 2 + idx
            ent = self.state.catalog[name]
            is_on = self.state.is_on(name)
            badge = ent.display_status(is_on)

            badge_attr = curses.color_pair(2) if badge in ("ON ", "REQ") else curses.color_pair(4)
            if badge == "WRN":
                badge_attr = curses.color_pair(3) | curses.A_BOLD
            elif badge == "RSH":
                badge_attr = curses.color_pair(4) | curses.A_BOLD
            elif badge == "TST":
                badge_attr = curses.color_pair(1)

            marker = "› " if i == self.repo_idx else "  "
            attr = curses.color_pair(5) | curses.A_BOLD if i == self.repo_idx else curses.A_NORMAL

            self.safe_addstr(row, 2, marker, attr)
            self.safe_addstr(row, 4, f"[{badge}]", badge_attr | curses.A_BOLD)
            self.safe_addstr(row, 11, f" {name:<26}", attr)

        # Vertical divider
        for r in range(top + 1, bottom):
            self.safe_addstr(r, split, "│", curses.A_DIM)

        # Right pane: Repo Card Details
        if 0 <= self.repo_idx < len(self.visible_repos):
            name = self.visible_repos[self.repo_idx]
            ent = self.state.catalog[name]
            is_on = self.state.is_on(name)
            live_stat = self.state.live_status.get(name, "Press [l] to probe")

            col = split + 3
            self.safe_addstr(top + 1, col, f"Repository: {name}", curses.color_pair(1) | curses.A_BOLD)
            self.safe_addstr(top + 2, col, f"Category:   {ent.cat}", curses.A_DIM)
            self.safe_addstr(top + 3, col, f"Kind:       {ent.kind}", curses.A_DIM)

            status_text = "ENABLED" if is_on else "DISABLED"
            st_color = curses.color_pair(2) if is_on else curses.color_pair(4)
            self.safe_addstr(top + 4, col, f"State:      {status_text}", st_color | curses.A_BOLD)
            self.safe_addstr(top + 5, col, f"Live Check: {live_stat}", curses.color_pair(1) | curses.A_BOLD)

            r = top + 7
            warn_msg = ent.warning_text() if hasattr(ent, "warning_text") else ent.warn
            if warn_msg:
                self.safe_addstr(r, col, f"! ADVISORY: {warn_msg}"[:max_x - col - 4], curses.color_pair(4) | curses.A_BOLD)
                r += 2

            self.safe_addstr(r, col, "Flagship Packages:", curses.A_BOLD)
            r += 1
            wrapped_top = textwrap.wrap(ent.top or "(none specified)", width=max_x - col - 4)
            for line in wrapped_top[:3]:
                self.safe_addstr(r, col, f"  {line}")
                r += 1

            r += 1
            self.safe_addstr(r, col, "Description:", curses.A_BOLD)
            r += 1
            wrapped_info = textwrap.wrap(ent.info, width=max_x - col - 4)
            for line in wrapped_info[:4]:
                self.safe_addstr(r, col, f"  {line}")
                r += 1

    def draw_review(self, top, bottom, max_x):
        self.safe_addstr(top, 2, "Zero-Trust Dry-Run & Staged Diff Review", curses.color_pair(1) | curses.A_BOLD)

        # Repository Mutations list
        mutations = []
        for n, on in sorted(self.state.repo_state.items()):
            was_on = self.state.initial_repo_state.get(n, False)
            if on != was_on:
                act = "ENABLE " if on else "DISABLE"
                mutations.append(f"  {act} repository [{n}]")

        r = top + 2
        self.safe_addstr(r, 2, "Repository Action Plan:", curses.A_BOLD)
        r += 1
        if mutations:
            for m in mutations[:4]:
                self.safe_addstr(r, 2, m, curses.color_pair(2) | curses.A_BOLD)
                r += 1
        else:
            self.safe_addstr(r, 2, "  (No repository status changes staged)", curses.A_DIM)
            r += 1

        r += 1
        self.safe_addstr(r, 2, "Configuration Diff (99pixel-deck):", curses.A_BOLD)
        r += 1

        diff = self.state.diff_text()
        lines = diff.splitlines() if diff else ["(No apt.conf changes staged)"]

        max_diff_lines = bottom - r - 3
        slice_lines = lines[self.diff_offset:self.diff_offset + max_diff_lines]

        for line in slice_lines:
            attr = curses.A_NORMAL
            if line.startswith("+"):
                attr = curses.color_pair(2)
            elif line.startswith("-"):
                attr = curses.color_pair(3)
            elif line.startswith("@"):
                attr = curses.color_pair(1)
            self.safe_addstr(r, 2, line[:max_x - 4], attr)
            r += 1

        # Check if user scrolled through diff to verify
        if self.diff_offset + max_diff_lines >= len(lines):
            self.state.reviewed = True

        rev_banner = " [✓ REVIEWED - READY TO APPLY] " if self.state.reviewed else " [⚠ SCROLL DIFF TO COMPLETE REVIEW] "
        banner_attr = curses.color_pair(2) | curses.A_BOLD if self.state.reviewed else curses.color_pair(4) | curses.A_BOLD
        self.safe_addstr(bottom - 2, 2, rev_banner, banner_attr)

        apply_btn = " [A] APPLY (DRY-RUN GATED) "
        self.safe_addstr(bottom - 1, 2, apply_btn, curses.color_pair(6) | curses.A_BOLD)

    def draw_help_modal(self, max_y, max_x):
        w = min(68, max_x - 4)
        h = 16
        y = (max_y - h) // 2
        x = (max_x - w) // 2

        for r in range(y, y + h):
            self.safe_addstr(r, x, " " * w, curses.color_pair(6))

        self.safe_addstr(y + 1, x + 2, "── Pixel Control Deck Help & Shortcuts ──", curses.A_BOLD)
        lines = [
            "Tab / 1, 2, 3   : Switch tabs (Options, Repos, Review)",
            "↑ / ↓ / j / k   : Navigate current list",
            "Space / Enter   : Toggle option / repository / cycle choice",
            "r / R           : Reset option to recommended default",
            "u / U           : Unset option override",
            "l / L           : Probe live repository reachability",
            "c / C           : Cycle repository category filter",
            "/               : Search catalog / query filter",
            "x / X           : Clear search query filter",
            "+ / n           : Add custom third-party APT repo line",
            "a / A           : Apply staged configuration (Review tab)",
            "? / F1          : Toggle this help dialog",
            "q / Q           : Quit Pixel Control Deck",
        ]
        for idx, line in enumerate(lines):
            self.safe_addstr(y + 3 + idx, x + 2, line)
        self.safe_addstr(y + h - 1, x + 2, "Press any key to close help...", curses.A_DIM)

    def handle_input(self, ch):
        self.status_msg = ""
        if self.show_help:
            self.show_help = False
            return

        # Global Hotkeys
        if ch in (ord('q'), ord('Q')):
            self.state.quitting = True
            return
        if ch in (ord('?'), curses.KEY_F1):
            self.show_help = True
            return

        # Mouse Handling
        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    if my == 1:
                        if 2 <= mx <= 16:
                            self.tab = 0
                        elif 17 <= mx <= 36:
                            self.tab = 1
                        elif 37 <= mx <= 58:
                            self.tab = 2
                    return
            except curses.error:
                pass

        # Tab Switching
        if ch == ord('1'):
            self.tab = 0
            return
        elif ch == ord('2'):
            self.tab = 1
            return
        elif ch == ord('3'):
            self.tab = 2
            return
        elif ch in (9,):  # Tab
            self.tab = (self.tab + 1) % 3
            return

        # Options Tab
        if self.tab == 0:
            if ch in (curses.KEY_UP, ord('k')):
                self.opt_idx = max(0, self.opt_idx - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                self.opt_idx = min(len(OPTIONS) - 1, self.opt_idx + 1)
            elif ch in (ord('r'), ord('R')):
                key = OPTIONS[self.opt_idx][0]
                rec = RECOMMENDED.get(key)
                if rec:
                    self.state.set_option(key, rec)
                    self.status_msg = f"Reset {key} to recommended: {rec}"
            elif ch in (ord('u'), ord('U')):
                key = OPTIONS[self.opt_idx][0]
                self.state.unset_option(key)
                self.status_msg = f"Unset override for {key}"
            elif ch in (10, 13, ord(' ')):
                key, _, otype, _, _, choices, _ = OPTIONS[self.opt_idx]
                cur = self.state.option_value(key)
                if otype == "bool":
                    new_val = "false" if cur in ("true", "1") else "true"
                    self.state.set_option(key, new_val)
                elif key == "Acquire::Languages":
                    new_val = "environment" if cur == "none" else "none"
                    self.state.set_option(key, new_val)
                elif otype.startswith("int:"):
                    choice_list = choices.split("/")
                    try:
                        next_idx = (choice_list.index(cur) + 1) % len(choice_list)
                        self.state.set_option(key, choice_list[next_idx])
                    except ValueError:
                        self.state.set_option(key, choice_list[0])

        # Repos Tab
        elif self.tab == 1:
            if ch in (curses.KEY_UP, ord('k')):
                self.repo_idx = max(0, self.repo_idx - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                self.repo_idx = min(len(self.visible_repos) - 1, self.repo_idx + 1)
            elif ch in (ord('c'), ord('C')):
                self.cat_idx = (self.cat_idx + 1) % len(self.categories)
                self._update_visible_repos()
            elif ch in (ord('l'), ord('L')):
                if self.visible_repos:
                    name = self.visible_repos[self.repo_idx]
                    status = self.state.check_live(name)
                    self.status_msg = f"[{name}] {status}"
            elif ch == ord('/'):
                self.prompt_search()
            elif ch in (ord('x'), ord('X')):
                self.search_query = ""
                self._update_visible_repos()
                self.status_msg = "Cleared search filter"
            elif ch in (ord('+'), ord('n'), ord('N'), ord('a'), ord('A')):
                self.prompt_add_custom_repo()
            elif ch in (10, 13, ord(' ')):
                if self.visible_repos:
                    name = self.visible_repos[self.repo_idx]
                    err = self.state.toggle(name)
                    if err:
                        self.status_msg = err

        # Review Tab
        elif self.tab == 2:
            if ch in (curses.KEY_UP, ord('k')):
                self.diff_offset = max(0, self.diff_offset - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                self.diff_offset += 1
            elif ch == curses.KEY_PPAGE:
                self.diff_offset = max(0, self.diff_offset - 5)
            elif ch == curses.KEY_NPAGE:
                self.diff_offset += 5
            elif ch in (ord('a'), ord('A')):
                self.apply_plan()

    def prompt_search(self):
        curses.echo()
        try:
            curses.curs_set(1)
        except (curses.error, OSError):
            pass
        max_y, max_x = self.stdscr.getmaxyx()
        prompt_y = max_y - 2
        self.safe_addstr(prompt_y, 2, "Search catalog: " + (" " * 40), curses.A_BOLD)
        try:
            self.stdscr.move(prompt_y, 18)
            q = self.stdscr.getstr(prompt_y, 18, 30).decode('utf-8', errors='ignore')
            self.search_query = q.strip()
        except Exception:
            pass
        curses.noecho()
        try:
            curses.curs_set(0)
        except (curses.error, OSError):
            pass
        self._update_visible_repos()

    def prompt_add_custom_repo(self):
        curses.echo()
        try:
            curses.curs_set(1)
        except (curses.error, OSError):
            pass
        max_y, max_x = self.stdscr.getmaxyx()
        prompt_y = max_y - 2

        self.safe_addstr(prompt_y, 2, " " * (max_x - 4), curses.A_NORMAL)
        self.safe_addstr(prompt_y, 2, "New Repo Name (slug): ", curses.A_BOLD)
        try:
            name_bytes = self.stdscr.getstr(prompt_y, 24, 30)
            repo_name = name_bytes.decode('utf-8', errors='ignore').strip()
        except Exception:
            repo_name = ""

        if not repo_name:
            curses.noecho()
            try:
                curses.curs_set(0)
            except (curses.error, OSError):
                pass
            self.status_msg = "Add repo cancelled (empty name)."
            return

        self.safe_addstr(prompt_y, 2, " " * (max_x - 4), curses.A_NORMAL)
        prompt_prefix = f"Deb line for [{repo_name}]: "
        self.safe_addstr(prompt_y, 2, prompt_prefix, curses.A_BOLD)
        try:
            line_bytes = self.stdscr.getstr(prompt_y, 2 + len(prompt_prefix), max_x - 6 - len(prompt_prefix))
            deb_line = line_bytes.decode('utf-8', errors='ignore').strip()
        except Exception:
            deb_line = ""

        curses.noecho()
        try:
            curses.curs_set(0)
        except (curses.error, OSError):
            pass

        if not deb_line:
            self.status_msg = "Add repo cancelled (empty deb line)."
            return

        ok, msg = self.state.add_custom_repo(repo_name, deb_line)
        self.status_msg = msg
        self._refresh_categories()
        self._update_visible_repos()

    def apply_plan(self):
        if not self.state.reviewed:
            self.status_msg = "Scroll to the end of the diff to review it before applying."
            return
        curses.endwin()
        print("\n" + "=" * 70)
        print("  Pixel Control Deck — Staging & Applying Verified Configuration")
        print("=" * 70 + "\n")
        try:
            try:
                answer = input("Apply the reviewed changes? [y/N] ")
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer.strip().lower() != "y":
                print("Apply cancelled.")
                self.state.reviewed = False
                print("\nPress Enter to return to deck...")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
                return

            ok = self.state.apply_changes(log=print, dry_run=False)
            print("\n" + ("Applied." if ok else "NOT applied — see messages above."))
            print("\nPress Enter to return to deck...")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
            if ok:
                # Reload configuration and state from disk
                conf_text = ""
                if os.path.isfile(self.state.conf_path):
                    with open(self.state.conf_path) as f:
                        conf_text = f.read()
                self.state.apt_conf = AptConf(conf_text)
                self.state.active_repos = scan_termux_repos(self.state.sources_dir, self.state.sources_list)
                self.state.initial_repo_state = {n: (n in self.state.active_repos or n == "termux-main") for n in self.state.catalog}
                self.state.repo_state = dict(self.state.initial_repo_state)
                self.state.options.clear()
                self.state.reviewed = False
                self.diff_offset = 0
                self.status_msg = "✓ Configuration and repository mutations applied successfully!"
            else:
                self.status_msg = "!! Apply aborted or encountered warnings."
        except Exception as e:
            print(f"Apply error: {e}")
            try:
                input("Press Enter to return...")
            except (EOFError, KeyboardInterrupt):
                pass
        finally:
            self.stdscr.clear()
            self.stdscr.refresh()
            self.tab = 1  # Return to repos tab


# ---------------------------------------------------------------- main ---
def main():
    parser = argparse.ArgumentParser(description="Pixel Control Deck — Native Termux TUI")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to apt.conf configuration file")
    parser.add_argument("--sources-dir", default=DEFAULT_SOURCES_DIR, help="Path to sources.list.d directory")
    parser.add_argument("--sources-list", default=DEFAULT_SOURCES_LIST, help="Path to sources.list file")
    parser.add_argument("--catalog", default=CATALOG_PATH, help="Path to termux-repos.catalog")
    parser.add_argument("--plan", action="store_true", help="Print diff and exit without curses")
    parser.add_argument("--live", action="store_true", help="Probe repository availability")
    parser.add_argument("--mode", choices=["options", "repos", "review"], default="options")
    args = parser.parse_args()

    state = State(args.conf, args.sources_dir, args.sources_list, args.catalog, live=args.live)

    if args.live:
        print("=== Probing Catalog Reachability ===")
        for name in sorted(state.catalog):
            status = state.check_live(name)
            print(f"  [{name:<22}] {status}")
        print()

    if args.plan:
        print("=== Proposed 99pixel-deck Configuration Diff ===")
        diff = state.diff_text()
        print(diff if diff else "(No apt.conf changes)")
        print("\n=== Repository State Plan ===")
        mutations = 0
        for n, on in sorted(state.repo_state.items()):
            was_on = state.initial_repo_state.get(n, False)
            if on != was_on:
                print(f"  {'ENABLE ' if on else 'DISABLE'} [{n}]")
                mutations += 1
        if mutations == 0:
            print("  (No repository status changes staged)")
        return 0

    init_tab = 0
    if args.mode == "repos":
        init_tab = 1
    elif args.mode == "review":
        init_tab = 2

    if not sys.stdout.isatty() or not sys.stdin.isatty():
        if not args.live:
            print("Pixel Control Deck TUI requires an interactive terminal session (TTY).")
            print("Run with --plan to inspect staged diff or --live to probe mirrors non-interactively.")
        return 0

    try:
        curses.wrapper(lambda stdscr: DeckApp(stdscr, state, initial_tab=init_tab).run())
    except (curses.error, KeyboardInterrupt):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
