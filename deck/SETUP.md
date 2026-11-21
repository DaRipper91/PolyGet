# SETUP.md — Asahi bundle, step by step

Every step that changes something is gated. The first run is a dry run. Run the same command again with nothing changed, and it applies.

1. **Copy the folder** to the MacBook and open a terminal in it:
   `chmod +x configure-dnf.sh`
2. **Look first:** `./configure-dnf.sh list`. Shows every repo, ON or off, with its category. The Asahi COPRs and fedora/updates should already be ON.
3. **Walk it:** `./configure-dnf.sh --live`.
   - *Step 1, options:* Enter keeps a value, `r` takes the recommended one, `-` unsets it, `s` skips ahead to the repos.
   - *Step 2, repos:* `e` enables, `d` disables, Enter keeps, `c` filters by category, `q` goes to the review.
   - Suggested first picks: `rpmfusion-free`, `flathub`, `tailscale`, plus whichever dev repos you use.
   - At the end you see the review, the diff, and a dry run of the apply step.

   **TUI alternative:** `./asahi-deck.py --live` opens a curses interface with the same options and repos. Navigate with arrows, toggle with Enter, filter by category with Left/Right, search with `/`, review the diff on the Review tab, then Apply. The TUI enforces the same dry-run gate: review the diff to completion before Apply will work.

4. **Apply:** run the command it prints, `./configure-dnf.sh apply`. dnf asks before importing each new repo key. Compare the fingerprint with the vendor's site, then answer `y`.
5. **Codecs** (if you enabled rpmfusion-free): `sudo dnf swap ffmpeg-free ffmpeg --allowerasing`.
6. **Upgrade:** `sudo dnf upgrade --refresh`. You'll see the new colors, and 10 downloads at once.
7. **Later changes:** `./configure-dnf.sh enable NAME` or `./configure-dnf.sh disable NAME`, then `./configure-dnf.sh apply`. Each one dry-runs first.
8. **After each Fedora upgrade:** run `./configure-dnf.sh --live` and look for COPRs without a build for the new release. `skip_if_unavailable=True` keeps updates working until they catch up.

Undo: `sudo cp /etc/dnf/dnf.conf.bak-<stamp> /etc/dnf/dnf.conf`. For repos, run the opposite enable or disable, or `dnf history undo N`.

## Install into your app drawer

```
bash install.sh --user      # installs to ~/.local (no root needed)
# or
sudo bash install.sh --system  # installs to /usr/local (all users)
```

This installs the `asahi-deck` command, an SVG icon, and a `.desktop` entry so "Asahi Control Deck" appears in your application launcher. It launches through `konsole -e` so it opens in a real terminal. User-mode installs rewrite the desktop entry to use absolute paths, so desktop services don't need to inherit your PATH.

After installing, run `asahi-deck` from any terminal or open it from your app drawer. On first launch it walks the dnf.conf options, then the repo cards; nothing changes to your system until you press Apply on a reviewed diff.
