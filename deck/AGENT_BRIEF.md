# AGENT_BRIEF.md — Asahi bundle (for opencode / Claude Code; agy secondary)

## Context
- Device: M1 MacBook Air running **Fedora Asahi Remix** (aarch64, 16K-page `kernel-16k`, dnf5).
- Owner: Cody (DaRipper91). Sister bundles: da-hp (CachyOS, pacman), Pixel 10 Pro (Termux apt), Nothing 2a (Termux pacman).
- Entry point: `configure-dnf.sh`. Data: `repos.catalog` (INI) and `dnf.conf` (template). Engine: `lib/walk.sh` + `lib/dryrun-gate.sh`.
- Alternative entry point: `asahi-deck.py` — a curses TUI that walks the same `dnf.conf` options and `repos.catalog`, with the same dry-run gate and refusal rules. Use it for interactive review; `configure-dnf.sh` for scripted/non-interactive changes.

## Rules
1. **Dry run first.** Never call `configure-dnf.sh apply` without a passing dry run. The gate enforces this; don't bypass it with `DRYRUN_GATE_CHAINED=1`. The TUI's Apply button also requires a reviewed diff before it will apply.
2. **Never enable anything that replaces Mesa** (terra-mesa, negativo17) or the Asahi kernel. Never disable `fedora`, `updates` or the required Asahi COPRs (`asahi-kernel`, `asahi-u-boot`, `asahi-branding`).
3. **Never set `gpgcheck=False`**, and never add `--nogpgcheck` to commands.
4. New repo → add a block to `repos.catalog` with: `cat`, `kind`, `ids`, `top`, `info`. Add `warn:` / `testing: yes` / `signed: no` / `setup: REFUSED — reason` where they apply. Verify the aarch64 build with `--live` before you call it supported. If you don't know its top packages, write `(run configure-dnf.sh --live)` rather than guessing.
5. Don't hardcode repo counts in docs.
6. Work on a branch and open a PR. Include the `configure-dnf.sh` dry-run output (or TUI review diff) in the PR description.

## Test without the MacBook
```bash
printf '[main]\ngpgcheck=True\n' > /tmp/d.conf
printf '%s\n' fedora updates > /tmp/ids.txt
./configure-dnf.sh --conf /tmp/d.conf --repos-from /tmp/ids.txt --stage-dir /tmp/st < answers.txt
bash -n configure-dnf.sh lib/*.sh
```
