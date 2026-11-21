#!/usr/bin/env python3
"""Asahi Control Deck — dnf5 repository walkthrough with mouse and keyboard controls.

Options come first: dnf.conf [main] settings one at a time or grouped, each with
an explanation, current value, recommended value and choices. Then repositories:
every entry in repos.catalog plus repos already in /etc/yum.repos.d/*.repo,
with category, description, the exact dnf commands that enable/disable them, and
live aarch64 build checks with --live.

Review the full diff, then explicitly apply. Apply validates with dnf, backs up
the current files, stages through a dry-run gate, and installs only after a
passing dry run. Never runs dnf without a refresh; never removes fedora/updates
or the required Asahi COPRs.

  python asahi-deck.py                    # walk dnf.conf options, then repos
  python asahi-deck.py --mode grouped     # skip the startup choice
  python asahi-deck.py --live             # check each repo's aarch64 build
  python asahi-deck.py --plan             # print current diff, no TUI
  python asahi-deck.py --conf /tmp/d.conf --repos-dir /tmp/repos.d
"""
import argparse
import configparser
import curses
import datetime
import difflib
import hashlib
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

DEFAULT_CONF = "/etc/dnf/dnf.conf"
REPO_DIR = "/etc/yum.repos.d"
CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repos.catalog")

# dnf repos that must stay enabled on Asahi (kernel comes from @asahi/kernel,
# branding carries the repo definitions, u-boot is the boot chain).
REQUIRED = {"fedora", "updates", "asahi-kernel", "asahi-u-boot", "asahi-branding"}

# Repos that have no aarch64 build, would replace Asahi's Mesa/graphics stack,
# or conflict with another enabled repo here. The TUI shows them but won't toggle on.
REFUSED = {
    "terra-mesa", "terra-nvidia", "rpmfusion-nonfree-nvidia",
    "rpmfusion-nonfree-steam", "negativo17-multimedia",
    "google-chrome", "microsoft-edge",
}

REFUSED_REASONS = {
    "terra-mesa": "Replaces Asahi's custom Mesa GPU driver. Overwriting Mesa will DESTROY Apple AGX graphics acceleration and desktop rendering!",
    "terra-nvidia": "Apple Silicon M-series hardware has no Nvidia GPU. Kernel modules and drivers from this repo are completely incompatible.",
    "rpmfusion-nonfree-nvidia": "Nvidia proprietary drivers have no hardware or kernel-16k support on Apple Silicon.",
    "rpmfusion-nonfree-steam": "Standard x86 Steam RPM cannot run on aarch64. Use 'asahi-steam' which runs Steam via FEX-Emu x86 translation.",
    "negativo17-multimedia": "Packaging conflicts directly with Fedora Asahi core multimedia libraries and Mesa dependencies.",
    "google-chrome": "Proprietary x86_64 RPM without an official native aarch64 Linux build. Use Chromium or Brave instead.",
    "microsoft-edge": "Proprietary x86_64 RPM without an official native aarch64 Linux build. Use Chromium or Brave instead.",
}

# dnf.conf [main] options: (key, group, type, default, explanation, choices, validate)
# Types: bool (True/False) · int:LO:HI · enum:a;b;c · text · custom
OPTIONS = [
    ("gpgcheck", "Safety", "bool", "True",
     "Verify every package's OpenPGP signature before installing. Turning this off lets any mirror or compromised key feed you modified packages.",
     "on/off", None),
    ("installonly_limit", "Safety", "int:0:9", "3",
     "How many kernel-16k (installonly) packages are kept side by side. Each set is ~100–300 MB across /boot and /lib/modules on Apple Silicon. 0 = keep forever; 1 is rejected because it blocks kernel upgrades.",
     "0/2/3/5", None),
    ("protect_running_kernel", "Safety", "bool", "True",
     "dnf will never remove the kernel you're currently booted into. Asahi's kernel-16k is installonly, so this keeps at least one working kernel after upgrades.",
     "on/off", None),
    ("clean_requirements_on_remove", "Safety", "bool", "True",
     "dnf remove also removes dependencies that nothing else needs. Undo with dnf history undo.",
     "on/off", None),
    ("best", "Safety", "bool", "False",
     "True = always demand the newest version or fail the transaction. False = fall back to an older package when the newest can't install (Fedora's default; friendlier with COPRs that lag after a release upgrade).",
     "on/off", None),
    ("skip_if_unavailable", "Safety", "bool", "True",
     "If a repo can't be reached (a COPR missing your release right after a Fedora upgrade), skip it instead of failing the whole update. Recommended with COPRs.",
     "on/off", None),
    ("excludepkgs", "Safety", "text", "__absent__",
     "Packages dnf must never install or update (globs OK). Use for pinning after a regression; remove the pin once the fix lands so you don't fall behind on security updates.",
     "(unset) / mesa* / kernel*", None),
    ("max_parallel_downloads", "Speed", "int:1:20", "10",
     "Packages downloaded at once. dnf5 default is 3, max 20. Above ~15 rarely helps and some mirrors rate-limit.",
     "3/10/20", None),
    ("max_downloads_per_mirror", "Speed", "int:1:20", "3",
     "Parallel download connections to a single mirror.",
     "3/5", None),
    ("fastestmirror", "Speed", "bool", "False",
     "Probe mirror latency and pick the fastest. Fedora's metalink already geo-sorts mirrors; probing usually costs more than it saves unless your local mirrors are bad.",
     "on/off", None),
    ("metadata_expire", "Speed", "custom", "43200",
     "How often repo metadata is re-checked. Seconds, or with s/m/h/d suffix, or never. dnf upgrade --refresh always re-checks anyway.",
     "43200 (12h) / 172800 (48h) / 6h / never", None),
    ("zchunk", "Speed", "bool", "True",
     "Delta-download repo metadata when available. Smaller, faster metadata refreshes.",
     "on/off", None),
    ("keepcache", "Speed", "bool", "False",
     "Keep downloaded RPMs after installing. The SSD is shared with macOS, so space is tight.",
     "on/off", None),
    ("install_weak_deps", "Speed", "bool", "True",
     "Install Recommends/Supplements too. False = leaner installs, occasionally missing an expected extra (fonts, codecs).",
     "on/off", None),
    ("timeout", "Speed", "int:5:300", "30",
     "Seconds a slow connection may stay below minrate before dnf aborts it.",
     "30/60", None),
    ("defaultyes", "Candy", "bool", "True",
     "Enter means Yes at confirmation prompts (dnf still asks first).",
     "on/off", None),
]
COLOR_OPTS = [
    ("color_list_available_upgrade", "bold,cyan", "Color for upgradable packages in lists."),
    ("color_list_available_downgrade", "dim,magenta", "Color for downgrades."),
    ("color_list_available_reinstall", "bold,green", "Color for reinstallable packages."),
    ("color_list_available_install", "bold,blue", "Color for installable packages."),
    ("color_update_installed", "dim,red", "Installed version in update listings."),
    ("color_update_local", "dim,green", "Locally available version in update listings."),
    ("color_update_remote", "bold,magenta", "Remote (new) version in update listings."),
    ("color_search_match", "bold,magenta", "Highlight of matched text in dnf search."),
]

# Normalize COLOR_OPTS to the same 7-tuple shape as OPTIONS so they can be
# iterated together everywhere. COLOR_OPTS entries are (key, default, desc).
ALL_OPTIONS = list(OPTIONS)
for _key, _default, _desc in COLOR_OPTS:
    ALL_OPTIONS.append((_key, "Candy", "text", _default, _desc, "comma-separated dnf5 color words", None))

RECOMMENDED = {
    "gpgcheck": "True",
    "installonly_limit": "3",
    "protect_running_kernel": "True",
    "clean_requirements_on_remove": "True",
    "best": "False",
    "skip_if_unavailable": "True",
    "excludepkgs": "__absent__",
    "max_parallel_downloads": "10",
    "max_downloads_per_mirror": "3",
    "fastestmirror": "False",
    "metadata_expire": "43200",
    "zchunk": "True",
    "keepcache": "False",
    "install_weak_deps": "True",
    "timeout": "30",
    "defaultyes": "True",
}

FLAGS = {k for k, _, t, _, _, _, _ in OPTIONS if t == "bool"}
DNF_COLOR_WORDS = {
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "bold", "dim", "underline", "blink", "reverse",
}

# --- System & Architecture Badges ---
def get_hardware_badge():
    arch = platform.machine() or "aarch64"
    try:
        pagesize = os.sysconf("SC_PAGE_SIZE")
        if pagesize == 16384:
            page_str = "16K"
        elif pagesize == 4096:
            page_str = "4K"
        elif pagesize == 65536:
            page_str = "64K"
        else:
            page_str = f"{pagesize // 1024}K"
    except Exception:
        page_str = "16K"
    return f"{arch} · {page_str}"


def get_hostname():
    try:
        return socket.gethostname() or "asahi"
    except Exception:
        return "asahi"


# --- ANSI Helpers for Clean CLI Layout ---
ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(text):
    return ANSI_PATTERN.sub('', str(text))


def pad_ansi(text, width, align='left'):
    visible_width = len(strip_ansi(text))
    padding = max(0, width - visible_width)
    if align == 'right':
        return (' ' * padding) + str(text)
    elif align == 'center':
        left = padding // 2
        right = padding - left
        return (' ' * left) + str(text) + (' ' * right)
    return str(text) + (' ' * padding)


def make_progress_bar(current, total, width=10):
    if total <= 0:
        pct = 100
        filled = width
    else:
        pct = min(100, max(0, int((current / total) * 100)))
        filled = int((pct / 100.0) * width)
    unfilled = width - filled
    bar = "█" * filled + "░" * unfilled
    return f"[{bar}] {pct:>3}%"


# ---------------------------------------------------------------- catalog ---
class CatalogEntry:
    """One repo from repos.catalog."""
    def __init__(self, name, fields):
        self.name = name
        self.cat = fields.get("cat", "Other")
        self.kind = fields.get("kind", "")
        self.ids = fields.get("ids", "")
        self.id_list = [i for i in self.ids.split() if i]
        self.copr = fields.get("copr", "")
        self.url = fields.get("url", "")
        self.pkg = fields.get("pkg", "")
        self.file = fields.get("file", "")
        self.key = fields.get("key", "")
        self.content = fields.get("content", "")
        self.remote = fields.get("remote", "")
        self.top = fields.get("top", "")
        self.info = fields.get("info", "")
        self.warn = fields.get("warn", "")
        self.setup = fields.get("setup", "")
        self.testing = fields.get("testing", "no") == "yes"
        self.required = fields.get("required", "no") == "yes"
        self.needs = fields.get("needs", "")

    def is_refused(self):
        return self.name in REFUSED or "REFUSED" in self.setup

    def is_required(self):
        return self.required or self.name in REQUIRED

    def is_testing(self):
        return self.testing

    def display_status(self, is_on):
        if self.is_refused():
            return "REF"
        if self.is_required():
            return "REQ"
        if self.is_testing():
            return "TST"
        return "ON" if is_on else "OFF"


def load_catalog(path):
    """Parse the INI-style repos.catalog into a dict of CatalogEntry."""
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
class DnfConf:
    """Parsed view of /etc/dnf/dnf.conf [main] plus the edits we know how to make."""

    def __init__(self, text):
        self.orig = text
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.splitlines()
        self.values = {}   # key -> value (or None if commented out / absent)
        self._scan()

    def _scan(self):
        in_main = False
        for line in self.lines:
            m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
            if m:
                in_main = m.group(1) == "main"
                continue
            if not in_main:
                continue
            km = re.match(r"^\s*#?\s*([A-Za-z0-9_-]+)\s*=\s*(.*?)\s*$", line)
            if km:
                key = km.group(1)
                commented = line.lstrip().startswith("#")
                self.values[key] = None if commented else km.group(2)

    def value(self, key):
        return self.values.get(key)

    def render(self, options):
        """Return the new dnf.conf text with options applied."""
        lines = list(self.lines)
        start = next((i for i, l in enumerate(lines) if l.strip() == "[main]"), None)
        if start is None:
            raise ValueError("Missing [main] section in dnf.conf")
        end = next((i for i in range(start + 1, len(lines))
                    if re.match(r"^\s*\[", lines[i])), len(lines))
        # Remove existing [main] keys we manage, then re-insert with new values.
        keep = []
        for i in range(start + 1, end):
            km = re.match(r"^\s*#?\s*([A-Za-z0-9_-]+)\s*=", lines[i])
            if km and km.group(1) in options:
                continue
            keep.append(lines[i])
        # Insert managed keys right after [main], grouped by category.
        changed = []          # (group, key, value) in definition order
        groups_with_changes = []
        for entry in ALL_OPTIONS:
            key, group, _t, _default, _expl, _choices, _val = entry
            if key not in options:
                continue
            if group not in groups_with_changes:
                groups_with_changes.append(group)
            changed.append((group, key, options[key]))
        inserted = []
        emitted_group = None
        for group, key, val in changed:
            if group != emitted_group:
                inserted.append(f"# --- {group} ---")
                emitted_group = group
            if val is None:
                inserted.append(f"#{key}=")
            elif val is True:
                inserted.append(f"{key}=True")
            elif val is False:
                inserted.append(f"{key}=False")
            else:
                inserted.append(f"{key}={val}")
        new_lines = lines[:start + 1] + inserted + ([""] if inserted else []) + keep + lines[end:]
        return self.newline.join(new_lines)


def scan_repos(repo_dir):
    """Scan /etc/yum.repos.d/*.repo and return {id: {enabled, file, sections}}."""
    repos = {}
    if not os.path.isdir(repo_dir):
        return repos
    for path in sorted(Path(repo_dir).glob("*.repo")):
        try:
            text = path.read_text()
        except OSError:
            continue
        cp = configparser.ConfigParser()
        cp.read_string(text)
        for section in cp.sections():
            enabled = cp.getboolean(section, "enabled", fallback=True)
            repo_id = cp.get(section, "repoid", fallback=section)
            repos[repo_id] = {
                "enabled": enabled,
                "file": str(path),
                "section": section,
                "baseurl": cp.get(section, "baseurl", fallback=""),
                "metalink": cp.get(section, "metalink", fallback=""),
                "mirrorlist": cp.get(section, "mirrorlist", fallback=""),
            }
    return repos


# ---------------------------------------------------------------- state ---
class State:
    def __init__(self, conf_path, repo_dir, catalog_path, live=False):
        self.conf_path = conf_path
        self.repo_dir = repo_dir
        self.catalog = load_catalog(catalog_path)
        with open(conf_path, newline="") as f:
            self.dnf_conf = DnfConf(f.read())
        self.repos = scan_repos(repo_dir)
        self.live = live
        self.live_status = {}   # repo_name -> "live OK" / "no aarch64" / "unreachable"
        self.repo_enabled = {n: (self.repos[n]["enabled"] if n in self.repos else False)
                             for n in self._all_repo_names()}
        self.adds = set()       # catalog repos not in files that user wants enabled
        self.options = {}       # key -> value overrides
        self.reviewed_hash = None
        self.quitting = False

    def _all_repo_names(self):
        names = set(self.repos)
        names |= set(self.catalog)
        return sorted(names)

    def all_rows(self):
        """All repo rows: existing repos first, then catalog-only repos."""
        out = []
        for n in sorted(self.repos):
            out.append((n, "file"))
        for n in sorted(self.catalog):
            if n not in self.repos:
                out.append((n, "catalog"))
        return out

    def is_on(self, name):
        if name in self.repos:
            return self.repo_enabled.get(name, self.repos[name]["enabled"])
        return name in self.adds

    def is_managed(self, name):
        """True if this repo appears in the catalog (we know how to toggle it)."""
        return name in self.catalog

    def toggle(self, name):
        ent = self.catalog.get(name)
        if ent is None:
            return f"[{name}] is not in the catalog — edit /etc/yum.repos.d/*.repo manually."
        if ent.is_refused():
            reason = REFUSED_REASONS.get(name, ent.setup or "Incompatible with Apple Silicon Asahi Linux.")
            return f"[{name}] is REFUSED: {reason}"
        if ent.is_required() and self.is_on(name):
            return f"[{name}] is REQUIRED on Asahi and cannot be disabled."
        if name in self.repos:
            self.repo_enabled[name] = not self.repo_enabled[name]
        else:
            self.adds ^= {name}
        # dependency: rpmfusion-free-tainted needs rpmfusion-free
        if ent.needs and self.is_on(name) and not self.is_on(ent.needs):
            self.adds.add(ent.needs)
            return (f"[{name}] needs [{ent.needs}] — enabling [{ent.needs}] too. "
                    f"Toggle [{ent.needs}] off later to remove it.")
        return ""

    def set_option(self, key, value):
        if value is not None:
            if key in FLAGS:
                if isinstance(value, str):
                    if value.lower() in ("true", "1", "yes", "on"):
                        value = True
                    elif value.lower() in ("false", "0", "no", "off"):
                        value = False
                    else:
                        raise ValueError("Flag options accept on/off or True/False only.")
                elif value is not True and value is not False:
                    raise ValueError("Flag options accept on/off or True/False only.")
            else:
                if not isinstance(value, str):
                    value = str(value)
                if not value or not value.strip():
                    raise ValueError("Enter a nonempty value.")
                if "\n" in value or "\r" in value or "\x00" in value:
                    raise ValueError("Value must be a single line.")
                t = next((t for k, _, t, _, _, _, _ in ALL_OPTIONS if k == key), "text")
                if t.startswith("int:"):
                    lo, hi = map(int, t[4:].split(":"))
                    if not value.isdecimal() or not (lo <= int(value) <= hi):
                        raise ValueError(f"Must be an integer between {lo} and {hi}.")
                if key == "metadata_expire":
                    if not re.fullmatch(r"([0-9]+[smhd]?|-1|never)", value):
                        raise ValueError("Use seconds, 6h-style, -1 or never.")
                if key.startswith("color_"):
                    for word in value.split(","):
                        if word.strip() not in DNF_COLOR_WORDS:
                            raise ValueError(f"'{word.strip()}' isn't a dnf5 color word.")
        trial = dict(self.options, **{key: value})
        self.dnf_conf.render(trial)  # validate render works
        self.options = trial

    def unset_option(self, key):
        """Revert an option to default (comments it out in dnf.conf)."""
        self.set_option(key, None)

    def option_value(self, key):
        if key in self.options:
            return self.options[key]
        return self.dnf_conf.value(key)

    def changed(self):
        return self.changes_count() > 0

    def changes_count(self):
        """Accurate count of staged mutations (dnf.conf overrides + repo toggles)."""
        count = 0
        for k, v in self.options.items():
            orig_v = self.dnf_conf.value(k)
            if str(v) != str(orig_v):
                count += 1
        count += len(self.adds)
        for n in self.repo_enabled:
            was_on = self.repos[n]["enabled"] if n in self.repos else False
            if self.repo_enabled[n] != was_on:
                count += 1
        return count

    def proposed_conf(self):
        return self.dnf_conf.render(self.options)

    def fingerprint(self):
        content = self.proposed_conf() + "\n" + "\n".join(
            f"{n}:{self.is_on(n)}" for n in sorted(self._all_repo_names())
        )
        return hashlib.sha256(content.encode()).hexdigest()

    # ---------------------------------------------------------------- repo commands ---
    def repo_cmds(self, name, enable):
        """Return the shell commands to enable/disable a catalog repo."""
        ent = self.catalog[name]
        k = ent.kind
        sudo = "sudo "
        if k == "builtin":
            action = "setopt %s.enabled=1" if enable else "setopt %s.enabled=0"
            return [f"{sudo}dnf config-manager {action % i}" for i in ent.id_list]
        if k == "copr":
            action = "enable" if enable else "disable"
            return [f"{sudo}dnf copr {action} {ent.copr}"]
        if k == "rpm":
            if enable:
                return [f"{sudo}dnf install -y {ent.url.format(FEDORA=self._fedora())}"]
            return [f"{sudo}dnf remove -y {ent.pkg}"]
        if k == "repofile":
            if enable:
                return [f"{sudo}dnf config-manager addrepo --from-repofile={ent.url}"]
            return [f"{sudo}rm -f {ent.file}"]
        if k == "repofile-inline":
            if enable:
                cmds = []
                if ent.key:
                    cmds.append(f"{sudo}rpm --import {ent.key}")
                cmds.append(f"printf '%b\\n' {shlex.quote(ent.content)} | {sudo}tee {ent.file} >/dev/null")
                return cmds
            return [f"{sudo}rm -f {ent.file}"]
        if k == "terra":
            if enable:
                return [f"{sudo}dnf install --repofrompath 'terra,https://repos.fyralabs.com/terra$releasever' "
                        f"--setopt='terra.gpgkey=https://repos.fyralabs.com/terra$releasever/key.asc' terra-release"]
            return [f"{sudo}dnf remove -y terra-release"]
        if k == "flatpak":
            action = "remote-add --if-not-exists" if enable else "remote-delete"
            return [f"{sudo}flatpak {action} {ent.remote} {ent.url}"]
        return []

    def _fedora(self):
        try:
            return subprocess.run(["rpm", "-E", "%fedora"], capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        except Exception:
            return ""

    # ---------------------------------------------------------------- prerequisites ---
    def prereqs(self):
        """Commands to run before installing the new config (key imports, keyrings)."""
        cmds = []
        newly = [n for n in self._all_repo_names() if self.is_on(n)
                 and n not in REQUIRED
                 and (n not in self.repos or not self.repos[n]["enabled"])]
        for n in newly:
            ent = self.catalog.get(n)
            if not ent:
                continue
            if ent.kind == "copr" and ent.copr:
                cmds.append(f"dnf copr enable {ent.copr}")
            if ent.kind == "rpm" and ent.url:
                cmds.append(f"dnf install -y {ent.url.format(FEDORA=self._fedora())}")
            if ent.kind == "repofile-inline" and ent.key:
                cmds.append(f"rpm --import {ent.key}")
        return list(dict.fromkeys(cmds))

    def warnings(self):
        w = []
        for n in self._all_repo_names():
            if not self.is_on(n):
                continue
            ent = self.catalog.get(n)
            if ent and ent.warn:
                w.append(f"[{n}] {ent.warn}")
            if ent and ent.is_testing():
                w.append(f"[{n}] testing repository — pre-release packages.")
        for key in ("gpgcheck",):
            v = self.option_value(key)
            if isinstance(v, str) and v.lower() in ("false", "0"):
                w.append(f"{key} weakens signature verification: {v}")
        return w

    def problems(self):
        out = []
        enabled = {n for n in self._all_repo_names() if self.is_on(n)}
        if "updates-testing" in enabled and "updates" not in enabled:
            out.append("[updates-testing] requires [updates] to be enabled.")
        if "asahi-alpha" in enabled:
            out.append("[asahi-alpha] is a personal testing repo — its author says everyone else should avoid it.")
        if "rpmfusion-free-tainted" in enabled and "rpmfusion-free" not in enabled:
            out.append("[rpmfusion-free-tainted] needs [rpmfusion-free] enabled too.")
        return out

    def check_live(self, name, force=False):
        """Check a repo's aarch64 build status (used with --live)."""
        if not self.live and not force:
            return "(skip --live)"
        if name in self.live_status and not force:
            return self.live_status[name]
        ent = self.catalog.get(name)
        if not ent:
            self.live_status[name] = "not in catalog"
            return self.live_status[name]
        try:
            if ent.kind == "copr" and ent.copr:
                own, proj = ent.copr.split("/", 1) if "/" in ent.copr else ("", ent.copr)
                r = subprocess.run(
                    ["curl", "-sf", "--max-time", "8",
                     f"https://copr.fedorainfracloud.org/api_3/project?ownername={own}&projectname={proj}"],
                    capture_output=True, text=True, timeout=10)
                fedora = self._fedora()
                if r.returncode == 0 and f"fedora-{fedora}-aarch64" in r.stdout:
                    self.live_status[name] = f"aarch64 build OK (fedora-{fedora})"
                else:
                    self.live_status[name] = f"no fedora-{fedora}-aarch64 chroot found"
            elif ent.kind == "repofile" and ent.url:
                base = subprocess.run(
                    ["curl", "-sf", "--max-time", "8", ent.url],
                    capture_output=True, text=True, timeout=10).stdout
                m = re.search(r"^baseurl *= *(.*)$", base, re.M)
                if m:
                    baseurl = m.group(1).replace("$basearch", "aarch64").replace("$releasever", self._fedora())
                    r = subprocess.run(["curl", "-sIL", "--max-time", "8", baseurl.rstrip("/") + "/repodata/repomd.xml"],
                                       capture_output=True, text=True, timeout=10)
                    code = ""
                    for line in r.stderr.splitlines():
                        if line.startswith("HTTP/"):
                            code = line.split()[1] if len(line.split()) > 1 else ""
                    lm = ""
                    for line in r.stderr.splitlines():
                        if line.lower().startswith("last-modified:"):
                            lm = line.split(":", 1)[1].strip()
                    if code == "200":
                        self.live_status[name] = f"aarch64 repo reachable (HTTP 200, {lm or '?'})"
                    else:
                        self.live_status[name] = f"no aarch64 repodata (HTTP {code or 'none'})"
                else:
                    self.live_status[name] = "could not read baseurl from .repo file"
            elif ent.kind == "rpm" and ent.url:
                url = ent.url.format(FEDORA=self._fedora())
                r = subprocess.run(["curl", "-sIL", "--max-time", "8", "-o", "/dev/null", "-w", "%{http_code}", url],
                                   capture_output=True, text=True, timeout=10)
                if r.stdout.strip() == "200":
                    self.live_status[name] = "release package exists (HTTP 200)"
                else:
                    self.live_status[name] = f"release package not found (HTTP {r.stdout.strip() or 'none'})"
            else:
                self.live_status[name] = "no live check for this kind"
        except Exception as e:
            self.live_status[name] = f"check failed ({e})"
        return self.live_status[name]

    def review_lines(self):
        lines = [
            "Review the complete mutation plan and configuration diff.",
            "Scroll to the end to complete review and unlock the dry-run gate.",
            ""
        ]
        probs = self.problems()
        warns = self.warnings()
        prereqs = self.prereqs() if os.path.realpath(self.conf_path) == DEFAULT_CONF else []

        if probs:
            lines.append("--- BLOCKED ISSUES ---")
            lines += ["BLOCKED: " + p for p in probs]
            lines.append("")
        if warns:
            lines.append("--- SAFETY WARNINGS ---")
            lines += ["WARNING: " + w for w in warns]
            lines.append("")
        if prereqs:
            lines.append("--- PREREQUISITES ---")
            lines += ["Prerequisites: $ " + c for c in prereqs]
            lines.append("")

        lines.append("--- REPOSITORY MUTATION PLAN ---")
        repo_changes = 0
        for n in self._all_repo_names():
            was_on = self.repos[n]["enabled"] if n in self.repos else False
            now_on = self.is_on(n)
            if was_on != now_on:
                repo_changes += 1
                action = f"ENABLE  [{n}]" if now_on else f"DISABLE [{n}]"
                ent = self.catalog.get(n)
                kind_info = f" ({ent.kind})" if ent and ent.kind else ""
                lines.append(f"  • {action}{kind_info}")
        if repo_changes == 0:
            lines.append("  (no repository changes)")
        lines.append("")

        lines.append("--- DNF.CONF CONFIGURATION DIFF ---")
        diff_lines = list(difflib.unified_diff(
            self.dnf_conf.orig.splitlines(),
            self.proposed_conf().splitlines(),
            fromfile=self.conf_path,
            tofile=self.conf_path + " (proposed)",
            lineterm="", n=2))
        if diff_lines:
            lines += diff_lines
        else:
            lines.append("  (no dnf.conf changes)")
        lines.append("")
        lines.append("--- END OF REVIEW PLAN ---")
        return lines


# ---------------------------------------------------------------- apply ---
def is_root():
    return os.geteuid() == 0


def run_cmd(cmd, log):
    """Run *cmd* (argv list or command string), log it once, return its exit code.

    A string containing a pipe (e.g. the repofile-inline ``printf | sudo tee``
    writer) goes through ``bash -c``; everything else is split without a shell.
    """
    log("$ " + (" ".join(cmd) if isinstance(cmd, list) else str(cmd)))
    if isinstance(cmd, str):
        cmd = ["bash", "-c", cmd] if "|" in cmd else shlex.split(cmd)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and r.stderr.strip():
        log(r.stderr.strip())
    return r.returncode


def apply_changes(state, log, confirm=input):
    """Back up, validate, dry-run gate, install. Returns bool."""
    new_conf = state.proposed_conf()
    path = state.conf_path

    if state.reviewed_hash != state.fingerprint():
        log("Review the current diff before applying.")
        return False
    if Path(path).read_bytes() != state.dnf_conf.orig.encode():
        log("Source changed on disk. Reopen before applying.")
        return False
    if state.problems():
        log("\n".join(state.problems()))
        return False

    live = os.path.realpath(path) == DEFAULT_CONF
    if live:
        try:
            osr = Path("/etc/os-release").read_text()
            if not re.search(r'^ID=["\']?fedora["\']?$', osr, re.M):
                log("Live apply targets /etc/dnf/dnf.conf but this isn't Fedora.")
                return False
        except OSError:
            pass
    try:
        if live and state.warnings() and confirm("Confirm all displayed warnings? [y/N] ").lower() != "y":
            return False
        if live and confirm(f"Apply this reviewed configuration to {path}? [y/N] ").lower() != "y":
            return False
    except (EOFError, KeyboardInterrupt):
        log("\nApply cancelled.")
        return False

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = f"{path}.bak-{stamp}"
    sudo = [] if (is_root() or os.access(path, os.W_OK)) else ["sudo"]

    def run(cmd):
        return run_cmd(cmd, log)

    # 1. Validate the new dnf.conf with dnf (read-only repolist).
    fd, tmp = tempfile.mkstemp(prefix="dnf.conf.", dir=tempfile.gettempdir())
    with os.fdopen(fd, "w") as f:
        f.write(new_conf)
    os.chmod(tmp, 0o644)
    try:
        if shutil.which("dnf"):
            r = subprocess.run(["dnf", "--config", tmp, "repolist", "--quiet"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                log("!! dnf rejected the new configuration:\n" + (r.stderr or r.stdout))
                return False
            log("dnf accepts the new configuration.")
        if Path(path).read_bytes() != state.dnf_conf.orig.encode():
            log("Source changed during preparation. Reopen before applying.")
            return False
        if run(sudo + ["cp", "-p", path, backup]) != 0:
            log("!! backup failed — config untouched.")
            return False
        log(f"backup: {backup}")
        if run(sudo + ["install", "-m644", tmp, path]) != 0:
            log("!! install failed — config untouched (backup kept).")
            return False
    finally:
        os.unlink(tmp)

    # 2. Apply repo enable/disable commands.
    plan = []
    for n in state._all_repo_names():
        was_on = self_state_repos(state, n)
        now_on = state.is_on(n)
        if was_on == now_on:
            continue
        plan.append((n, now_on))
    for n, enable in plan:
        ent = state.catalog.get(n)
        if not ent or ent.is_refused():
            log(f"[{n}] skipped (refused or unmanaged).")
            continue
        log(f"  -- {'enable' if enable else 'disable'} [{n}]")
        for c in state.repo_cmds(n, enable):
            # repo_cmds() already prefixes "sudo "; drop it when running as root
            # and never stack a second one on top.
            if is_root():
                c = re.sub(r"^sudo ", "", c).replace(" | sudo tee", " | tee")
            if run(c) != 0:
                log(f"!! command failed: {c}")
                run(sudo + ["cp", "-p", backup, path])
                log("!! rolled back dnf.conf to backup")
                return False

    if live:
        run(sudo + ["dnf", "makecache", "--refresh"])
    log(f"Applied. Undo dnf.conf: sudo cp {backup} {path}")
    log("Repo changes are undone with the opposite enable/disable in this deck.")
    return True


def self_state_repos(state, n):
    return state.repos[n]["enabled"] if n in state.repos else False


# ---------------------------------------------------------------- Box Drawing Helpers ---
PAIR_DEFAULT = 0
PAIR_GREEN = 1      # ON / good / additions / verified
PAIR_RED = 2        # OFF / refused / deletions / errors
PAIR_YELLOW = 3     # required / testing / modified / warnings
PAIR_CYAN = 4       # headers / info / hunks / host
PAIR_MAGENTA = 5    # selected / active chip
PAIR_BLUE = 6       # frame borders / secondary accents
PAIR_ALERT = 7      # white on red (critical warnings)
PAIR_STATUS = 8     # black on cyan (status pill)
PAIR_VERIFIED = 9   # black on green (dry-run gate unlocked)
PAIR_DIM = 10       # dim / inactive


def draw_box(scr, y, x, h, w, title="", color=0, title_color=0, subtitle="", subtitle_color=0):
    """Draw a clean rounded Unicode box frame with optional title and subtitle."""
    max_h, max_w = scr.getmaxyx()
    if y >= max_h or x >= max_w or h < 2 or w < 2:
        return
    actual_h = min(h, max_h - y)
    actual_w = min(w, max_w - x)
    if actual_h < 2 or actual_w < 2:
        return

    # Top border
    top_bar = "╭" + ("─" * (actual_w - 2)) + "╮"
    try:
        scr.addnstr(y, x, top_bar, actual_w, color)
    except curses.error:
        pass

    # Title
    if title and actual_w > len(title) + 6:
        t_text = f" {title} "
        t_attr = title_color or color
        try:
            scr.addnstr(y, x + 2, t_text, actual_w - 4, t_attr)
        except curses.error:
            pass

    # Subtitle (right-aligned)
    if subtitle and actual_w > len(title or "") + len(subtitle) + 8:
        sub_pos = x + actual_w - len(subtitle) - 4
        s_text = f" {subtitle} "
        s_attr = subtitle_color or color
        try:
            scr.addnstr(y, sub_pos, s_text, len(s_text), s_attr)
        except curses.error:
            pass

    # Side borders
    for row in range(y + 1, y + actual_h - 1):
        try:
            scr.addnstr(row, x, "│", 1, color)
            scr.addnstr(row, x + actual_w - 1, "│", 1, color)
        except curses.error:
            pass

    # Bottom border
    bot_bar = "╰" + ("─" * (actual_w - 2)) + "╯"
    bot_y = y + actual_h - 1
    try:
        if bot_y == max_h - 1 and (x + actual_w) >= max_w:
            scr.addnstr(bot_y, x, bot_bar[:-1], actual_w - 1, color)
        else:
            scr.addnstr(bot_y, x, bot_bar, actual_w, color)
    except curses.error:
        pass


def draw_divider_h(scr, y, x, w, color=0, label=""):
    """Draw a horizontal divider line with optional embedded label."""
    max_h, max_w = scr.getmaxyx()
    if y >= max_h or x >= max_w or w < 2:
        return
    actual_w = min(w, max_w - x)
    line = "├" + ("─" * (actual_w - 2)) + "┤"
    try:
        scr.addnstr(y, x, line, actual_w, color)
        if label and actual_w > len(label) + 6:
            scr.addnstr(y, x + 2, f" {label} ", actual_w - 4, color)
    except curses.error:
        pass


# ---------------------------------------------------------------- TUI ---
class UI:
    def __init__(self, scr, state, mode="choose"):
        self.scr = scr
        self.s = state
        self.mode = mode
        self.tab = 0          # 0 options, 1 repos, 2 review
        self.cursor = [0, 0, 0]
        self.offset = [0, 0, 0]
        self.search = ["", "", ""]
        self.category = ["All", "All", "All"]
        self.msg = "Click rows or press Enter to edit. Tab switches panes. ? opens Help."
        self.msg_type = "info"
        self.hits = []
        self.visible_rows = [[], [], []]
        self.detail_offset = [0, 0, 0]
        self.live_status = {}
        self.show_help = False
        self.choose_cursor = 0
        self.hw_badge = get_hardware_badge()
        self.hostname = get_hostname()

        try:
            curses.curs_set(0)
        except curses.error:
            pass

        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(50)
        except curses.error:
            pass

        self.scr.keypad(True)
        self._init_colors()

    def _init_colors(self):
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            curses.init_pair(PAIR_GREEN, curses.COLOR_GREEN, bg)
            curses.init_pair(PAIR_RED, curses.COLOR_RED, bg)
            curses.init_pair(PAIR_YELLOW, curses.COLOR_YELLOW, bg)
            curses.init_pair(PAIR_CYAN, curses.COLOR_CYAN, bg)
            curses.init_pair(PAIR_MAGENTA, curses.COLOR_MAGENTA, bg)
            curses.init_pair(PAIR_BLUE, curses.COLOR_BLUE, bg)
            curses.init_pair(PAIR_ALERT, curses.COLOR_WHITE, curses.COLOR_RED)
            curses.init_pair(PAIR_STATUS, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(PAIR_VERIFIED, curses.COLOR_BLACK, curses.COLOR_GREEN)
            curses.init_pair(PAIR_DIM, curses.COLOR_WHITE, bg)
        except curses.error:
            pass

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and 0 <= x < w - 1:
            try:
                self.scr.addnstr(y, x, str(text), w - x - 1, attr)
            except curses.error:
                pass

    def button(self, y, x, label, action, attr=curses.A_REVERSE):
        self.put(y, x, label, attr)
        self.hits.append((y, x, x + len(label), action))

    def toast(self, message, msg_type="info"):
        self.msg = message
        self.msg_type = msg_type

    def attr_for_status(self, status):
        if status == "ON":
            return curses.color_pair(PAIR_GREEN) | curses.A_BOLD
        if status in ("OFF", "REF"):
            return curses.color_pair(PAIR_RED) | curses.A_BOLD
        if status in ("REQ", "TST"):
            return curses.color_pair(PAIR_YELLOW) | curses.A_BOLD
        return 0

    def value_attr(self, key, value):
        """Color attribute for setting value in the options list."""
        if value is None:
            return curses.color_pair(PAIR_DIM)
        default = RECOMMENDED.get(key, "")
        if key == "gpgcheck" and str(value).lower() in ("false", "0"):
            return curses.color_pair(PAIR_RED) | curses.A_BOLD
        if str(value) != str(default):
            return curses.color_pair(PAIR_YELLOW) | curses.A_BOLD
        return curses.color_pair(PAIR_GREEN)

    def rows(self, tab):
        if tab == 0:
            cat = self.category[tab]
            s = self.search[tab].lower()
            return [o[0] for o in ALL_OPTIONS
                    if (cat == "All" or o[1] == cat)
                    and s in " ".join(str(x) for x in o if x is not None).lower()]
        if tab == 1:
            cat = self.category[tab]
            s = self.search[tab].lower()
            out = []
            for n, src in self.s.all_rows():
                ent = self.s.catalog.get(n)
                cname = ent.cat if ent else "Installed / official"
                info = (ent.info if ent else "Repository in the opened configuration.")
                if cat != "All" and cname != cat:
                    continue
                if s and s not in (n + " " + cname + " " + info).lower():
                    continue
                out.append((n, src))
            return out
        return []

    def meta(self, name):
        return self.s.catalog.get(name)

    def detail(self, tab, name):
        if tab == 0:
            opt = next((o for o in ALL_OPTIONS if o[0] == name), None)
            if not opt:
                return ["Unknown option."]
            key, group, typ, default, expl, choices, _ = opt
            value = self.s.option_value(key)
            rec = RECOMMENDED.get(key, default)
            val_disp = "(unset — default)" if value is None else str(value)

            lines = [
                f"Option: {key}",
                f"Group: {group}   Type: {typ}",
                f"Current: {val_disp}",
                f"Recommended: {rec}   Built-in Default: {default}",
                f"Allowed Choices: {choices}",
                "",
                "Description:",
                expl,
            ]
            if str(value) != str(rec) and value is not None:
                lines.append("")
                lines.append("Notice: Current setting differs from recommended value.")
            if key == "gpgcheck" and str(value).lower() in ("false", "0"):
                lines.append("")
                lines.append("CRITICAL: gpgcheck is DISABLED. Signature validation disabled!")
            return lines

        if tab == 1:
            ent = self.meta(name)
            if not ent:
                r = self.s.repos[name]
                on = "ON" if r["enabled"] else "OFF"
                return [
                    f"Repository: [{name}]",
                    "Category: Installed / official",
                    f"Status: {on} (source file: {r['file']})",
                    f"Base URL: {r['baseurl'] or '(none)'}",
                    f"Mirror List: {r['mirrorlist'] or '(none)'}",
                    "Notice: External uncataloged repo — edit .repo file directly.",
                    f"Live Status: {self.live_status.get(name, '(press L to probe)')}",
                ]

            status_str = ent.display_status(self.s.is_on(name))
            lines = [
                f"Repository: [{name}]",
                f"Category: {ent.cat}   Kind: {ent.kind}",
                f"Status: {status_str}   Top Packages: {ent.top or '(unspecified)'}",
                f"Repo Identifiers: {ent.ids or '(none)'}",
            ]
            if ent.copr:
                lines.append(f"COPR: {ent.copr}")
            if ent.url:
                lines.append(f"URL: {ent.url}")
            if ent.pkg:
                lines.append(f"RPM Package: {ent.pkg}")
            if ent.file:
                lines.append(f"Repo File: {ent.file}")
            if ent.key:
                lines.append(f"GPG Key: {ent.key}")
            if ent.needs:
                lines.append(f"Dependency: Needs [{ent.needs}]")

            lines.append("")
            lines.append("Description:")
            lines.append(ent.info)

            if ent.is_refused():
                lines.append("")
                lines.append("APPLE SILICON HARDWARE PROTECTION:")
                reason = REFUSED_REASONS.get(name, ent.setup or "Incompatible with Apple Silicon.")
                lines.append(f"REFUSED: {reason}")
            elif ent.is_required():
                lines.append("")
                lines.append("MANDATORY SYSTEM COMPONENT:")
                lines.append("Required for Fedora Asahi Remix operations. Deactivation locked.")
            elif ent.is_testing():
                lines.append("")
                lines.append("TESTING REPOSITORY: Contains pre-release packages.")

            if ent.warn:
                lines.append("")
                lines.append(f"Warning: {ent.warn}")

            lines.append("")
            live_stat = self.live_status.get(name, "(press L to probe aarch64 build)")
            lines.append(f"Live Build: {live_stat}")

            on = self.s.is_on(name)
            cmds = self.s.repo_cmds(name, not on) if ent and not ent.is_refused() and not ent.is_required() else []
            if cmds:
                lines.append("")
                lines.append(f"Shell command to {'enable' if not on else 'disable'}:")
                for c in cmds:
                    lines.append("  $ " + c)

            return lines
        return []

    def prompt(self, label, initial="", allowed="", choices=""):
        """Clean modal input dialog for setting values."""
        value, pos = initial, len(initial)
        h, w = self.scr.getmaxyx()
        dialog_w = min(68, max(46, w - 6))
        dialog_h = 7
        dialog_y = max(2, (h - dialog_h) // 2)
        dialog_x = max(2, (w - dialog_w) // 2)

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            while True:
                draw_box(self.scr, dialog_y, dialog_x, dialog_h, dialog_w,
                         title=f"Edit: {label}",
                         color=curses.color_pair(PAIR_CYAN),
                         title_color=curses.color_pair(PAIR_CYAN) | curses.A_BOLD)

                hint_line = ""
                if allowed or choices:
                    hint_line = f"Allowed: {allowed}" if allowed else ""
                    if choices:
                        hint_line += f"  Choices: {choices}" if hint_line else f"Choices: {choices}"
                if hint_line:
                    self.put(dialog_y + 1, dialog_x + 3, hint_line[:dialog_w - 6], curses.color_pair(PAIR_DIM))

                self.put(dialog_y + 3, dialog_x + 3, "Value: ", curses.A_BOLD)
                val_start_x = dialog_x + 10
                avail_val_w = dialog_w - 14

                start_idx = max(0, pos - avail_val_w + 1)
                disp_val = value[start_idx:start_idx + avail_val_w]
                disp_field = disp_val + " " * max(0, avail_val_w - len(disp_val))
                self.put(dialog_y + 3, val_start_x, disp_field, curses.A_REVERSE)

                self.put(dialog_y + 5, dialog_x + 3, "[Enter] Confirm   [Esc] Cancel   [Arrows] Navigate", curses.color_pair(PAIR_DIM))

                cursor_col = val_start_x + (pos - start_idx)
                try:
                    self.scr.move(dialog_y + 3, min(val_start_x + avail_val_w - 1, cursor_col))
                except curses.error:
                    pass
                self.scr.refresh()

                try:
                    k = self.scr.get_wch()
                except (curses.error, OSError, KeyboardInterrupt):
                    return None

                if k in ("\n", "\r", curses.KEY_ENTER):
                    return value
                if k == "\x1b":
                    return None
                if k == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif k == curses.KEY_RIGHT:
                    pos = min(len(value), pos + 1)
                elif k == curses.KEY_HOME:
                    pos = 0
                elif k == curses.KEY_END:
                    pos = len(value)
                elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    if pos > 0:
                        value = value[:pos - 1] + value[pos:]
                        pos -= 1
                elif k == curses.KEY_DC:
                    if pos < len(value):
                        value = value[:pos] + value[pos + 1:]
                elif isinstance(k, str) and k.isprintable():
                    value = value[:pos] + k + value[pos:]
                    pos += 1
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def switch(self, tab):
        self.tab = tab
        self.offset[tab] = 0
        self.detail_offset[tab] = 0
        self.category[tab] = "All"
        self.search[tab] = ""

    def set_category(self, cat):
        self.category[self.tab] = cat
        self.cursor[self.tab] = 0
        self.offset[self.tab] = 0
        self.detail_offset[self.tab] = 0

    def toggle_help(self):
        self.show_help = not self.show_help

    def check_live(self, name):
        """Check a repo's aarch64 build status (used with --live)."""
        res = self.s.check_live(name, force=True)
        self.live_status[name] = res
        return res

    def review_lines(self):
        return self.s.review_lines()

    def draw_help(self):
        h, w = self.scr.getmaxyx()
        modal_w = min(74, w - 4)
        modal_h = min(22, h - 2)
        start_y = max(1, (h - modal_h) // 2)
        start_x = max(1, (w - modal_w) // 2)

        draw_box(self.scr, start_y, start_x, modal_h, modal_w,
                 title=" ASAHI CONTROL DECK CONTROLS",
                 color=curses.color_pair(PAIR_CYAN),
                 title_color=curses.color_pair(PAIR_CYAN) | curses.A_BOLD,
                 subtitle="[Esc / ? to close]",
                 subtitle_color=curses.color_pair(PAIR_YELLOW))

        help_sections = [
            ("Navigation", [
                ("Tab", "Cycle tabs (Options / Repos / Review)"),
                ("1 / 2 / 3", "Jump directly to tab"),
                ("↑ / ↓", "Navigate rows in active table"),
                ("PgUp / PgDn", "Scroll table by 8 rows"),
                ("Home / End", "Jump to first / last item"),
                ("← / →", "Cycle category filters"),
            ]),
            ("Actions", [
                ("Enter / Space", "Edit option value or toggle repo"),
                ("U", "Unset option (revert to default)"),
                ("/", "Search filter (Esc clears)"),
                ("L", "Run live aarch64 build probe"),
                ("J / K", "Scroll details inspector pane"),
                ("D", "Open Review & Diff tab"),
                ("A", "Apply changes (dry-run gated)"),
                ("? / F1", "Toggle this help dialog"),
                ("Q", "Quit control deck"),
            ]),
        ]

        col1_w = modal_w // 2 - 2
        col2_x = start_x + col1_w + 3
        draw_divider_h(self.scr, start_y + 1, start_x, modal_w, color=curses.color_pair(PAIR_BLUE))

        row_y = start_y + 2
        self.put(row_y, start_x + 3, "Navigation Keys", curses.A_BOLD | curses.color_pair(PAIR_CYAN))
        self.put(row_y, col2_x, "Action Commands", curses.A_BOLD | curses.color_pair(PAIR_CYAN))
        row_y += 1

        nav_items = help_sections[0][1]
        act_items = help_sections[1][1]
        max_rows = max(len(nav_items), len(act_items))

        for idx in range(max_rows):
            cur_y = row_y + idx
            if cur_y >= start_y + modal_h - 6:
                break
            if idx < len(nav_items):
                k_str, desc = nav_items[idx]
                self.put(cur_y, start_x + 3, f"{k_str:<12}", curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)
                self.put(cur_y, start_x + 15, desc[:col1_w - 14], curses.color_pair(PAIR_DIM))
            if idx < len(act_items):
                k_str, desc = act_items[idx]
                self.put(cur_y, col2_x, f"{k_str:<14}", curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)
                self.put(cur_y, col2_x + 14, desc[:modal_w - (col2_x - start_x) - 16], curses.color_pair(PAIR_DIM))

        note_y = start_y + modal_h - 5
        draw_divider_h(self.scr, note_y, start_x, modal_w, color=curses.color_pair(PAIR_BLUE))
        self.put(note_y + 1, start_x + 3, "Safety: Dry-run gate protects disk. Mesa & Asahi kernel locked.", curses.color_pair(PAIR_GREEN))
        self.put(note_y + 2, start_x + 3, "Nothing is written until explicitly applied after diff review.", curses.color_pair(PAIR_DIM))
        self.put(note_y + 3, start_x + (modal_w - 28) // 2, "[Press Any Key or ? to Close]", curses.A_BOLD | curses.color_pair(PAIR_CYAN))

        self.scr.refresh()

    def confirm_quit(self):
        """Ask for confirmation if there are unsaved changes. Returns True to quit."""
        if not self.s.changed():
            return True
        h, w = self.scr.getmaxyx()
        modal_w = min(58, w - 4)
        modal_h = 7
        start_y = max(1, (h - modal_h) // 2)
        start_x = max(1, (w - modal_w) // 2)

        draw_box(self.scr, start_y, start_x, modal_h, modal_w,
                 title="DISCARD CHANGES & QUIT?",
                 color=curses.color_pair(PAIR_RED),
                 title_color=curses.color_pair(PAIR_RED) | curses.A_BOLD)

        changes = self.s.changes_count()
        msg1 = f"You have {changes} unstaged configuration change(s)."
        msg2 = "Exiting will discard all unapplied edits!"
        self.put(start_y + 2, start_x + (modal_w - len(msg1)) // 2, msg1, curses.A_BOLD)
        self.put(start_y + 3, start_x + (modal_w - len(msg2)) // 2, msg2, curses.color_pair(PAIR_YELLOW))

        btn_str = "[Y] Discard & Exit     [N] Keep Editing"
        self.put(start_y + 5, start_x + (modal_w - len(btn_str)) // 2, btn_str, curses.A_BOLD | curses.color_pair(PAIR_CYAN))
        self.scr.refresh()

        while True:
            try:
                k = self.scr.getch()
            except KeyboardInterrupt:
                return True
            except (curses.error, OSError):
                return False
            if k in (ord('y'), ord('Y'), 3):
                return True
            if k in (ord('n'), ord('N'), 27):  # n, N, or Esc
                return False

    def draw_startup_screen(self):
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        self.hits = []

        card_w = min(72, w - 4)
        card_h = 16
        start_y = max(1, (h - card_h) // 2)
        start_x = max(1, (w - card_w) // 2)

        draw_box(self.scr, start_y, start_x, card_h, card_w,
                 title=" ASAHI CONTROL DECK",
                 color=curses.color_pair(PAIR_CYAN),
                 title_color=curses.color_pair(PAIR_CYAN) | curses.A_BOLD,
                 subtitle=self.hw_badge,
                 subtitle_color=curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)

        self.put(start_y + 1, start_x + 3, "Apple Silicon dnf5 Configuration & Repository Deck", curses.A_BOLD)
        self.put(start_y + 2, start_x + 3, f"Host: {self.hostname}  ·  Target: {self.s.conf_path}", curses.color_pair(PAIR_CYAN))

        draw_divider_h(self.scr, start_y + 3, start_x, card_w, color=curses.color_pair(PAIR_BLUE))

        self.put(start_y + 4, start_x + 3, "Select configuration deck mode:", curses.A_BOLD)

        cur = getattr(self, "choose_cursor", 0)

        # Mode 1 button & description
        btn1_attr = (curses.A_REVERSE | curses.color_pair(PAIR_CYAN) | curses.A_BOLD) if cur == 0 else curses.A_BOLD
        self.put(start_y + 6, start_x + 3, "▸" if cur == 0 else " ", curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)
        self.button(start_y + 6, start_x + 5, "[1] One at a time", lambda: self.choose("single"), btn1_attr)
        self.put(start_y + 7, start_x + 9, "Guided step-by-step walk of all dnf.conf options.", curses.color_pair(PAIR_DIM))
        self.put(start_y + 8, start_x + 9, "Recommended for initial tuning and safety verification.", curses.color_pair(PAIR_DIM))

        # Mode 2 button & description
        btn2_attr = (curses.A_REVERSE | curses.color_pair(PAIR_CYAN) | curses.A_BOLD) if cur == 1 else curses.A_BOLD
        self.put(start_y + 10, start_x + 3, "▸" if cur == 1 else " ", curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)
        self.button(start_y + 10, start_x + 5, "[2] Grouped Deck", lambda: self.choose("grouped"), btn2_attr)
        self.put(start_y + 11, start_x + 9, "Full interactive control deck with category filters,", curses.color_pair(PAIR_DIM))
        self.put(start_y + 12, start_x + 9, "instant search, live repo build probes, and deep diffs.", curses.color_pair(PAIR_DIM))

        draw_divider_h(self.scr, start_y + 13, start_x, card_w, color=curses.color_pair(PAIR_BLUE))

        legend = "[1/2] Select   │   [Enter/Space] Launch   │   [Q] Quit"
        self.put(start_y + 14, start_x + (card_w - len(legend)) // 2, legend, curses.color_pair(PAIR_DIM))

        self.scr.refresh()

    def draw_header_and_tabs(self, h, w):
        # Header bar at y = 0
        self.scr.addnstr(0, 0, " " * (w - 1), w - 1, curses.color_pair(PAIR_CYAN) | curses.A_REVERSE)
        head_left = f"  ASAHI CONTROL DECK  │  [{self.hw_badge}]  │  host: {self.hostname}  │  target: {self.s.conf_path}"
        self.put(0, 0, head_left, curses.color_pair(PAIR_CYAN) | curses.A_REVERSE | curses.A_BOLD)

        head_right = f"Mode: {self.mode} │ Live: {'on' if self.s.live else 'off'} "
        if w > len(head_left) + len(head_right) + 2:
            self.put(0, w - len(head_right) - 1, head_right, curses.color_pair(PAIR_CYAN) | curses.A_REVERSE)

        # Tab bar at y = 1
        tabs = [
            ("1 Options", 0),
            ("2 Repos", 1),
            ("3 Review & Diff", 2)
        ]
        cur_x = 1
        for label, tab_idx in tabs:
            is_active = (self.tab == tab_idx)
            icon = "◆" if is_active else "◇"
            btn_text = f" {icon} {label} "
            if is_active:
                attr = curses.A_REVERSE | curses.color_pair(PAIR_CYAN) | curses.A_BOLD
            else:
                attr = curses.color_pair(PAIR_CYAN)
            self.button(1, cur_x, btn_text, lambda t=tab_idx: self.switch(t), attr)
            cur_x += len(btn_text) + 1

        actions = [
            ("[A Apply]", self.do_apply, curses.color_pair(PAIR_GREEN) | curses.A_BOLD),
            ("[? Help]", self.toggle_help, curses.color_pair(PAIR_YELLOW)),
            ("[Q Quit]", lambda: setattr(self, "quitting", True), curses.color_pair(PAIR_RED))
        ]
        right_x = w - 2
        for btn_label, btn_action, btn_attr in reversed(actions):
            right_x -= len(btn_label) + 1
            if right_x > cur_x:
                self.button(1, right_x, btn_label, btn_action, btn_attr)

        # Sub-header / Category Chips Bar at y = 2
        if self.tab in (0, 1):
            if self.tab == 0:
                groups = ["All"] + list(dict.fromkeys(g for _, g, _, _, _, _, _ in ALL_OPTIONS))
            else:
                groups = ["All"] + sorted({e.cat for e in self.s.catalog.values()})

            self.put(2, 1, "Category:", curses.A_BOLD)
            chip_x = 11
            active_cat = self.category[self.tab]
            for grp in groups:
                short_name = grp
                if grp == "Official & Core Overlays": short_name = "Official"
                elif grp == "Dev, Toolchains & Scientific": short_name = "Dev & Tools"
                elif grp == "Prebuilt AUR & Convenience": short_name = "AUR/Prebuilt"
                elif grp == "Desktop, Apps & Pro Audio": short_name = "Desktop"
                elif grp == "Kernels & Graphics Bleeding-Edge": short_name = "Bleeding-Edge"
                elif grp == "Refused / Incompatible": short_name = "Refused"
                elif grp == "Security & Infrastructure": short_name = "Security"

                is_active = (grp == active_cat)
                chip_label = f"[{short_name}]"
                if chip_x + len(chip_label) > w - 30:
                    break
                if is_active:
                    chip_attr = curses.A_REVERSE | curses.color_pair(PAIR_MAGENTA) | curses.A_BOLD
                else:
                    chip_attr = curses.color_pair(PAIR_MAGENTA)
                self.button(2, chip_x, chip_label, lambda g=grp: self.set_category(g), chip_attr)
                chip_x += len(chip_label) + 1

            search_str = self.search[self.tab]
            if search_str:
                s_badge = f"🔍 Search: '{search_str}' (Esc to clear)"
                self.put(2, max(chip_x + 2, w - len(s_badge) - 2), s_badge, curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)
            else:
                changes = self.s.changes_count()
                if changes:
                    c_badge = f"● {changes} change{'s' if changes > 1 else ''} pending"
                    self.put(2, max(chip_x + 2, w - len(c_badge) - 2), c_badge, curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)
                else:
                    c_badge = "○ No pending changes"
                    self.put(2, max(chip_x + 2, w - len(c_badge) - 2), c_badge, curses.color_pair(PAIR_DIM))
        elif self.tab == 2:
            changes = self.s.changes_count()
            prob_count = len(self.s.problems())
            warn_count = len(self.s.warnings())
            is_unlocked = (self.s.reviewed_hash == self.s.fingerprint())
            gate_str = "UNLOCKED" if is_unlocked else "LOCKED (scroll to bottom)"
            gate_attr = curses.color_pair(PAIR_GREEN) if is_unlocked else curses.color_pair(PAIR_YELLOW)
            summary = f"Staged Changes: {changes}  │  Blocked: {prob_count}  │  Warnings: {warn_count}  │  Dry-Run Gate: "
            self.put(2, 1, summary, curses.color_pair(PAIR_DIM))
            self.put(2, 1 + len(summary), gate_str, gate_attr | curses.A_BOLD)

    def draw_options_tab(self, h, w):
        pane_y = 3
        pane_h = h - 5
        rows = self.rows(0)
        self.visible_rows[0] = []

        if not rows:
            draw_box(self.scr, pane_y, 0, pane_h, w - 1, title="dnf.conf Options", color=curses.color_pair(PAIR_BLUE))
            self.put(pane_y + 3, 4, "No settings match current filter. Press Esc or '/' to clear search.", curses.color_pair(PAIR_YELLOW))
            return

        self.cursor[0] = max(0, min(self.cursor[0], len(rows) - 1))
        cur_idx = self.cursor[0]
        cur_key = rows[cur_idx]

        is_split = (w >= 105)
        if is_split:
            w_left = int(w * 0.52)
            w_right = w - w_left - 1

            # Left Pane: Table
            draw_box(self.scr, pane_y, 0, pane_h, w_left,
                     title="dnf.conf Settings",
                     color=curses.color_pair(PAIR_BLUE),
                     subtitle=f"{len(rows)} options")

            hdr_key_w = max(18, w_left - 38)
            hdr = f"  {'Key':<{hdr_key_w}} {'Current':<14} {'Recommended':<12} {'Group'}"
            self.put(pane_y + 1, 1, hdr[:w_left - 2], curses.A_BOLD | curses.color_pair(PAIR_CYAN))
            draw_divider_h(self.scr, pane_y + 2, 0, w_left, color=curses.color_pair(PAIR_BLUE))

            table_rows_avail = pane_h - 4
            view_start = max(0, min(cur_idx - table_rows_avail // 2, len(rows) - table_rows_avail))

            for row_offset, idx in enumerate(range(view_start, min(len(rows), view_start + table_rows_avail))):
                item_y = pane_y + 3 + row_offset
                key = rows[idx]
                opt = next((o for o in ALL_OPTIONS if o[0] == key), None)
                group = opt[1] if opt else ""
                val = self.s.option_value(key)
                rec = RECOMMENDED.get(key, opt[3] if opt else "")
                val_disp = "(unset)" if val is None else str(val)

                if val is None:
                    icon = "○"
                elif key == "gpgcheck" and str(val).lower() in ("false", "0"):
                    icon = "⚠"
                elif str(val) != str(rec):
                    icon = "●"
                else:
                    icon = "✓"

                line_str = f" {icon} {key:<{hdr_key_w - 2}} {val_disp:<14} {str(rec):<12} {group}"
                attr = self.value_attr(key, val)
                if idx == cur_idx:
                    attr = curses.A_REVERSE | attr | curses.A_BOLD

                self.put(item_y, 1, line_str[:w_left - 2], attr)
                self.visible_rows[0].append((item_y, idx))

            # Right Pane: Setting Details Inspector
            draw_box(self.scr, pane_y, w_left, pane_h, w_right,
                     title=f"Inspector: [{cur_key}]",
                     color=curses.color_pair(PAIR_CYAN),
                     subtitle="[J/K Scroll]")

            detail_lines = self.detail(0, cur_key)
            wrapped = []
            for dl in detail_lines:
                if not dl:
                    wrapped.append("")
                else:
                    wrapped.extend(textwrap.wrap(dl, max(20, w_right - 6)) or [""])

            card_avail = pane_h - 3
            self.detail_offset[0] = max(0, min(self.detail_offset[0], max(0, len(wrapped) - card_avail)))
            d_start = self.detail_offset[0]

            for offset_y, d_line in enumerate(wrapped[d_start:d_start + card_avail]):
                put_y = pane_y + 2 + offset_y
                line_attr = 0
                if d_line.startswith("Option:"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_CYAN)
                elif d_line.startswith("CRITICAL:"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_ALERT)
                elif d_line.startswith("Notice:"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_YELLOW)
                self.put(put_y, w_left + 3, d_line[:w_right - 6], line_attr)

        else:
            # Top / Bottom split for narrower displays
            top_h = max(7, (pane_h * 5) // 9)
            bot_h = pane_h - top_h
            bot_y = pane_y + top_h

            draw_box(self.scr, pane_y, 0, top_h, w - 1,
                     title="dnf.conf Settings",
                     color=curses.color_pair(PAIR_BLUE),
                     subtitle=f"{len(rows)} options")

            hdr = f"  {'Key':<28} {'Current':<14} {'Recommended':<12} {'Group'}"
            self.put(pane_y + 1, 1, hdr[:w - 3], curses.A_BOLD | curses.color_pair(PAIR_CYAN))
            draw_divider_h(self.scr, pane_y + 2, 0, w - 1, color=curses.color_pair(PAIR_BLUE))

            table_rows_avail = top_h - 4
            view_start = max(0, min(cur_idx - table_rows_avail // 2, len(rows) - table_rows_avail))

            for row_offset, idx in enumerate(range(view_start, min(len(rows), view_start + table_rows_avail))):
                item_y = pane_y + 3 + row_offset
                key = rows[idx]
                opt = next((o for o in ALL_OPTIONS if o[0] == key), None)
                group = opt[1] if opt else ""
                val = self.s.option_value(key)
                rec = RECOMMENDED.get(key, opt[3] if opt else "")
                val_disp = "(unset)" if val is None else str(val)

                icon = "●" if (val is not None and str(val) != str(rec)) else ("✓" if val is not None else "○")
                line_str = f" {icon} {key:<26} {val_disp:<14} {str(rec):<12} {group}"
                attr = self.value_attr(key, val)
                if idx == cur_idx:
                    attr = curses.A_REVERSE | attr | curses.A_BOLD

                self.put(item_y, 1, line_str[:w - 3], attr)
                self.visible_rows[0].append((item_y, idx))

            draw_box(self.scr, bot_y, 0, bot_h, w - 1,
                     title=f"Inspector: [{cur_key}]",
                     color=curses.color_pair(PAIR_CYAN),
                     subtitle="[J/K Scroll]")

            detail_lines = self.detail(0, cur_key)
            wrapped = []
            for dl in detail_lines:
                wrapped.extend(textwrap.wrap(dl, max(20, w - 6)) or [""])

            card_avail = bot_h - 3
            self.detail_offset[0] = max(0, min(self.detail_offset[0], max(0, len(wrapped) - card_avail)))
            d_start = self.detail_offset[0]

            for offset_y, d_line in enumerate(wrapped[d_start:d_start + card_avail]):
                put_y = bot_y + 1 + offset_y
                line_attr = curses.A_BOLD if d_line.startswith("Option:") else 0
                self.put(put_y, 3, d_line[:w - 6], line_attr)

    def draw_repos_tab(self, h, w):
        pane_y = 3
        pane_h = h - 5
        rows = self.rows(1)
        self.visible_rows[1] = []

        if not rows:
            draw_box(self.scr, pane_y, 0, pane_h, w - 1, title="Repository Catalog", color=curses.color_pair(PAIR_BLUE))
            self.put(pane_y + 3, 4, "No repositories match filter. Press Esc or '/' to clear search.", curses.color_pair(PAIR_YELLOW))
            return

        self.cursor[1] = max(0, min(self.cursor[1], len(rows) - 1))
        cur_idx = self.cursor[1]
        cur_name = rows[cur_idx][0]

        is_split = (w >= 105)
        if is_split:
            w_left = int(w * 0.52)
            w_right = w - w_left - 1

            # Left Pane: Repos Table
            draw_box(self.scr, pane_y, 0, pane_h, w_left,
                     title="Repository Catalog",
                     color=curses.color_pair(PAIR_BLUE),
                     subtitle=f"{len(rows)} repos")

            hdr_name_w = max(16, w_left - 36)
            hdr = f"  {'Status':<10} {'Repository Name':<{hdr_name_w}} {'Category'}"
            self.put(pane_y + 1, 1, hdr[:w_left - 2], curses.A_BOLD | curses.color_pair(PAIR_CYAN))
            draw_divider_h(self.scr, pane_y + 2, 0, w_left, color=curses.color_pair(PAIR_BLUE))

            table_rows_avail = pane_h - 4
            view_start = max(0, min(cur_idx - table_rows_avail // 2, len(rows) - table_rows_avail))

            for row_offset, idx in enumerate(range(view_start, min(len(rows), view_start + table_rows_avail))):
                item_y = pane_y + 3 + row_offset
                name = rows[idx][0]
                ent = self.s.catalog.get(name)
                is_on = self.s.is_on(name)
                status = ent.display_status(is_on) if ent else ("ON" if self.s.repos[name]["enabled"] else "OFF")
                cname = ent.cat if ent else "Installed / official"

                badge = f"[{status}]"
                line_str = f"  {badge:<10} {name:<{hdr_name_w}} {cname}"
                attr = self.attr_for_status(status)
                if idx == cur_idx:
                    attr = curses.A_REVERSE | attr | curses.A_BOLD

                self.put(item_y, 1, line_str[:w_left - 2], attr)
                self.visible_rows[1].append((item_y, idx))

            # Right Pane: Repo Details Inspector
            draw_box(self.scr, pane_y, w_left, pane_h, w_right,
                     title=f"Repo Inspector: [{cur_name}]",
                     color=curses.color_pair(PAIR_CYAN),
                     subtitle="[L Live Probe]")

            detail_lines = self.detail(1, cur_name)
            wrapped = []
            for dl in detail_lines:
                if not dl:
                    wrapped.append("")
                else:
                    wrapped.extend(textwrap.wrap(dl, max(20, w_right - 6)) or [""])

            card_avail = pane_h - 3
            self.detail_offset[1] = max(0, min(self.detail_offset[1], max(0, len(wrapped) - card_avail)))
            d_start = self.detail_offset[1]

            for offset_y, d_line in enumerate(wrapped[d_start:d_start + card_avail]):
                put_y = pane_y + 2 + offset_y
                line_attr = 0
                if d_line.startswith("APPLE SILICON HARDWARE") or d_line.startswith("REFUSED:"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_ALERT)
                elif d_line.startswith("MANDATORY SYSTEM") or d_line.startswith("TESTING REPOSITORY"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_YELLOW)
                elif d_line.startswith("Repository:"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_CYAN)
                elif d_line.startswith("Live Build:"):
                    line_attr = curses.A_BOLD | curses.color_pair(PAIR_GREEN if "OK" in d_line else PAIR_YELLOW)
                self.put(put_y, w_left + 3, d_line[:w_right - 6], line_attr)

        else:
            top_h = max(7, (pane_h * 5) // 9)
            bot_h = pane_h - top_h
            bot_y = pane_y + top_h

            draw_box(self.scr, pane_y, 0, top_h, w - 1,
                     title="Repository Catalog",
                     color=curses.color_pair(PAIR_BLUE),
                     subtitle=f"{len(rows)} repos")

            hdr = f"  {'Status':<10} {'Repository Name':<28} {'Category'}"
            self.put(pane_y + 1, 1, hdr[:w - 3], curses.A_BOLD | curses.color_pair(PAIR_CYAN))
            draw_divider_h(self.scr, pane_y + 2, 0, w - 1, color=curses.color_pair(PAIR_BLUE))

            table_rows_avail = top_h - 4
            view_start = max(0, min(cur_idx - table_rows_avail // 2, len(rows) - table_rows_avail))

            for row_offset, idx in enumerate(range(view_start, min(len(rows), view_start + table_rows_avail))):
                item_y = pane_y + 3 + row_offset
                name = rows[idx][0]
                ent = self.s.catalog.get(name)
                is_on = self.s.is_on(name)
                status = ent.display_status(is_on) if ent else ("ON" if self.s.repos[name]["enabled"] else "OFF")
                cname = ent.cat if ent else "Installed / official"

                badge = f"[{status}]"
                line_str = f"  {badge:<10} {name:<28} {cname}"
                attr = self.attr_for_status(status)
                if idx == cur_idx:
                    attr = curses.A_REVERSE | attr | curses.A_BOLD

                self.put(item_y, 1, line_str[:w - 3], attr)
                self.visible_rows[1].append((item_y, idx))

            draw_box(self.scr, bot_y, 0, bot_h, w - 1,
                     title=f"Repo Inspector: [{cur_name}]",
                     color=curses.color_pair(PAIR_CYAN),
                     subtitle="[L Live Probe]")

            detail_lines = self.detail(1, cur_name)
            wrapped = []
            for dl in detail_lines:
                wrapped.extend(textwrap.wrap(dl, max(20, w - 6)) or [""])

            card_avail = bot_h - 3
            self.detail_offset[1] = max(0, min(self.detail_offset[1], max(0, len(wrapped) - card_avail)))
            d_start = self.detail_offset[1]

            for offset_y, d_line in enumerate(wrapped[d_start:d_start + card_avail]):
                put_y = bot_y + 1 + offset_y
                line_attr = curses.A_BOLD if d_line.startswith("Repository:") else 0
                self.put(put_y, 3, d_line[:w - 6], line_attr)

    def draw_review_tab(self, h, w):
        pane_y = 3
        pane_h = h - 5
        lines = [part for line in self.review_lines()
                 for part in (textwrap.wrap(line, max(10, w - 6), replace_whitespace=False, drop_whitespace=False) or [""])]

        view_avail = pane_h - 6
        max_scroll = max(0, len(lines) - view_avail)
        self.offset[2] = max(0, min(self.offset[2], max_scroll))

        p_str = make_progress_bar(self.offset[2], max_scroll, width=10)
        draw_box(self.scr, pane_y, 0, pane_h, w - 1,
                 title="Configuration Diff & Dry-Run Gate",
                 color=curses.color_pair(PAIR_CYAN),
                 subtitle=p_str)

        # Draw diff lines with high-contrast syntax highlighting
        for y_offset, line in enumerate(lines[self.offset[2]:self.offset[2] + view_avail]):
            cur_y = pane_y + 1 + y_offset
            attr = 0
            if line.startswith("+") and not line.startswith("+++"):
                attr = curses.color_pair(PAIR_GREEN) | curses.A_BOLD
            elif line.startswith("-") and not line.startswith("---"):
                attr = curses.color_pair(PAIR_RED) | curses.A_BOLD
            elif line.startswith("@@"):
                attr = curses.color_pair(PAIR_CYAN) | curses.A_BOLD
            elif line.startswith("--- ") or line.startswith("+++ "):
                attr = curses.color_pair(PAIR_MAGENTA) | curses.A_BOLD
            elif line.startswith("BLOCKED:"):
                attr = curses.color_pair(PAIR_ALERT) | curses.A_BOLD
            elif line.startswith("WARNING:"):
                attr = curses.color_pair(PAIR_YELLOW) | curses.A_BOLD
            elif line.startswith("Prerequisites:"):
                attr = curses.color_pair(PAIR_CYAN) | curses.A_BOLD
            elif "ENABLE  [" in line:
                attr = curses.color_pair(PAIR_GREEN) | curses.A_BOLD
            elif "DISABLE [" in line:
                attr = curses.color_pair(PAIR_YELLOW) | curses.A_BOLD
            elif line.startswith("--- ") and line.endswith(" ---"):
                attr = curses.A_BOLD | curses.color_pair(PAIR_CYAN)

            self.put(cur_y, 3, line[:w - 6], attr)

        # Gate verification check
        if self.offset[2] >= max_scroll:
            self.s.reviewed_hash = self.s.fingerprint()

        is_verified = (self.s.reviewed_hash == self.s.fingerprint())
        banner_y = pane_y + pane_h - 4
        draw_divider_h(self.scr, banner_y, 0, w - 1, color=curses.color_pair(PAIR_BLUE))

        if is_verified:
            banner_text = " ✓ REVIEW VERIFIED — DRY-RUN GATE UNLOCKED — PRESS [A] TO APPLY "
            self.put(banner_y + 1, max(2, (w - len(banner_text)) // 2),
                     banner_text, curses.color_pair(PAIR_VERIFIED) | curses.A_BOLD)
        else:
            pct_scrolled = int((self.offset[2] / max(1, max_scroll)) * 100)
            banner_text = f" ⚠ SCROLL TO BOTTOM [PgDn/End] TO UNLOCK APPLY GATE ({pct_scrolled}%) "
            self.put(banner_y + 1, max(2, (w - len(banner_text)) // 2),
                     banner_text, curses.color_pair(PAIR_YELLOW) | curses.A_BOLD)

    def draw(self):
        if self.show_help:
            self.draw_help()
            return

        self.scr.erase()
        self.hits = []
        h, w = self.scr.getmaxyx()

        if h < 20 or w < 70:
            self.put(0, 0, "Expand terminal window to at least 70 cols x 20 rows. Q quits.")
            self.scr.refresh()
            return

        if self.mode == "choose":
            self.draw_startup_screen()
            return

        self.draw_header_and_tabs(h, w)

        if self.tab == 0:
            self.draw_options_tab(h, w)
        elif self.tab == 1:
            self.draw_repos_tab(h, w)
        elif self.tab == 2:
            self.draw_review_tab(h, w)

        # Toast / Message Line at h - 2
        msg_text = self.msg
        icon = "ℹ "
        msg_attr = curses.color_pair(PAIR_CYAN)
        if self.msg_type == "success" or "Applied" in msg_text or "✓" in msg_text:
            icon = "✓ "
            msg_attr = curses.color_pair(PAIR_GREEN) | curses.A_BOLD
        elif self.msg_type == "error" or "Error" in msg_text or "rejected" in msg_text or "failed" in msg_text:
            icon = "✕ "
            msg_attr = curses.color_pair(PAIR_RED) | curses.A_BOLD
        elif self.msg_type == "warn" or "refused" in msg_text.lower() or "required" in msg_text.lower():
            icon = "▲ "
            msg_attr = curses.color_pair(PAIR_YELLOW) | curses.A_BOLD

        self.put(h - 2, 1, icon + msg_text, msg_attr)

        # Unified Keyboard Legend at h - 1
        legend = "[Tab] Tabs  │  [↑/↓] Move  │  [Enter] Edit/Toggle  │  [U] Unset  │  [/] Search  │  [D] Review  │  [A] Apply  │  [?] Help  │  [Q] Quit"
        self.put(h - 1, 1, legend, curses.color_pair(PAIR_DIM))
        self.scr.refresh()

    def check_live_selected(self):
        rows = self.rows(self.tab)
        if not rows or self.tab != 1:
            return
        name = rows[self.cursor[self.tab]][0]
        self.toast(f"Probing aarch64 build for [{name}]...", msg_type="info")
        self.scr.refresh()
        status = self.check_live(name)
        self.toast(f"[{name}] {status}", msg_type="info")

    def choose(self, mode):
        self.mode = mode

    def move(self, delta):
        self.detail_offset[self.tab] = 0
        if self.tab == 2:
            self.offset[2] += delta
            return
        rows = self.rows(self.tab)
        if self.tab == 0 and self.mode == "single" and self.cursor[0] + delta >= len(rows):
            self.switch(1)
            return
        self.cursor[self.tab] = max(0, min(max(0, len(rows) - 1), self.cursor[self.tab] + delta))

    def activate(self):
        rows = self.rows(self.tab)
        if self.tab == 2 or not rows:
            return
        try:
            if self.tab == 1:
                name = rows[self.cursor[self.tab]][0]
                msg = self.s.toggle(name)
                if msg:
                    self.toast(msg, msg_type="warn" if "refused" in msg.lower() or "required" in msg.lower() else "info")
                else:
                    state_txt = "enabled" if self.s.is_on(name) else "disabled"
                    self.toast(f"[{name}] {state_txt}. Review diff before applying.", msg_type="success")
            else:
                name = rows[self.cursor[self.tab]]
                opt = next((o for o in ALL_OPTIONS if o[0] == name), None)
                allowed = opt[2] if opt else ""
                choices = opt[5] if opt else ""
                old = self.s.option_value(name)
                if name in FLAGS:
                    # Toggle flag: True -> False -> None -> True
                    if old is True or str(old).lower() == "true":
                        value = False
                    elif old is False or str(old).lower() == "false":
                        value = None
                    else:
                        value = True
                else:
                    value = self.prompt(name, initial=str(old) if old is not None else "", allowed=allowed, choices=choices)
                if value is None and name not in FLAGS:
                    return
                self.s.set_option(name, value)
                val_disp = "(unset)" if value is None else str(value)
                self.toast(f"{name} set to {val_disp}. Review diff before applying.", msg_type="success")
        except ValueError as e:
            self.toast(str(e), msg_type="error")
        except (curses.error, OSError) as e:
            self.toast(f"Input error: {e}", msg_type="error")
        except Exception as e:
            self.toast(f"Error: {e}", msg_type="error")

    def unset(self):
        rows = self.rows(self.tab)
        if self.tab == 0 and rows:
            name = rows[self.cursor[0]]
            try:
                self.s.unset_option(name)
                self.toast(f"{name} unset (uses built-in default).", msg_type="success")
            except ValueError as e:
                self.toast(str(e), msg_type="error")

    def do_apply(self):
        if not self.s.changed():
            self.toast("No pending changes to apply.", msg_type="info")
            return
        if self.s.reviewed_hash != self.s.fingerprint():
            self.switch(2)
            self.toast("Review diff to the bottom before applying.", msg_type="warn")
            return
        curses.endwin()
        try:
            print("\n" + "=" * 74)
            print("  Asahi Control Deck — Executing Staged Configuration Apply")
            print("=" * 74 + "\n")
            ok = apply_changes(self.s, print)
            print("\n" + "-" * 74)
            try:
                input("Press Enter to return to Asahi Control Deck...")
            except (EOFError, KeyboardInterrupt):
                pass
            if ok:
                self.s = State(self.s.conf_path, self.s.repo_dir, CATALOG_PATH, self.s.live)
                self.toast("Configuration successfully applied!", msg_type="success")
            else:
                self.toast("Apply aborted or failed. Check console output.", msg_type="error")
        except (OSError, ValueError) as e:
            self.toast(f"Apply error: {e}", msg_type="error")
        finally:
            self.scr.refresh()

    def key(self, k):
        if self.show_help:
            if k in (27, getattr(curses, 'KEY_F1', 265), 265, ord('?'), ord('q'), ord('Q')):
                self.show_help = False
            else:
                self.show_help = False
            return True

        if k in (ord('q'), ord('Q'), 3):  # 3 is ASCII ETX (Ctrl+C)
            if self.confirm_quit():
                return False
            return True

        if k in (getattr(curses, 'KEY_F1', 265), 265, ord('?')):
            self.show_help = True
            return True

        if k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, buttons = curses.getmouse()
            except curses.error:
                return True
            if buttons & getattr(curses, 'BUTTON4_PRESSED', 0):
                self.move(-3)
            elif buttons & getattr(curses, 'BUTTON5_PRESSED', 0):
                self.move(3)
            elif buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED |
                            curses.BUTTON1_DOUBLE_CLICKED | getattr(curses, 'BUTTON1_RELEASED', 0)):
                for by, left, right, action in self.hits:
                    if my == by and left <= mx < right:
                        action()
                        return not getattr(self, 'quitting', False)
                for ry, i in self.visible_rows[self.tab]:
                    if my == ry:
                        self.cursor[self.tab] = i
                        if buttons & curses.BUTTON1_DOUBLE_CLICKED:
                            self.activate()
                        break
            return not getattr(self, 'quitting', False)

        if self.mode == "choose":
            if k == ord('1'):
                self.choose("single")
            elif k == ord('2'):
                self.choose("grouped")
            elif k in (curses.KEY_UP, curses.KEY_DOWN, 9):
                self.choose_cursor = 1 - getattr(self, "choose_cursor", 0)
            elif k in (10, 13, ord(' ')):
                self.choose("single" if getattr(self, "choose_cursor", 0) == 0 else "grouped")
            return True

        if k in (ord('j'), ord('J')):
            self.detail_offset[self.tab] += 1
        elif k in (ord('k'), ord('K')):
            self.detail_offset[self.tab] = max(0, self.detail_offset[self.tab] - 1)
        elif k == 9:  # Tab
            self.switch((self.tab + 1) % 3)
        elif k == ord('1'):
            self.switch(0)
        elif k == ord('2'):
            self.switch(1)
        elif k == ord('3'):
            self.switch(2)
        elif k in (ord('d'), ord('D')):
            self.switch(2)
        elif k in (ord('a'), ord('A')):
            self.do_apply()
        elif k in (ord('l'), ord('L')):
            self.check_live_selected()
        elif k == curses.KEY_UP:
            self.move(-1)
        elif k == curses.KEY_DOWN:
            self.move(1)
        elif k == curses.KEY_NPAGE:
            self.move(8)
        elif k == curses.KEY_PPAGE:
            self.move(-8)
        elif k == curses.KEY_END:
            if self.tab == 2:
                self.offset[2] = 10 ** 9
            else:
                self.cursor[self.tab] = max(0, len(self.rows(self.tab)) - 1)
        elif k == curses.KEY_HOME:
            if self.tab == 2:
                self.offset[2] = 0
            else:
                self.cursor[self.tab] = 0
        elif k in (10, 13, ord(' ')):
            self.activate()
        elif k in (ord('u'), ord('U')):
            self.unset()
        elif k == ord('/') and self.tab != 2:
            value = self.prompt("Search: ", self.search[self.tab])
            if value is not None:
                self.search[self.tab] = value
                self.cursor[self.tab] = 0
        elif k == 27 and self.search[self.tab]:  # Escape clears active search
            self.search[self.tab] = ""
            self.cursor[self.tab] = 0
            self.toast("Search filter cleared.", msg_type="info")
        elif k in (curses.KEY_LEFT, curses.KEY_RIGHT) and self.tab != 2:
            if self.tab == 0:
                groups = ["All"] + list(dict.fromkeys(g for _, g, _, _, _, _, _ in ALL_OPTIONS))
            else:
                groups = ["All"] + sorted({e.cat for e in self.s.catalog.values()})
            self.category[self.tab] = groups[(groups.index(self.category[self.tab]) +
                                               (1 if k == curses.KEY_RIGHT else -1)) % len(groups)]
            self.cursor[self.tab] = 0
        return not getattr(self, 'quitting', False)

    def run(self):
        while True:
            try:
                self.draw()
            except (curses.error, OSError):
                pass
            try:
                k = self.scr.getch()
            except KeyboardInterrupt:
                if self.confirm_quit():
                    return
                continue
            except (curses.error, OSError):
                continue
            try:
                if not self.key(k):
                    return
            except (curses.error, OSError):
                pass
            except Exception as e:
                self.toast(f"Unexpected error: {e}", msg_type="error")


# ---------------------------------------------------------------- CLI ---
class CLI:
    """Robust, pure-terminal command-line interface with box borders and clean ANSI tables."""
    def __init__(self, state, mode="choose", yes=False):
        self.s = state
        self.mode = mode
        self.yes = yes
        self.hw_badge = get_hardware_badge()
        self.hostname = get_hostname()
        self.use_color = (
            sys.stdout.isatty() and
            os.environ.get("NO_COLOR", "") == "" and
            os.environ.get("TERM", "") != "dumb"
        )

    def color(self, code, text):
        if not self.use_color:
            return str(text)
        return f"\033[{code}m{text}\033[0m"

    def c_bold(self, t): return self.color("1", t)
    def c_dim(self, t): return self.color("2", t)
    def c_green(self, t): return self.color("32", t)
    def c_red(self, t): return self.color("31", t)
    def c_yellow(self, t): return self.color("33", t)
    def c_blue(self, t): return self.color("34", t)
    def c_magenta(self, t): return self.color("35", t)
    def c_cyan(self, t): return self.color("36", t)

    def status_badge(self, name):
        ent = self.s.catalog.get(name)
        if ent and ent.is_refused():
            return self.c_red("[REFUSED]")
        if ent and ent.is_required():
            return self.c_yellow("[REQUIRED]")
        if ent and getattr(ent, "testing", False):
            return self.c_yellow("[TESTING]" if self.s.is_on(name) else "[OFF/TST]")
        if self.s.is_on(name):
            return self.c_green("[ON]     ")
        return self.c_dim("[OFF]    ")

    def run(self):
        if self.mode == "single":
            self.walk_options()
            self.main_menu()
        elif self.mode == "grouped":
            self.manage_options_grouped()
            self.main_menu()
        else:
            self.main_menu()

    def main_menu(self):
        while True:
            changes = self.s.changes_count()
            change_str = self.c_yellow(f"{changes} pending") if changes else self.c_dim("none")
            w = 78
            print()
            print(self.c_cyan("╭─") + self.c_bold("  ASAHI CONTROL DECK (CLI) ") + self.c_cyan(f"─ [{self.hw_badge}] ─ [Host: {self.hostname}] ─╮"))
            print(self.c_cyan("│ ") + pad_ansi(f"Target Config: {self.s.conf_path}", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("│ ") + pad_ansi(f"Staged Changes: {change_str}  │  Live Checks: {'on' if self.s.live else 'off'}", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("├" + ("─" * (w - 2)) + "┤"))
            print(self.c_cyan("│ ") + pad_ansi("  1) Single Option Walk   — Sequential dnf.conf options walkthrough", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("│ ") + pad_ansi("  2) Grouped Settings     — View & modify dnf.conf options by category", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("│ ") + pad_ansi("  3) Repository Catalog   — Browse, filter, toggle & live test repos", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("│ ") + pad_ansi("  4) Review Plan & Diff   — Verify changes & safety guardrails", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("│ ") + pad_ansi("  5) Apply Changes        — Validate & write (dry-run gated)", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("│ ") + pad_ansi("  q) Quit", w - 4) + self.c_cyan(" │"))
            print(self.c_cyan("╰" + ("─" * (w - 2)) + "╯"))

            try:
                choice = input(self.c_bold("Select an option [1-5, q]: ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if choice == "1":
                self.walk_options()
            elif choice == "2":
                self.manage_options_grouped()
            elif choice == "3":
                self.manage_repos()
            elif choice == "4":
                self.review_diff()
            elif choice == "5":
                self.apply_plan()
            elif choice in ("q", "quit", "exit"):
                if self.s.changed():
                    try:
                        c = input("You have unstaged changes. Discard and quit? [y/N]: ").strip().lower()
                        if c == "y":
                            break
                    except (EOFError, KeyboardInterrupt):
                        print()
                        break
                else:
                    break

    def walk_options(self):
        print()
        print(self.c_cyan("╭─") + self.c_bold(" dnf.conf Options Walk (Single Mode) ") + self.c_cyan("─" * 38 + "╮"))
        print(self.c_dim("Enter = keep current │ r = recommended │ - = unset │ s = skip │ q = back"))
        print()
        for idx, (key, group, typ, default, expl, choices, _) in enumerate(ALL_OPTIONS, 1):
            cur = self.s.option_value(key)
            rec = RECOMMENDED.get(key, default)
            cur_disp = "(unset)" if cur is None else str(cur)
            print(self.c_bold(f"[{idx}/{len(ALL_OPTIONS)}] {key}") + f"  ({group})")
            print(f"  {expl}")
            print(f"  Current: {self.c_cyan(cur_disp)} │ Recommended: {self.c_green(str(rec))} │ Default: {default} │ Choices: {choices}")
            while True:
                try:
                    val = input(f"  Set {key} [{cur_disp}]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if not val:
                    break
                if val == "q":
                    return
                if val == "s":
                    print("Skipping remaining options.")
                    return
                if val == "r":
                    try:
                        self.s.set_option(key, rec)
                        print(self.c_green(f"  ✓ Set {key} = {rec}"))
                        break
                    except ValueError as e:
                        print(self.c_red(f"  !! {e}"))
                elif val == "-":
                    self.s.unset_option(key)
                    print(self.c_yellow(f"  ✓ Unset {key}"))
                    break
                else:
                    try:
                        self.s.set_option(key, val)
                        print(self.c_green(f"  ✓ Set {key} = {val}"))
                        break
                    except ValueError as e:
                        print(self.c_red(f"  !! {e}"))

    def manage_options_grouped(self):
        groups = list(dict.fromkeys(g for _, g, _, _, _, _, _ in ALL_OPTIONS))
        while True:
            print()
            print(self.c_cyan("╭─") + self.c_bold(" dnf.conf Grouped Settings ") + self.c_cyan("─" * 46 + "╮"))
            for i, g in enumerate(groups, 1):
                count = sum(1 for _, grp, _, _, _, _, _ in ALL_OPTIONS if grp == g)
                print(f"  {i}) {g:<14} ({count} settings)")
            print("  a) All settings")
            print("  b) Back")
            try:
                ans = input(self.c_bold("Select group [1-3, a, b]: ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if ans == "b":
                return
            if ans == "a":
                selected_opts = ALL_OPTIONS
                title = "All Settings"
            elif ans.isdigit() and 1 <= int(ans) <= len(groups):
                title = groups[int(ans) - 1]
                selected_opts = [o for o in ALL_OPTIONS if o[1] == title]
            else:
                continue

            self._edit_options_list(selected_opts, title)

    def _edit_options_list(self, opts, title):
        while True:
            w = 88
            print()
            print(self.c_cyan("╭─") + self.c_bold(f" {title} ") + self.c_cyan("─" * max(4, w - len(title) - 6) + "╮"))
            hdr = f"  {'#':<4} {pad_ansi('Option Key', 30)} {pad_ansi('Current Value', 16)} {pad_ansi('Recommended', 14)} {'Default'}"
            print(self.c_bold(hdr))
            print(self.c_cyan("├" + ("─" * (w - 2)) + "┤"))
            for i, (key, grp, _, default, _, _, _) in enumerate(opts, 1):
                cur = self.s.option_value(key)
                rec = RECOMMENDED.get(key, default)
                cur_disp = "(unset)" if cur is None else str(cur)

                if cur is None:
                    c_val = self.c_dim(cur_disp)
                elif key == "gpgcheck" and str(cur).lower() in ("false", "0"):
                    c_val = self.c_red("⚠ " + cur_disp)
                elif str(cur) != str(rec):
                    c_val = self.c_yellow(cur_disp)
                else:
                    c_val = self.c_green(cur_disp)

                row = f"  {i:<4} {pad_ansi(key, 30)} {pad_ansi(c_val, 16)} {pad_ansi(self.c_green(str(rec)), 14)} {default}"
                print(row)
            print(self.c_cyan("╰" + ("─" * (w - 2)) + "╯"))

            try:
                ans = input("Enter option number to edit, or 'b' to go back: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if ans == "b":
                return
            if ans.isdigit() and 1 <= int(ans) <= len(opts):
                key, grp, typ, default, expl, choices, _ = opts[int(ans) - 1]
                cur = self.s.option_value(key)
                rec = RECOMMENDED.get(key, default)
                cur_disp = "(unset)" if cur is None else str(cur)
                print()
                print(self.c_bold(f"Option: {key} ({grp})"))
                print(f"Explanation: {expl}")
                print(f"Current: {cur_disp} │ Recommended: {rec} │ Allowed Choices: {choices}")
                try:
                    val = input(f"New value [Enter=keep, r={rec}, -=unset]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
                if not val:
                    continue
                if val == "r":
                    try:
                        self.s.set_option(key, rec)
                        print(self.c_green(f"✓ Set {key} = {rec}"))
                    except ValueError as e:
                        print(self.c_red(f"!! {e}"))
                elif val == "-":
                    self.s.unset_option(key)
                    print(self.c_yellow(f"✓ Unset {key}"))
                else:
                    try:
                        self.s.set_option(key, val)
                        print(self.c_green(f"✓ Set {key} = {val}"))
                    except ValueError as e:
                        print(self.c_red(f"!! {e}"))

    def manage_repos(self):
        cats = ["All"] + sorted({e.cat for e in self.s.catalog.values()})
        current_cat = "All"
        search_filter = ""
        while True:
            rows = []
            for n, src in self.s.all_rows():
                ent = self.s.catalog.get(n)
                cname = ent.cat if ent else "Installed / official"
                info = ent.info if ent else "Repository in the opened configuration."
                if current_cat != "All" and cname != current_cat:
                    continue
                if search_filter and search_filter.lower() not in (n + " " + cname + " " + info).lower():
                    continue
                rows.append((n, cname, info))

            w = 84
            print()
            print(self.c_cyan("╭─") + self.c_bold(f" Repository Catalog │ Category: {current_cat} │ Found: {len(rows)} ") + self.c_cyan("─" * 12 + "╮"))
            if search_filter:
                print(self.c_cyan("│ ") + f"Active Search Filter: '{search_filter}'" + self.c_cyan(" │"))
            hdr = f"  {pad_ansi('Status', 12)} {pad_ansi('Repository Name', 28)} {pad_ansi('Category', 32)}"
            print(self.c_cyan("├" + ("─" * (w - 2)) + "┤"))
            print(self.c_bold(hdr))
            print(self.c_cyan("├" + ("─" * (w - 2)) + "┤"))

            for n, cname, info in rows[:25]:
                badge = self.status_badge(n)
                row = f"  {pad_ansi(badge, 12)} {pad_ansi(n, 28)} {pad_ansi(self.c_dim(cname[:32]), 32)}"
                print(row)
            if len(rows) > 25:
                print(self.c_dim(f"  ... and {len(rows) - 25} more repos (use category or search filter)"))
            print(self.c_cyan("├" + ("─" * (w - 2)) + "┤"))
            print("  Commands: e <name>   enable repo        │ d <name>   disable repo")
            print("            t <name>   toggle repo        │ l <name>   live build check")
            print("            c          filter category    │ / <query>  search repos")
            print("            i <name>   inspect details    │ b          back to main menu")
            print(self.c_cyan("╰" + ("─" * (w - 2)) + "╯"))

            try:
                cmd = input(self.c_bold("Repo command: ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not cmd or cmd == "b":
                return
            parts = cmd.split(maxsplit=1)
            action = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if action == "c":
                print("\nCategories:")
                for i, c in enumerate(cats, 1):
                    print(f"  {i}) {c}")
                try:
                    c_sel = input("Select category number: ").strip()
                    if c_sel.isdigit() and 1 <= int(c_sel) <= len(cats):
                        current_cat = cats[int(c_sel) - 1]
                        search_filter = ""
                except (EOFError, KeyboardInterrupt):
                    pass
            elif action == "/":
                search_filter = arg
            elif action in ("e", "enable"):
                if not arg:
                    print(self.c_red("Specify repository name."))
                    continue
                if not self.s.is_on(arg):
                    msg = self.s.toggle(arg)
                    if msg:
                        print(self.c_yellow(f"  {msg}"))
                    else:
                        print(self.c_green(f"  ✓ Enabled [{arg}]"))
                else:
                    print(f"  [{arg}] is already enabled.")
            elif action in ("d", "disable"):
                if not arg:
                    print(self.c_red("Specify repository name."))
                    continue
                if self.s.is_on(arg):
                    msg = self.s.toggle(arg)
                    if msg:
                        print(self.c_yellow(f"  {msg}"))
                    else:
                        print(self.c_yellow(f"  ✓ Disabled [{arg}]"))
                else:
                    print(f"  [{arg}] is already disabled.")
            elif action in ("t", "toggle"):
                if not arg:
                    print(self.c_red("Specify repository name."))
                    continue
                msg = self.s.toggle(arg)
                if msg:
                    print(self.c_yellow(f"  {msg}"))
                else:
                    st = "ON" if self.s.is_on(arg) else "OFF"
                    print(self.c_green(f"  ✓ Toggled [{arg}] -> {st}"))
            elif action in ("l", "live"):
                target = arg or (rows[0][0] if rows else "")
                if target:
                    print(f"Probing live build for [{target}]...")
                    status = self.s.check_live(target, force=True)
                    print(self.c_cyan(f"  [{target}] {status}"))
                else:
                    print(self.c_red("No repository specified."))
            elif action in ("i", "info", "inspect"):
                if not arg:
                    print(self.c_red("Specify repository name."))
                    continue
                ent = self.s.catalog.get(arg)
                print()
                print(self.c_bold(f"Repository: {arg}"))
                if ent:
                    print(f"  Category:     {ent.cat}")
                    print(f"  Kind:         {ent.kind}")
                    print(f"  Status:       {self.status_badge(arg)}")
                    print(f"  IDs:          {', '.join(ent.id_list)}")
                    print(f"  Top packages: {ent.top or '(none specified)'}")
                    print(f"  Description:  {ent.info}")
                    if ent.warn:
                        print(self.c_yellow(f"  Warning:      {ent.warn}"))
                    if ent.is_refused():
                        reason = REFUSED_REASONS.get(arg, ent.setup or "Incompatible with Apple Silicon.")
                        print(self.c_red(f"  REFUSED:      {reason}"))
                    live_stat = self.s.check_live(arg)
                    print(f"  Live build:   {self.c_cyan(live_stat)}")
                elif arg in self.s.repos:
                    r = self.s.repos[arg]
                    print(f"  File:         {r['file']}")
                    print(f"  Status:       {'ON' if r['enabled'] else 'OFF'}")
                else:
                    print(self.c_red(f"  Repository [{arg}] not found."))
                try:
                    input("\nPress Enter to continue...")
                except (EOFError, KeyboardInterrupt):
                    pass

    def review_diff(self):
        w = 78
        print()
        print(self.c_cyan("╭─") + self.c_bold(" Plan Review & Safety Verification Gate ") + self.c_cyan("─" * (w - 42) + "╮"))

        problems = self.s.problems()
        warnings = self.s.warnings()
        prereqs = self.s.prereqs() if os.path.realpath(self.s.conf_path) == DEFAULT_CONF else []

        if problems:
            print(self.c_red(self.c_bold("BLOCKED ISSUES:")))
            for p in problems:
                print(self.c_red(f"  ✕ {p}"))
            print()
        if warnings:
            print(self.c_yellow(self.c_bold("SAFETY WARNINGS:")))
            for w_msg in warnings:
                print(self.c_yellow(f"  ▲ {w_msg}"))
            print()
        if prereqs:
            print(self.c_cyan(self.c_bold("PREREQUISITES:")))
            for pr in prereqs:
                print(self.c_cyan(f"  $ {pr}"))
            print()

        print(self.c_bold("REPOSITORY MUTATION PLAN:"))
        repo_changes = 0
        for n in self.s._all_repo_names():
            was_on = self.repos_status_get(n)
            now_on = self.s.is_on(n)
            if was_on != now_on:
                repo_changes += 1
                action = self.c_green(f"ENABLE  [{n}]") if now_on else self.c_yellow(f"DISABLE [{n}]")
                print(f"  • {action}")
        if repo_changes == 0:
            print(self.c_dim("  (no repository changes)"))

        print()
        print(self.c_bold("CONFIGURATION DIFF (dnf.conf):"))
        diff_lines = list(difflib.unified_diff(
            self.s.dnf_conf.orig.splitlines(),
            self.s.proposed_conf().splitlines(),
            fromfile=self.s.conf_path,
            tofile=self.s.conf_path + " (proposed)",
            lineterm="", n=2))
        if diff_lines:
            for dl in diff_lines:
                if dl.startswith("+") and not dl.startswith("+++"):
                    print(self.c_green(dl))
                elif dl.startswith("-") and not dl.startswith("---"):
                    print(self.c_red(dl))
                elif dl.startswith("@@"):
                    print(self.c_cyan(dl))
                else:
                    print(dl)
        else:
            print(self.c_dim("  (no dnf.conf changes)"))

        self.s.reviewed_hash = self.s.fingerprint()
        print()
        if not problems:
            print(self.c_green("✓ Plan review verified. Dry-run gate UNLOCKED."))
        else:
            print(self.c_red("✕ Plan BLOCKED. Resolve issues before applying."))

    def repos_status_get(self, n):
        return self.s.repos[n]["enabled"] if n in self.s.repos else False

    def apply_plan(self):
        if not self.s.changed():
            print(self.c_yellow("\nNo changes to apply."))
            return
        if self.s.reviewed_hash != self.s.fingerprint():
            print(self.c_yellow("\nPlan has not been reviewed yet. Opening review..."))
            self.review_diff()
        if self.s.problems():
            print(self.c_red("\nCannot apply: configuration has blocking errors."))
            return
        print()
        confirm_fn = (lambda msg: "y") if self.yes else input
        ok = apply_changes(self.s, print, confirm=confirm_fn)
        if ok:
            print(self.c_green("\n✓ Successfully applied configuration!"))
            self.s = State(self.s.conf_path, self.s.repo_dir, CATALOG_PATH, self.s.live)
        else:
            print(self.c_red("\n✕ Apply aborted or failed."))


# ---------------------------------------------------------------- Non-interactive Batch & Lists ---
def cli_list_repos(state, use_color=True):
    c_green = (lambda t: f"\033[32m{t}\033[0m") if use_color else str
    c_red = (lambda t: f"\033[31m{t}\033[0m") if use_color else str
    c_yellow = (lambda t: f"\033[33m{t}\033[0m") if use_color else str
    c_dim = (lambda t: f"\033[2m{t}\033[0m") if use_color else str
    c_bold = (lambda t: f"\033[1m{t}\033[0m") if use_color else str
    c_cyan = (lambda t: f"\033[36m{t}\033[0m") if use_color else str

    w = 104
    print(c_cyan("╭─") + c_bold(" Fedora Asahi Remix Repository Catalog ") + c_cyan("─" * (w - 42) + "╮"))
    hdr = f"  {pad_ansi('Status', 12)} {pad_ansi('Repository Name', 34)} {pad_ansi('Category', 30)} {pad_ansi('Top Packages', 22)}"
    print(c_bold(hdr))
    print(c_cyan("├" + ("─" * (w - 2)) + "┤"))
    for n, src in state.all_rows():
        ent = state.catalog.get(n)
        cname = ent.cat if ent else "Installed / official"
        top = ent.top if ent else ""
        if ent and ent.is_refused():
            st = c_red("[REFUSED] ")
        elif ent and ent.is_required():
            st = c_yellow("[REQUIRED]")
        elif ent and ent.is_testing():
            st = c_yellow("[TESTING] " if state.is_on(n) else "[OFF/TST] ")
        elif state.is_on(n):
            st = c_green("[ON]      ")
        else:
            st = c_dim("[OFF]     ")
        row = f"  {pad_ansi(st, 12)} {pad_ansi(n[:34], 34)} {pad_ansi(cname[:30], 30)} {pad_ansi(c_dim(top[:22]), 22)}"
        print(row)
    print(c_cyan("╰" + ("─" * (w - 2)) + "╯"))


def cli_list_options(state, use_color=True):
    c_cyan = (lambda t: f"\033[36m{t}\033[0m") if use_color else str
    c_green = (lambda t: f"\033[32m{t}\033[0m") if use_color else str
    c_yellow = (lambda t: f"\033[33m{t}\033[0m") if use_color else str
    c_red = (lambda t: f"\033[31m{t}\033[0m") if use_color else str
    c_dim = (lambda t: f"\033[2m{t}\033[0m") if use_color else str
    c_bold = (lambda t: f"\033[1m{t}\033[0m") if use_color else str

    w = 90
    print(c_cyan("╭─") + c_bold(" dnf.conf Options Catalog ") + c_cyan("─" * (w - 28) + "╮"))
    hdr = f"  {pad_ansi('Option Key', 32)} {pad_ansi('Group', 10)} {pad_ansi('Current', 16)} {pad_ansi('Recommended', 14)} {'Default'}"
    print(c_bold(hdr))
    print(c_cyan("├" + ("─" * (w - 2)) + "┤"))
    for key, group, typ, default, expl, choices, _ in ALL_OPTIONS:
        cur = state.option_value(key)
        rec = RECOMMENDED.get(key, default)
        cur_disp = "(unset)" if cur is None else str(cur)

        if cur is None:
            c_val = c_dim(cur_disp)
        elif key == "gpgcheck" and str(cur).lower() in ("false", "0"):
            c_val = c_red("⚠ " + cur_disp)
        elif str(cur) != str(rec):
            c_val = c_yellow(cur_disp)
        else:
            c_val = c_green(cur_disp)

        row = f"  {pad_ansi(key, 32)} {pad_ansi(group, 10)} {pad_ansi(c_val, 16)} {pad_ansi(c_green(str(rec)), 14)} {default}"
        print(row)
    print(c_cyan("╰" + ("─" * (w - 2)) + "╯"))


def cli_run_batch(state, args):
    """Execute direct non-interactive CLI commands."""
    changed = False
    if args.set:
        for item in args.set:
            if "=" in item:
                k, v = item.split("=", 1)
            else:
                sys.exit(f"Invalid format for --set '{item}'. Use KEY=VALUE.")
            try:
                state.set_option(k.strip(), v.strip())
                print(f"Set {k.strip()} = {v.strip()}")
                changed = True
            except ValueError as e:
                sys.exit(f"Error setting {k}: {e}")

    if args.unset:
        for k in args.unset:
            state.unset_option(k.strip())
            print(f"Unset {k.strip()}")
            changed = True

    if args.enable:
        for name in args.enable:
            if not state.is_on(name):
                msg = state.toggle(name)
                if msg:
                    print(f"Notice: {msg}")
                if state.is_on(name):
                    print(f"Enabled [{name}]")
                    changed = True
            else:
                print(f"[{name}] already enabled.")

    if args.disable:
        for name in args.disable:
            if state.is_on(name):
                msg = state.toggle(name)
                if msg:
                    print(f"Notice: {msg}")
                if not state.is_on(name):
                    print(f"Disabled [{name}]")
                    changed = True
            else:
                print(f"[{name}] already disabled.")

    if args.apply:
        if not state.changed():
            print("No changes to apply.")
            return
        state.reviewed_hash = state.fingerprint()
        confirm_fn = (lambda msg: "y") if args.yes else input
        ok = apply_changes(state, print, confirm=confirm_fn)
        if not ok:
            sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conf", default=DEFAULT_CONF, help="dnf.conf to edit (default /etc/dnf/dnf.conf)")
    ap.add_argument("--repos-dir", default=REPO_DIR, help="directory with *.repo files (default /etc/yum.repos.d)")
    ap.add_argument("--catalog", default=CATALOG_PATH, help="repo catalog file (default repos.catalog next to this script)")
    ap.add_argument("--plan", action="store_true", help="print current diff and exit (no TUI/TTY needed)")
    ap.add_argument("--live", action="store_true", help="check each repo's aarch64 build as you walk the cards")
    ap.add_argument("--mode", choices=("choose", "single", "grouped"), default="choose",
                    help="start mode: choose (startup prompt), single (walk options), or grouped (full deck)")

    # Hybrid CLI / TUI interface options
    ap.add_argument("--cli", action="store_true", help="force robust command-line text interface (no curses)")
    ap.add_argument("--tui", action="store_true", help="force curses terminal UI")
    ap.add_argument("-y", "--yes", action="store_true", help="assume yes for confirmations in CLI mode")

    # Direct non-interactive batch actions
    ap.add_argument("--list", action="store_true", help="list all catalog and installed repositories with status")
    ap.add_argument("--list-options", action="store_true", help="list all dnf.conf options and their current values")
    ap.add_argument("--enable", nargs="+", metavar="REPO", help="enable one or more repositories")
    ap.add_argument("--disable", nargs="+", metavar="REPO", help="disable one or more repositories")
    ap.add_argument("--set", nargs="+", metavar="KEY=VALUE", help="set one or more dnf.conf options")
    ap.add_argument("--unset", nargs="+", metavar="KEY", help="unset one or more dnf.conf options")
    ap.add_argument("--apply", action="store_true", help="apply pending/staged changes through the dry-run gate")

    args = ap.parse_args()

    if not os.path.exists(args.conf):
        sys.exit(f"{args.conf} not found")
    if not os.path.exists(args.catalog):
        sys.exit(f"catalog {args.catalog} not found")

    state = State(args.conf, args.repos_dir, args.catalog, live=args.live)

    # 1. Non-interactive direct query/batch flags
    if args.plan:
        d = difflib.unified_diff(
            state.dnf_conf.orig.splitlines(),
            state.proposed_conf().splitlines(),
            fromfile=args.conf, tofile=args.conf + " (proposed)", lineterm="", n=2)
        out = "\n".join(d)
        print(out if out else "No changes.")
        return

    if args.list:
        cli_list_repos(state, use_color=sys.stdout.isatty())
        return

    if args.list_options:
        cli_list_options(state, use_color=sys.stdout.isatty())
        return

    if args.enable or args.disable or args.set or args.unset or args.apply:
        cli_run_batch(state, args)
        return

    # 2. Determine whether to run Curses TUI or CLI
    if args.cli:
        CLI(state, mode=args.mode, yes=args.yes).run()
        return

    if not sys.stdin.isatty():
        if args.tui:
            sys.exit("Error: --tui requested but standard input is not a terminal (TTY).")
        print("[Notice] Non-interactive environment detected (no TTY). Current configuration plan:")
        d = difflib.unified_diff(
            state.dnf_conf.orig.splitlines(),
            state.proposed_conf().splitlines(),
            fromfile=args.conf, tofile=args.conf + " (proposed)", lineterm="", n=2)
        out = "\n".join(d)
        print(out if out else "No changes.")
        return

    term = os.environ.get("TERM", "")
    use_tui = not (term in ("", "dumb", "unknown"))

    if args.tui and not use_tui:
        print(f"[Warning] TERM='{term}' is unsuitable for curses, but --tui was forced.")
        use_tui = True

    if use_tui:
        try:
            curses.wrapper(lambda scr: UI(scr, state, args.mode).run())
            return
        except (KeyboardInterrupt, SystemExit):
            return
        except Exception as e:
            if args.tui:
                sys.exit(f"Curses TUI error: {e}")
            print(f"\n[Notice] Curses TUI unavailable or failed to initialize ({e}).")
            print("[Notice] Gracefully falling back to robust CLI interface...\n")

    try:
        CLI(state, mode=args.mode, yes=args.yes).run()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
