#!/usr/bin/env bash
# configure-apt.sh — interactive apt/pkg + repo configurator for Google Pixel 10 Pro (Termux)
# Same rules as the Asahi dnf bundle: nothing changes without a staged diff and a passing dry run.
#
#   ./configure-apt.sh                  # walk apt.conf options → walk repos → stage + diff + dry run
#   ./configure-apt.sh apply            # apply the staged plan (dry-run gated)
#   ./configure-apt.sh list             # every catalog repo: status, category, info
#   ./configure-apt.sh enable x11-repo tur-repo   # stage just these (then: apply)
#   ./configure-apt.sh disable tur-multilib
#   ./configure-apt.sh --live           # cards probe mirror availability
#
# Testing flags: --conf FILE, --sources-dir DIR, --stage-dir DIR.
set -uo pipefail

SELF="$(readlink -f "$0")"; HERE="$(cd "$(dirname "$SELF")" && pwd)"
source "$HERE/lib/dryrun-gate.sh" || exit 1
source "$HERE/lib/walk.sh" || exit 1
gate_parse "$@"; set -- ${GATE_ARGS[@]+"${GATE_ARGS[@]}"}

CMD="walk"; NAMES=(); LIVE=0; CONF_OVERRIDE=""; SOURCES_OVERRIDE=""; CATALOG_OVERRIDE=""; STAGE_DIR=""
while (( $# )); do
  case "$1" in
    apply|list|enable|disable|add-repo) CMD="$1" ;;
    --live) LIVE=1 ;;
    --conf) CONF_OVERRIDE="$2"; shift ;;
    --sources-dir) SOURCES_OVERRIDE="$2"; shift ;;
    --catalog) CATALOG_OVERRIDE="$2"; shift ;;
    --stage-dir) STAGE_DIR="$2"; shift ;;
    -h|--help) sed -n '2,15p' "$SELF"; exit 0 ;;
    -*) die "unknown option $1" ;;
    *) NAMES+=("$1") ;;
  esac; shift
done

# Detect Termux prefix vs standard root
TERMUX_PREFIX="/data/data/com.termux/files/usr"
if [[ -d "$TERMUX_PREFIX" ]]; then
  DEFAULT_APT_CONF="$TERMUX_PREFIX/etc/apt/apt.conf.d/99pixel-deck"
  DEFAULT_SOURCES_DIR="$TERMUX_PREFIX/etc/apt/sources.list.d"
  DEFAULT_SOURCES_LIST="$TERMUX_PREFIX/etc/apt/sources.list"
else
  DEFAULT_APT_CONF="/etc/apt/apt.conf.d/99pixel-deck"
  DEFAULT_SOURCES_DIR="/etc/apt/sources.list.d"
  DEFAULT_SOURCES_LIST="/etc/apt/sources.list"
fi

TARGET_CONF="${CONF_OVERRIDE:-$DEFAULT_APT_CONF}"
TARGET_SOURCES_DIR="${SOURCES_OVERRIDE:-$DEFAULT_SOURCES_DIR}"
TEMPLATE="$HERE/apt.conf"; CATALOG="${CATALOG_OVERRIDE:-$HERE/termux-repos.catalog}"
STAGE_DIR="${STAGE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/configure-apt}"
mkdir -p "$STAGE_DIR" || die "can't create $STAGE_DIR"
STAGED_CONF="$STAGE_DIR/apt.conf.staged"
PLAN="$STAGE_DIR/repo-plan.txt"
SNAP="$STAGE_DIR/apt.conf.orig"

# --------------------------------------------------------------- detection ---
ARCH="$(uname -m 2>/dev/null || echo 'aarch64')"
IS_TERMUX=0; [[ -d "$TERMUX_PREFIX" ]] && IS_TERMUX=1
DEVICE="Google Pixel 10 Pro (Tensor G5 blazer)"
PKG_MGR="apt"
command -v pkg >/dev/null && PKG_MGR="pkg"

summary() {
  hr; echo "  ${B}${BLU}Pixel 10 Pro / Termux APT Configurator${R}  ${D}(dry-run gated · zero-trust diff)${R}"; hr
  printf '  %-14s %s\n' "Device:" "${B}$DEVICE${R}"
  printf '  %-14s %s\n' "Host:" "$(hostname 2>/dev/null || echo 'da-pixel-10-pro')"
  printf '  %-14s %s\n' "Architecture:" "$ARCH ${D}(Tensor G5 / arm64-v8a)${R}"
  printf '  %-14s %s\n' "Manager:" "$PKG_MGR"
  printf '  %-14s %s\n' "Target Conf:" "$TARGET_CONF"
  printf '  %-14s %s\n' "Sources Dir:" "$TARGET_SOURCES_DIR"
  printf '  %-14s %s\n' "Staging Dir:" "$STAGE_DIR"
  [[ "$ARCH" == aarch64 ]] || warn "Architecture is $ARCH; Pixel 10 Pro repos require aarch64"
  hr
}

# ------------------------------------------------------------- repo state ---
catalog_load "$CATALOG"
declare -A RCUR WANT

# Query installed packages once to avoid O(N) dpkg-query forks on Android flash
INSTALLED_PKGS=""
if command -v dpkg-query >/dev/null; then
  INSTALLED_PKGS=" $(dpkg-query -W -f='${Package} ${Status}\n' 2>/dev/null | awk '/install ok installed/ {print $1}') "
fi

is_repo_enabled() {
  local n="$1"
  local k="$(rget "$n" kind)"
  local pkg="$(rget "$n" pkg)"
  local ids="$(rget "$n" ids)"
  
  if [[ "$k" == "builtin" ]]; then
    return 0 # termux-main always base
  fi
  if [[ -f "$TARGET_SOURCES_DIR/${n}.list" ]]; then
    return 0
  fi
  if [[ "$k" == "pkg" && -n "$pkg" ]]; then
    if [[ "$INSTALLED_PKGS" == *" $pkg "* ]]; then
      return 0
    fi
  fi
  if [[ "$k" == "listfile" || "$k" == "pkg" ]]; then
    for id in $ids; do
      if grep -rqs "$id" "$TARGET_SOURCES_DIR" "$DEFAULT_SOURCES_LIST" 2>/dev/null; then
        return 0
      fi
    done
  fi
  return 1
}

for n in "${RNAMES[@]}"; do
  st="off"
  if is_repo_enabled "$n"; then st="on"; fi
  RCUR[$n]="$st"; WANT[$n]="$st"
done

repo_cmds() {
  local n="$1" act="$2"
  local k="$(rget "$n" kind)"
  local pkg="$(rget "$n" pkg)"
  local ids="$(rget "$n" ids)"
  
  if [[ "$k" == "pkg" && -n "$pkg" ]]; then
    if [[ "$act" == "enable" ]]; then
      echo "pkg install -y $pkg"
    else
      echo "pkg uninstall -y $pkg"
    fi
  elif [[ "$k" == "listfile" ]]; then
    local listfile="$TARGET_SOURCES_DIR/${n}.list"
    if [[ "$act" == "enable" ]]; then
      local url="$(rget "$n" url)"
      if [[ "$url" =~ ^deb ]]; then
        echo "printf '%s\n' \"$url\" > \"$listfile\""
      else
        echo "printf 'deb %s stable main\n' \"$url\" > \"$listfile\""
      fi
    else
      echo "rm -f \"$listfile\""
    fi
  elif [[ "$k" == "mirror" ]]; then
    if [[ "$act" == "enable" ]]; then
      case "$n" in
        termux-main-cf)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://packages-cf.termux.dev/apt/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
        termux-main-direct)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://packages.termux.dev/apt/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
        grimler-mirror)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://grimler.se/termux/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
        fcix-mirror)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://mirror.fcix.net/termux/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
        bfsu-mirror)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://mirrors.bfsu.edu.cn/termux/apt/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
        tuna-mirror)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
        librehat-mirror)
          echo "sed -i -E 's|https://[^ ]+/apt/termux-main|https://termux.librehat.com/apt/termux-main|g' \"$DEFAULT_SOURCES_LIST\"" ;;
      esac
    fi
  fi
}

resolve_repo_name() {
  local target="$1"
  if [[ -n "$(rget "$target" cat)" ]]; then
    echo "$target"
    return 0
  fi
  for r in "${RNAMES[@]}"; do
    if [[ "$(rget "$r" pkg)" == "$target" ]]; then
      echo "$r"
      return 0
    fi
    for id in $(rget "$r" ids); do
      if [[ "$id" == "$target" ]]; then
        echo "$r"
        return 0
      fi
    done
  done
  echo "$target"
}

# ============================================================= APPLY ===
if [[ "$CMD" == "apply" ]]; then
  [[ -f "$STAGED_CONF" && -f "$PLAN" ]] || die "nothing staged — run ./configure-apt.sh or pixel-deck first"
  cat "$TARGET_CONF" > "$SNAP" 2>/dev/null || : > "$SNAP"
  GATE_NAME="pixel-apt-deck"
  GATE_INPUTS=("$SELF" "$STAGED_CONF" "$PLAN" "$SNAP" "$CATALOG")
  GATE_EXTRA="host=$(hostname 2>/dev/null) target=$TARGET_CONF"
  gate_begin
  summary

  run() {
    if (( APPLY )); then
      echo "+ $*"
      eval "$@"
    else
      echo "[dry-run] $*"
    fi
  }

  echo "  ${B}apt.conf: current → staged${R}"
  diff -u --label "current $TARGET_CONF" --label staged "$SNAP" "$STAGED_CONF" || true

  STAMP="$(date +%Y%m%d-%H%M%S)"
  echo; echo "  ${B}Repository Action Plan:${R}"
  if [[ -s "$PLAN" ]]; then
    while read -r name action; do
      [[ -z "$name" ]] && continue
      printf '  - %-7s %s\n' "$action" "$name"
    done < "$PLAN"
  else
    echo "  (No repository status changes staged)"
  fi

  if ! cmp -s "$SNAP" "$STAGED_CONF"; then
    if [[ -f "$TARGET_CONF" ]]; then
      run "cp -a '$TARGET_CONF' '$TARGET_CONF.bak-$STAMP'"
    fi
    run "mkdir -p '$(dirname "$TARGET_CONF")'"
    run "install -m 644 '$STAGED_CONF' '$TARGET_CONF'"
  fi

  if [[ -s "$PLAN" ]]; then
    while read -r name action; do
      [[ -z "$name" ]] && continue
      echo "Executing: $action $name..."
      while IFS= read -r cmd_line; do
        [[ -z "$cmd_line" ]] && continue
        run "$cmd_line"
      done < <(repo_cmds "$name" "$action")
    done < "$PLAN"
  fi

  if (( APPLY )); then
    echo "✓ Pixel 10 Pro configuration applied successfully."
  else
    echo
    hr
    echo "  ${GRN}${B}Dry run passed and stamped.${R} To apply it:  ${CYN}$SELF apply${CONF_OVERRIDE:+ --conf $CONF_OVERRIDE}${R}"
  fi
  exit 0
fi

# --------------------------------------------------------------- commands ---
if [[ "$CMD" == "list" ]]; then
  summary
  printf '  %-22s %-5s %-30s %s\n' "REPO" "STATE" "CATEGORY" "TOP PACKAGES"
  hr
  for n in "${RNAMES[@]}"; do
    printf '  %-22s %-5s %-30s %s\n' "$n" "${RCUR[$n]}" "$(rget "$n" cat)" "$(rget "$n" top | cut -c1-35)"
  done
  echo
  exit 0
fi

if [[ "$CMD" == "enable" || "$CMD" == "disable" ]]; then
  (( ${#NAMES[@]} )) || die "specify at least one repository name to $CMD"
  target_state="off"; [[ "$CMD" == "enable" ]] && target_state="on"
  for raw_name in "${NAMES[@]}"; do
    n="$(resolve_repo_name "$raw_name")"
    [[ -n "$(rget "$n" cat)" ]] || die "unknown repository: $raw_name"
    warn_text="$(rget "$n" warn)"
    [[ -z "$warn_text" ]] && warn_text="$(rget "$n" setup)"
    if [[ -n "$warn_text" && "$target_state" == "on" ]]; then
      warn "[$n] advisory: $warn_text"
    fi
    WANT[$n]="$target_state"
  done
fi

if [[ "$CMD" == "add-repo" ]]; then
  (( ${#NAMES[@]} >= 2 )) || die "usage: $SELF add-repo <name> <deb-line>"
  raw_name="${NAMES[0]}"
  deb_line="${NAMES[*]:1}"
  clean_name="$(echo "$raw_name" | tr -c '[:alnum:]_-' '-' | sed 's/^-//;s/-$//')"
  [[ -n "$clean_name" ]] || die "invalid repository name: $raw_name"
  [[ "$deb_line" =~ ^deb ]] || deb_line="deb $deb_line"
  if [[ ! "$deb_line" =~ \[.*\] ]]; then
    deb_line="$(echo "$deb_line" | sed 's/^deb /deb [trusted=yes] /')"
  fi

  if ! grep -q "^\[$clean_name\]" "$CATALOG" 2>/dev/null; then
    if [[ -w "$CATALOG" ]]; then
      printf '\n[%s]\ncat: Custom Repositories\nkind: listfile\nurl: %s\nids: %s\ninfo: Custom user repository\n' "$clean_name" "$deb_line" "$clean_name" >> "$CATALOG"
      catalog_load "$CATALOG"
    fi
  fi
  RCUR[$clean_name]="${RCUR[$clean_name]:-off}"
  WANT[$clean_name]="on"
  echo "Custom repository [$clean_name] staged for enablement."
fi

if [[ "$CMD" == "walk" ]]; then
  summary
  echo "  Walking Pixel 10 Pro repository configuration..."
  echo
  for n in "${RNAMES[@]}"; do
    cat_name="$(rget "$n" cat)"
    req="$(rget "$n" required)"
    if [[ "$req" == "yes" ]]; then
      WANT[$n]="on"; continue
    fi
    echo "  [${B}${CYN}$n${R}] — $(rget "$n" info)"
    echo "    Category: $cat_name"
    echo "    Flagship packages: $(rget "$n" top)"
    warn_text="$(rget "$n" warn)"
    [[ -n "$warn_text" ]] && warn "$warn_text"
    ask a "Enable [$n]? [current: ${RCUR[$n]}] (y/n/keep):"
    case "$a" in
      y|Y|yes) WANT[$n]="on" ;;
      n|N|no)  WANT[$n]="off" ;;
      *) WANT[$n]="${RCUR[$n]}" ;;
    esac
    echo
  done
fi

# ------------------------------------------------------------ dry-run stage ---
mkdir -p "$STAGE_DIR"
cp "$TEMPLATE" "$STAGED_CONF"
cat "$TARGET_CONF" > "$SNAP" 2>/dev/null || : > "$SNAP"

: > "$PLAN"
for n in "${RNAMES[@]}"; do
  cur="${RCUR[$n]:-off}"; want="${WANT[$n]:-off}"
  if [[ "$cur" != "$want" ]]; then
    act="enable"; [[ "$want" == "off" ]] && act="disable"
    echo "$n $act" >> "$PLAN"
  fi
done

# Run dry run of apply to produce stamp
bash "$SELF" apply --dry-run \
  --stage-dir "$STAGE_DIR" \
  ${CONF_OVERRIDE:+--conf "$CONF_OVERRIDE"} \
  ${SOURCES_OVERRIDE:+--sources-dir "$SOURCES_OVERRIDE"} \
  ${CATALOG_OVERRIDE:+--catalog "$CATALOG_OVERRIDE"}
rc=$?
exit "$rc"
