# PIXEL_BRIEF.md — Pixel 10 Pro Native Termux Bundle

## Hardware & Operating Context
- **Device:** Google Pixel 10 Pro (`da-pixel-10-pro`).
- **SoC & Architecture:** Google Tensor G5 (`blazer`, 1x Cortex-X4 @ 3.78GHz + 5x Cortex-A725 @ 3.05GHz + 2x Cortex-A520 @ 2.25GHz), ARM64 (`aarch64`), Android 17.
- **Userland Environment:** Termux non-root userland paired with Shizuku (`rish`).
- **Memory Ceiling:** 16 GB physical RAM with **~2.5–3.0 GB userland headroom**. Local LLMs strictly limited to ≤3B parameters (`qwen2.5-coder:3b`, `llama3.2:3b`) to avoid Android Low Memory Killer (LMK) termination.
- **Package Manager:** Native Termux `apt` / `pkg`. STRICT: Never execute `dnf` or `pacman`.

## Control Engines
- **Interactive TUI:** `pixel-deck.py` (symlinked as `termux-deck.py`). Walks APT performance/safety parameters, toggles curated catalog repositories with category filters, searches live packages, and stages changes with diff preview.
- **Scripted CLI:** `configure-apt.sh`. Headless and batch administration engine utilizing `lib/walk.sh` and `lib/dryrun-gate.sh`.
- **Target Configuration:** `/data/data/com.termux/files/usr/etc/apt/apt.conf.d/99pixel-deck` (or `/etc/apt/apt.conf.d/99pixel-deck` in PRoot).
- **Catalog:** `termux-repos.catalog` (INI-style catalog defining official, TUR, security, and refused repositories).

## Safety Directives & Guardrails
1. **Zero-Trust Dry-Run Gate:** No configuration modification or repository mutation is applied without a verified staged diff and a passing dry-run fingerprint.
2. **Never Disable `termux-main`:** Core system utilities rely on Bionic libc runtime packages.
3. **Mandatory Signature Enforcement:** `Acquire::AllowInsecureRepositories` is permanently locked to `false`. Unsigned repositories are refused.
4. **Preserve Memory & Storage Headroom:** `APT::Install-Recommends` and `APT::Install-Suggests` remain `false` to avoid bloat exhausting userland RAM.
5. **Privileged Operations (`needs-root`):** Repositories requiring elevated privileges (`termux-root`, `wireguard-tools`) are flagged with `RSH` badges and require Shizuku `rish` or explicit user confirmation.
