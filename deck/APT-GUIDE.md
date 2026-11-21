# APT-GUIDE.md — Pixel 10 Pro / Termux APT Directives

A guide to APT and repository tuning on Android 17 (Tensor G5 blazer, aarch64).

---

## ⚙️ Core Configuration Directives (`99pixel-deck`)

### 🛡️ Safety & Integrity
- **`Acquire::AllowInsecureRepositories "false"`**:
  Refuses any repository that fails OpenPGP signature verification. Protects mobile devices when connecting through public Wi-Fi or cellular networks.
- **`Acquire::Check-Valid-Until "true"`**:
  Requires `Release` files to have unexpired timestamps. Defends against replay attacks from outdated or spoofed mirrors.

### ⚡ Speed & Latency Optimization
- **`Acquire::Languages "none"`**:
  Disables automatic downloading of localized `Translation-*` packages. Eliminates several megabytes of redundant downloads per `apt update` on cellular connections and reduces I/O wear on flash storage.
- **`Acquire::http::Pipeline-Depth "5"`**:
  Enables HTTP keepalive pipelining up to 5 concurrent requests over a single TCP socket, significantly cutting connection handshakes.
- **`Acquire::http::Timeout "20"`**:
  Lowers connection timeout from default 120s down to 20s. Prevents hanging on unresponsive mirrors during mobile handoffs.
- **`Acquire::Retries "3"`**:
  Automatically retries transient connection drops typical of mobile cellular environments.

### 💾 Memory & Flash Storage Preservation
- **`APT::Install-Recommends "false"`**:
  Stops APT from installing recommended extra packages. Essential on Android to protect the **~2.5–3.0 GB userland memory headroom** from unnecessary background daemon bloat.
- **`APT::Install-Suggests "false"`**:
  Disables suggested package installs.
- **`APT::Clean-Installed "true"`**:
  Immediately unlinks cached `.deb` archives after installation. Preserves internal UFS 4.0 flash storage.

### 🍭 Terminal Candy & DPkg Safety
- **`APT::Color "1"`**:
  Forces vibrant ANSI colored terminal output in Termux sessions.
- **`DPkg::Options { "--force-confdef"; "--force-confold"; }`**:
  Prevents interactive stdin prompts during batch package upgrades.

---

## 📦 Curated Repository Catalog

| Repository | Category | State | Description |
|---|---|---|---|
| `termux-main` | Official & Core Overlays | **REQ** | Core Bionic userland base packages. |
| `termux-main-cf` | Official & Core Overlays | Opt | Cloudflare CDN edge-cached mirror. |
| `termux-main-direct` | Official & Core Overlays | Opt | Direct origin mirror (packages.termux.dev). |
| `termux-x11` | Official & Core Overlays | Opt | Termux:X11 and Wayland desktop packages. |
| `termux-root` | Official & Core Overlays | **RSH** | Privileged packages requiring root or Shizuku `rish`. |
| `tur-repo` | Community & TUR | Opt | Termux User Repository (ripgrep-all, modern CLI tools). |
| `tur-on-device` | Community & TUR | **TST** | On-device compiled toolchains and rust nightly (bundled in `tur-repo`). |
| `glibc-repo` | Community & TUR | Opt | Glibc runtime runner for standard Linux binaries. |
| `termux-gui-repo` | Community & TUR | Opt | Native Android Jetpack Compose / GUI bindings (`termux-gui-package`). |
| `tailscale` | Security & Infrastructure | Opt | Mesh VPN client daemon (operates via Android VPN or userspace Go binary). |
| `wireguard-tools` | Security & Infrastructure | **RSH** | WireGuard management tools. |
| `tor-repo` | Security & Infrastructure | Opt | Official Tor Project onion routing overlay. |
| `science-repo` | Dev & Scientific | Opt | NumPy, SciPy, OpenBLAS, and gfortran libraries. |
| `game-repo` | Dev & Scientific | Opt | Terminal emulators, DOSBox, and interactive engines. |
| `tur-multilib` | Refused / Incompatible | **REF** | Unsupported on Tensor G5 pure 64-bit hardware (no AArch32 EL0 mode). |
| `debian-raw-ppa` | Refused / Incompatible | **REF** | Incompatible with Android Bionic libc. |
| `pacman-termux-repo`| Refused / Incompatible | **REF** | Corrupts Termux APT dpkg state database. |
| `x86_64-foreign-repos`| Refused / Incompatible | **REF** | Cannot execute natively on Tensor G5 aarch64. |
| `unsigned-http-repo`| Refused / Incompatible | **REF** | Bypasses mandatory OpenPGP signature verification. |
