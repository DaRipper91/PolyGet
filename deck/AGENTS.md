# repo-config-deck — Agent Operating Guide & Architecture Blueprint

## 🌌 Project Identity & Scope
`repo-config-deck` is the hardware-guarded package configuration and repository control deck for two specialized aarch64 operating environments:
1. **Apple Silicon M1/M2/M3 on Fedora Asahi Remix:** Driven by `asahi-deck.py` (curses TUI) and `configure-dnf.sh` (CLI). Enforces strict hardware safety to protect the custom 16k page-size kernel and custom Mesa GPU driver stack from destructive third-party repository overwrites.
2. **Google Pixel 10 Pro on Android 17 / Termux:** Driven by `pixel-deck.py` (symlinked as `termux-deck.py`) and `configure-apt.sh` (CLI). Tunes APT parameters to protect physical RAM ceilings (~2.5–3.0 GB userland headroom) and UFS flash storage.

---

## 🔒 Hard Invariant Rules & Safety Guardrails

### 1. Apple Silicon Asahi Invariants
- **Zero-Trust Dry-Run Gate:** Never invoke `configure-dnf.sh apply` without a preceding passing dry run. The TUI's Apply button strictly requires a reviewed diff before applying.
- **Never Replace Mesa or Kernel:** Under no circumstances enable repositories that overwrite Asahi's Mesa stack (`terra-mesa`, `negativo17`) or replace `kernel-16k`. Never disable `fedora`, `updates`, or the critical Asahi COPRs (`asahi-kernel`, `asahi-u-boot`, `asahi-branding`).
- **Strict GPG Enforcement:** Never set `gpgcheck=False`, and never pass `--nogpgcheck` to DNF commands.
- **Elevations & Pipelines:** Do not stack `sudo sudo`. When writing repofiles via shell pipelines (`printf | sudo tee`), always execute via `bash -c`.

### 2. Google Pixel Termux Invariants
- **Never Disable `termux-main`:** Core utilities depend on Bionic libc runtime packages.
- **Strict Signature Policy:** `Acquire::AllowInsecureRepositories` is permanently locked to `false`. Unsigned third-party repositories are refused.
- **Preserve Memory Ceiling:** Keep `APT::Install-Recommends "false"` and `APT::Install-Suggests "false"` to prevent daemon bloat from triggering the Android Low Memory Killer (LMK).
- **Package Manager Boundary:** On Android/Termux, use `apt` / `pkg`. STRICT: Never run `dnf` or `pacman`.

---

## 🏗️ Repository Layout & Dual-Engine Topology
```
repo-config-deck/
├── asahi-deck.py           # Interactive curses TUI for Fedora Asahi Remix
├── configure-dnf.sh        # Headless & scripted CLI engine for DNF5
├── dnf.conf                # Reference DNF5 template (10 downloads, zchunk)
├── repos.catalog           # INI catalog of verified / refused Fedora COPRs
├── pixel-deck.py           # Interactive curses TUI for Pixel / Termux
├── termux-deck.py          # Symlink to pixel-deck.py
├── configure-apt.sh        # Headless & scripted CLI engine for Termux APT
├── apt.conf                # Reference Termux APT configuration template
├── termux-repos.catalog    # INI catalog of curated Termux / TUR mirrors
├── lib/
│   ├── dryrun-gate.sh      # Preflight dry-run validator and diff hasher
│   └── walk.sh             # Interactive option walker engine
├── tests/
│   ├── test_apply_changes.py # Tests for asahi-deck apply, sudo, and pipelines
│   ├── test_configure_apt.py # Tests for configure-apt CLI dry-run and apply
│   └── test_pixel_deck.py    # Tests for pixel-deck TUI state and catalog
└── install.sh              # System / user installer (--termux flag supported)
```

---

## 🛠️ Verification Runbooks

### Run Test Suite
```bash
pytest tests/ -q
```

### Launch Interactive Asahi TUI (Fedora)
```bash
./asahi-deck.py
```

### Launch Interactive Pixel TUI (Termux)
```bash
./pixel-deck.py
```

### Scripted DNF Dry-Run (Fedora)
```bash
./configure-dnf.sh walk
```

### Scripted APT Dry-Run (Termux)
```bash
./configure-apt.sh walk
```
