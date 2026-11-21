#!/usr/bin/env bash
set -euo pipefail
src_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mode=${1:---user}
case "$mode" in
  --termux) exec "$src_dir/install-termux.sh" "${@:2}" ;;
  --user) prefix="${HOME}/.local" ;;
  --system) prefix=/usr/local ;;
  *) printf 'Usage: %s [--user|--system|--termux]\n' "$0" >&2; exit 2 ;;
esac
# DESTDIR supports reviewing the exact installation tree without root.
install_root="${DESTDIR:-}${prefix}"
if [[ "$mode" == --system && -z ${DESTDIR:-} && $EUID != 0 ]]; then
  printf 'System installation needs root. Run: sudo bash %q --system\n' "$src_dir/install.sh" >&2
  exit 1
fi
install -Dm755 "$src_dir/asahi-deck.py" "$install_root/lib/asahi-deck/asahi-deck.py"
install -Dm644 "$src_dir/repos.catalog" "$install_root/lib/asahi-deck/repos.catalog"
install -d "$install_root/bin"
# Derive the installed location from the launcher, supporting both prefixes.
cat > "$install_root/bin/asahi-deck" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
launcher_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$launcher_dir/../lib/asahi-deck/asahi-deck.py" "$@"
LAUNCHER
chmod 755 "$install_root/bin/asahi-deck"
install -Dm644 "$src_dir/asahi-deck.svg" "$install_root/share/icons/hicolor/scalable/apps/asahi-deck.svg"
install -Dm644 "$src_dir/asahi-deck.desktop" "$install_root/share/applications/asahi-deck.desktop"
# The user entry uses absolute paths so desktop services need not inherit PATH.
if [[ "$mode" == --user ]]; then
  python - "$install_root/share/applications/asahi-deck.desktop" "$prefix" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]);prefix=sys.argv[2]
def quoted(value):
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
s=p.read_text().replace('Exec=konsole -e asahi-deck', 'Exec=konsole -e '+quoted(prefix+'/bin/asahi-deck'))
s=s.replace('TryExec=konsole', 'TryExec='+prefix+'/bin/asahi-deck')
s=s.replace('Icon=asahi-deck','Icon='+prefix+'/share/icons/hicolor/scalable/apps/asahi-deck.svg')
p.write_text(s)
PY
fi
if [[ -z ${DESTDIR:-} ]]; then
  if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$install_root/share/applications"
  fi
  if command -v gtk-update-icon-cache >/dev/null && [[ -f "$install_root/share/icons/hicolor/index.theme" ]]; then
    gtk-update-icon-cache -f -t "$install_root/share/icons/hicolor"
  fi
fi
printf 'Installed Asahi Control Deck into %s\n' "$install_root"
