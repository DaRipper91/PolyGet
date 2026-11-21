# DNF-GUIDE.md — dnf5 and repos on Fedora Asahi Remix (M1 MacBook Air)

What every option in `dnf.conf` does, and every repo in `repos.catalog`: what it holds, whether it's worth having on Apple Silicon, and what replaces it. `configure-dnf.sh` shows the same text on its cards.

## How dnf differs from pacman

| pacman (da-hp) | dnf5 (asahi) |
|---|---|
| One `pacman.conf` with every repo | `/etc/dnf/dnf.conf` holds options; each repo is its own file in `/etc/yum.repos.d/*.repo` |
| Repo order decides which repo wins | Version decides; on a tie, `priority=` (lower wins), then `cost=` |
| `pacman-key` imports keys first | dnf asks to import a repo's key the first time it uses it. Check the fingerprint against the vendor's site before you say yes |
| `-Syu` | `dnf upgrade --refresh` |
| AUR | COPR (`dnf copr enable owner/project`): prebuilt user repos, one per project |

## Apple Silicon rules

- **Never replace Mesa.** Asahi ships its own GPU driver stack. Any repo that carries `mesa-*` (Terra's mesa subrepo, negativo17) can swap it out and leave you with software rendering or a black screen. The configurator refuses those repos. RPM Fusion is allowed because it doesn't ship Mesa. Use it for codecs (`dnf swap ffmpeg-free ffmpeg --allowerasing`), never for drivers.
- **The kernel comes from the Asahi COPR.** `@asahi/kernel` builds `kernel-16k`. Disabling that COPR stops kernel updates, so the configurator won't let you.
- **16K pages.** Some prebuilt aarch64 software assumes 4K pages and crashes on start (older Chromium/Electron builds, some JITs). If an app won't open, check for a newer build, or a Flatpak, before you blame the repo.
- **x86-only vendors.** Google Chrome, Microsoft Edge, the NVIDIA drivers and Steam-from-RPM-Fusion have no aarch64 builds. They're refused. Steam runs through Asahi's own `asahi-steam` (FEX + muvm).

## [main] options

`True`/`False` options accept `1`/`0` too. The configurator writes `True`/`False`.

### Safety

| Option | Best | Second best | Notes |
|---|---|---|---|
| `gpgcheck` | `True` | none | Checks each package's signature. `False` lets any mirror feed you modified packages. The configurator asks you to type `yes` before turning it off. |
| `installonly_limit` | `3` | `2` (tight `/boot`) | Kernels kept side by side. Each `kernel-16k` set is ~100–300 MB across `/boot` and `/lib/modules`. `1` is rejected because it blocks upgrades. `0` keeps every kernel forever. |
| `protect_running_kernel` | `True` | none | dnf will never remove the kernel you're booted into. |
| `clean_requirements_on_remove` | `True` | `False` | `dnf remove` also removes dependencies nothing else needs. Undo with `dnf history undo`. |
| `best` | `False` | `True` | `True` fails a transaction when the newest version can't install. `False` falls back to an older one, which helps when a COPR lags behind Fedora. |
| `skip_if_unavailable` | `True` | `False` | A COPR that hasn't built for your release yet (common the week after a Fedora upgrade) is skipped instead of blocking every update. Use `False` if you'd rather get an error. |
| `excludepkgs` | unset | `mesa*`, a regression | Pins packages. Remove the pin once the fix lands, or you fall behind on security updates. |

### Speed

| Option | Best | Second best | Notes |
|---|---|---|---|
| `max_parallel_downloads` | `10` | `3` (default) | Max 20. Above ~15 rarely helps, and some mirrors rate-limit. |
| `max_downloads_per_mirror` | `3` | `5` | Parallel connections to one mirror. |
| `fastestmirror` | `False` | `True` | Fedora's metalink already sorts mirrors by location. Probing them every time costs more than it saves, unless your local mirrors are bad. |
| `metadata_expire` | `43200` (12 h) | `172800` (48 h default) | How often repo metadata is re-checked. Accepts seconds, `6h`-style suffixes, `-1` or `never`. `dnf upgrade --refresh` always re-checks anyway. |
| `zchunk` | `True` | none | Delta-downloads metadata where repos support it. |
| `keepcache` | `False` | `True` (offline reinstalls) | Keeps downloaded RPMs. The SSD is shared with macOS, so space is tight. |
| `install_weak_deps` | `True` | `False` (lean) | Installs Recommends. `False` saves space, but you may miss expected extras like fonts or codecs. |
| `timeout` | `30` | `60` (bad Wi-Fi) | Seconds a stalled download may run before dnf aborts it. |

### Candy

`defaultyes=True` makes Enter mean Yes, but dnf still asks first. The `color_*` options take comma-separated words: `black red green yellow blue magenta cyan white bold dim underline blink reverse`. The configurator rejects anything else.

| Option | Bundle value |
|---|---|
| `color_list_available_upgrade` | `bold,cyan` |
| `color_list_available_downgrade` | `dim,magenta` |
| `color_list_available_reinstall` | `bold,green` |
| `color_list_available_install` | `bold,blue` |
| `color_update_installed` | `dim,red` |
| `color_update_local` | `dim,green` |
| `color_update_remote` | `bold,magenta` |
| `color_search_match` | `bold,magenta` |

Any `[main]` keys you set yourself are kept under "carried over from your previous dnf.conf".

## Repos

**Kind** tells you how the configurator turns a repo on and off:

- **builtin**: `dnf config-manager setopt ID.enabled=1/0`
- **copr**: `dnf copr enable/disable`
- **rpm**: installs or removes a `*-release` package
- **repofile**: adds or removes a vendor `.repo` file
- **flatpak**: `flatpak remote-add/remote-delete`

| Repo | What's in it | On the MacBook | Alternative |
|---|---|---|---|
| fedora, updates | The distro | **Required** | none |
| updates-testing | Updates awaiting karma | Only to test a fix (asks first) | `dnf upgrade --enablerepo=updates-testing PKG` for a single package |
| fedora-cisco-openh264 | H.264 for Firefox and WebRTC | Keep | RPM Fusion ffmpeg |
| asahi-kernel, asahi-u-boot, asahi-branding | Kernel, boot chain, remix packages | **Required** | none |
| asahi-scripts | Firmware, m1n1 and boot helpers | Keep | none |
| asahi-steam | The only working Steam on Apple Silicon | If you game | none |
| rpmfusion-free | Full ffmpeg, codecs, VLC | Recommended for media | Flathub apps bring their own codecs |
| rpmfusion-nonfree | Smaller on aarch64 | Optional; needs free | none |
| rpmfusion-free-tainted | libdvdcss | Only for DVDs; needs free | none |
| terra | Fyra Labs extra packages | Optional (asks; its Mesa/NVIDIA subrepos are refused) | COPR for single apps |
| flathub | Flatpak apps | Recommended | none |
| vscode, docker-ce, gh-cli | Vendor repos | Enable what you use | Flathub VS Code (sandboxed) |
| copr-starship, copr-lazygit, copr-nerd-fonts | Candy CLI tools | Nice to have | cargo/go installs |
| brave-browser, vivaldi | Browsers | Check for an aarch64 build with `--live` | Firefox from fedora |
| 1password | Password manager | Check for an aarch64 build with `--live` | Flathub |
| tailscale | Mesh VPN | Recommended (ties the MacBook to da-hp and the phones) | none |
| asahi-alpha | Pre-release Asahi bits | Testing only | none |
| **refused** | terra-mesa, terra-nvidia, rpmfusion-nonfree-nvidia, rpmfusion-nonfree-steam, negativo17-multimedia, google-chrome, microsoft-edge | Would replace Asahi's Mesa, or have no aarch64 build | See each card |

`--live` checks each repo against its live source as you walk the cards. COPR projects are checked for a `fedora-<N>-aarch64` build. `.repo` files are checked for `repodata/repomd.xml` and its Last-Modified date. Release RPMs are checked for the file itself. Run it right after each Fedora upgrade, because that's when COPRs lag behind.

## Handy commands

```bash
dnf repo list --all                      # every repo and its state
dnf repo info rpmfusion-free             # one repo's details
dnf history list / dnf history undo N    # roll back a transaction
dnf swap ffmpeg-free ffmpeg --allowerasing   # after enabling rpmfusion-free
dnf check-upgrade --refresh
sudo asahi-diagnose                      # Asahi's own system report (asahi-scripts)
```
