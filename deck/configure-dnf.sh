#!/usr/bin/env bash
# configure-dnf.sh — interactive dnf5 + repo configurator for Fedora Asahi Remix
# on the M1 MacBook Air ("asahi"). Same rules as the pacman bundles:
# nothing changes without a staged diff and a passing dry run.
#
#   ./configure-dnf.sh                  # walk dnf.conf options → walk repos → stage + diff + dry run
#   ./configure-dnf.sh apply            # apply the staged plan (dry-run gated)
#   ./configure-dnf.sh list             # every catalog repo: status, category, info
#   ./configure-dnf.sh enable rpmfusion-free tailscale   # stage just these (then: apply)
#   ./configure-dnf.sh disable docker-ce
#   ./configure-dnf.sh --live           # cards also check the repo has an aarch64 build + last update
#   ./configure-dnf.sh --tui            # launch the curses TUI control deck (asahi-deck.py)
#   ./configure-dnf.sh --deck           # launch asahi-deck.py (hybrid TUI/CLI auto-detected)
#
# Testing flags: --conf FILE (dnf.conf to read), --repos-from FILE (enabled repo ids,
# one per line, instead of asking dnf), --stage-dir DIR.
set -uo pipefail

SELF="$(readlink -f "$0")"; HERE="$(cd "$(dirname "$SELF")" && pwd)"
source "$HERE/lib/dryrun-gate.sh" || exit 1
source "$HERE/lib/walk.sh" || exit 1
gate_parse "$@"; set -- ${GATE_ARGS[@]+"${GATE_ARGS[@]}"}

CMD="walk"; NAMES=(); LIVE=0; CONF_OVERRIDE=""; REPOS_FROM=""; STAGE_DIR=""
while (( $# )); do
  case "$1" in
    apply|list|enable|disable) CMD="$1" ;;
    --tui)
      if [[ -f "$HERE/asahi-deck.py" ]]; then
        exec /usr/bin/python3 "$HERE/asahi-deck.py" --tui "$@"
      fi
      die "--tui requested but asahi-deck.py not found in $HERE"
      ;;
    --deck)
      if [[ -f "$HERE/asahi-deck.py" ]]; then
        exec /usr/bin/python3 "$HERE/asahi-deck.py" "$@"
      fi
      die "--deck requested but asahi-deck.py not found in $HERE"
      ;;
    --live) LIVE=1 ;;
    --conf) CONF_OVERRIDE="$2"; shift ;;
    --repos-from) REPOS_FROM="$2"; shift ;;
    --stage-dir) STAGE_DIR="$2"; shift ;;
    -h|--help) sed -n '2,15p' "$SELF"; exit 0 ;;
    -*) die "unknown option $1" ;;
    *) NAMES+=("$1") ;;
  esac; shift
done

SUDO="sudo"; (( EUID == 0 )) && SUDO=""
TARGET_CONF="${CONF_OVERRIDE:-/etc/dnf/dnf.conf}"
TEMPLATE="$HERE/dnf.conf"; CATALOG="$HERE/repos.catalog"
STAGE_DIR="${STAGE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/configure-dnf}"
mkdir -p "$STAGE_DIR" || die "can't create $STAGE_DIR"
STAGED="$STAGE_DIR/dnf.conf.staged"; PLAN="$STAGE_DIR/repo-plan.txt"; SNAP="$STAGE_DIR/current-dnf.conf"

# --------------------------------------------------------------- detection ---
OS_NAME="$(. /etc/os-release 2>/dev/null; echo "${NAME:-unknown}")"
FEDORA="$(rpm -E %fedora 2>/dev/null)"; [[ "$FEDORA" =~ ^[0-9]+$ ]] || FEDORA="$(. /etc/os-release 2>/dev/null; echo "${VERSION_ID:-0}")"
ARCH="$(uname -m)"; PAGESZ="$(getconf PAGESIZE 2>/dev/null || echo '?')"
ASAHI=0
{ [[ "$OS_NAME" == *Asahi* ]] || rpm -q fedora-asahi-remix-release-common >/dev/null 2>&1 || [[ "$(uname -r)" == *asahi* ]]; } && ASAHI=1
summary() {
  hr; echo "  ${B}${BLU}dnf configurator${R}  ${D}(dry-run gated · nothing changes without a diff)${R}"; hr
  printf '  %-12s %s\n' "System:" "${B}$OS_NAME${R} ${FEDORA:+(Fedora $FEDORA)}"
  printf '  %-12s %s\n' "Host:" "$(hostname 2>/dev/null || cat /etc/hostname 2>/dev/null)  ${D}kernel $(uname -r)${R}"
  printf '  %-12s %s\n' "Arch:" "$ARCH  ${D}page size: $PAGESZ$([[ $PAGESZ == 16384 ]] && echo ' (16K — Apple Silicon kernel)')${R}"
  printf '  %-12s %s\n' "dnf:" "$(dnf --version 2>/dev/null | head -1 || echo 'not found')"
  printf '  %-12s %s\n' "Config:" "$TARGET_CONF"
  printf '  %-12s %s\n' "Staging:" "$STAGE_DIR"
  (( ASAHI )) || warn "this doesn't look like Fedora Asahi Remix — the catalog is built for it (aarch64)"
  [[ "$ARCH" == aarch64 ]] || warn "arch is $ARCH; repo choices here assume aarch64"
  hr
}

# ------------------------------------------------------------- repo state ---
catalog_load "$CATALOG"
ENABLED_IDS=""
if [[ -n "$REPOS_FROM" ]]; then ENABLED_IDS="$(cat "$REPOS_FROM")"
elif command -v dnf >/dev/null; then ENABLED_IDS="$(dnf repo list --enabled 2>/dev/null | awk 'NR>1 && $1!="" {print $1}')"
fi
if command -v flatpak >/dev/null; then ENABLED_IDS+=$'\n'"$(flatpak remotes --columns=name 2>/dev/null | sed 's/^/flatpak:/')"; fi
for n in "${RNAMES[@]}"; do
  st="off"
  if [[ "$(rget "$n" kind)" == flatpak ]]; then
    grep -qx "flatpak:$(rget "$n" remote)" <<<"$ENABLED_IDS" && st="on"
  else
    for id in $(rget "$n" ids); do grep -qx "$id" <<<"$ENABLED_IDS" && st="on"; done
  fi
  RCUR[$n]="$st"; WANT[$n]="$st"
done

repo_cmds() {   # repo_cmds NAME enable|disable → shell commands, one per line
  local n="$1" act="$2" k id url
  k="$(rget "$n" kind)"
  case "$k:$act" in
    builtin:enable)  for id in $(rget "$n" ids); do echo "$SUDO dnf config-manager setopt $id.enabled=1"; done ;;
    builtin:disable) for id in $(rget "$n" ids); do echo "$SUDO dnf config-manager setopt $id.enabled=0"; done ;;
    copr:enable)     echo "$SUDO dnf copr enable $(rget "$n" copr)" ;;
    copr:disable)    echo "$SUDO dnf copr disable $(rget "$n" copr)" ;;
    rpm:enable)      url="$(rget "$n" url)"; echo "$SUDO dnf install ${url//\{FEDORA\}/$FEDORA}" ;;
    rpm:disable)     echo "$SUDO dnf remove $(rget "$n" pkg)" ;;
    repofile:enable) echo "$SUDO dnf config-manager addrepo --from-repofile=$(rget "$n" url)" ;;
    repofile:disable|repofile-inline:disable)
                     echo "$SUDO cp -a $(rget "$n" file) $STAGE_DIR/ 2>/dev/null; $SUDO rm -f $(rget "$n" file)" ;;
    repofile-inline:enable)
                     echo "$SUDO rpm --import $(rget "$n" key)"
                     echo "printf '%b\\n' '$(rget "$n" content)' | $SUDO tee $(rget "$n" file) >/dev/null" ;;
    terra:enable)    echo "$SUDO dnf install --repofrompath 'terra,https://repos.fyralabs.com/terra\$releasever' --setopt='terra.gpgkey=https://repos.fyralabs.com/terra\$releasever/key.asc' terra-release" ;;
    terra:disable)   echo "$SUDO dnf remove terra-release" ;;
    flatpak:enable)  echo "$SUDO flatpak remote-add --if-not-exists $(rget "$n" remote) $(rget "$n" url)" ;;
    flatpak:disable) echo "$SUDO flatpak remote-delete $(rget "$n" remote)" ;;
  esac
}

# ------------------------------------------------------------ live checks ---
repo_extra() {
  (( LIVE )) || return 0
  local n="$1" k base hdr code lm url own proj
  k="$(rget "$n" kind)"
  case "$k" in
    copr)
      own="${1%%/*}"; own="$(rget "$n" copr)"; proj="${own#*/}"; own="${own%%/*}"
      if curl -sf --max-time 10 "https://copr.fedorainfracloud.org/api_3/project?ownername=${own}&projectname=${proj}" 2>/dev/null | grep -q "fedora-$FEDORA-aarch64"; then
        echo "    ${GRN}live:${R} COPR builds fedora-$FEDORA-aarch64"
      else echo "    ${YEL}live:${R} no fedora-$FEDORA-aarch64 chroot found (or COPR unreachable)"; fi ;;
    repofile)
      base="$(curl -sf --max-time 10 "$(rget "$n" url)" 2>/dev/null | sed -n 's/^baseurl *= *//p' | head -1)"
      [[ -z "$base" ]] && { echo "    ${D}live: couldn't read the .repo file (offline?)${R}"; return; }
      base="${base//\$basearch/aarch64}"; base="${base//\$releasever/$FEDORA}"
      hdr="$(curl -sIL --max-time 10 "${base%/}/repodata/repomd.xml" 2>/dev/null | tr -d '\r')"
      code="$(awk '/^HTTP/{c=$2} END{print c}' <<<"$hdr")"; lm="$(awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}' <<<"$hdr")"
      [[ "$code" == 200 ]] && echo "    ${GRN}live:${R} aarch64 repo reachable · last updated ${lm:-?}" \
                           || echo "    ${YEL}live:${R} no aarch64 repodata (HTTP ${code:-none}) at $base" ;;
    rpm)
      url="$(rget "$n" url)"; [[ -z "$url" ]] && return
      code="$(curl -sIL --max-time 10 -o /dev/null -w '%{http_code}' "${url//\{FEDORA\}/$FEDORA}" 2>/dev/null)"
      [[ "$code" == 200 ]] && echo "    ${GRN}live:${R} release package for Fedora $FEDORA exists" || echo "    ${YEL}live:${R} release package not found (HTTP ${code:-none})" ;;
    *) echo "    ${D}live: (no live check for kind '$k')${R}" ;;
  esac
}

# ============================================================== LIST ===
if [[ "$CMD" == list ]]; then
  printf "%-26s %-8s %-34s %s\n" REPO STATUS CATEGORY INFO
  for n in "${RNAMES[@]}"; do
    st="${RCUR[$n]}"; [[ "$st" == on ]] && st="ON"; is_refused "$n" && st="refused"
    printf "%-26s %-8s %-34s %s\n" "$n" "$st" "$(rget "$n" cat)" "$(rget "$n" info | cut -c1-70)"
  done
  exit 0
fi

# ============================================================= APPLY ===
if [[ "$CMD" == apply ]]; then
  [[ -f "$STAGED" && -f "$PLAN" ]] || die "nothing staged — run ./configure-dnf.sh first"
  cat "$TARGET_CONF" > "$SNAP" 2>/dev/null || : > "$SNAP"
  GATE_NAME="configure-dnf-apply"
  GATE_INPUTS=("$SELF" "$STAGED" "$PLAN" "$SNAP" "$CATALOG")
  GATE_EXTRA="$TARGET_CONF $FEDORA $(sort <<<"$ENABLED_IDS" | tr '\n' ' ')"
  gate_begin
  summary
  run() { if (( APPLY )); then echo "+ $*"; eval "$@"; else echo "[dry-run] $*"; fi; }
  echo "  ${B}dnf.conf: current → staged${R}"
  diff -u --label "current $TARGET_CONF" --label staged "$SNAP" "$STAGED" && echo "  (no differences)"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  echo; echo "  ${B}Repo plan${R}"; [[ -s "$PLAN" ]] || echo "  (no repo changes)"
  if ! cmp -s "$SNAP" "$STAGED"; then
    (( APPLY )) && [[ "$(readlink -f "$TARGET_CONF")" != /etc/dnf/dnf.conf ]] && die "--conf is for testing; applying only works on /etc/dnf/dnf.conf"
    run "$SUDO cp -a '$TARGET_CONF' '$TARGET_CONF.bak-$STAMP'"
    run "$SUDO install -m 644 '$STAGED' '$TARGET_CONF'"
  fi
  while read -r act n; do
    [[ -z "${act:-}" ]] && continue
    echo "  -- $act [$n]"
    while IFS= read -r c; do [[ -n "$c" ]] && run "$c"; done < <(repo_cmds "$n" "$act")
  done < "$PLAN"
  # dnf asks to import each new repo's signing key here — check the fingerprint against the vendor's site
  run "$SUDO dnf makecache --refresh"
  echo
  echo "  Rollback dnf.conf: ${CYN}$SUDO cp $TARGET_CONF.bak-$STAMP $TARGET_CONF${R}"
  echo "  Repo changes are undone with the opposite command (configure-dnf.sh disable/enable <name>)."
  exit 0
fi

# ============================================== WALK / ENABLE / DISABLE ===
summary
CUR="$(mktemp)"; STAGE="$(mktemp)"; trap 'rm -f "$CUR" "$STAGE" "$STAGE.tmp"' EXIT
cat "$TARGET_CONF" > "$CUR" 2>/dev/null || { warn "can't read $TARGET_CONF — starting from the bundle defaults"; : > "$CUR"; }

OPTS="$(cat <<'EOF'
gpgcheck|Safety|bool|True|Verify every package's OpenPGP signature. Turning this off lets any mirror or repo feed you modified packages.|True (always) · False (refused unless you type yes)
installonly_limit|Safety|custom|3|How many kernels (kernel-16k) and other install-only packages are kept side by side. 0 = unlimited, 1 isn't allowed.|2 (tight disk) · 3 (default) · 5 (kernel testing)
protect_running_kernel|Safety|bool|True|Never remove the kernel you're booted into.|True · False
clean_requirements_on_remove|Safety|bool|True|dnf remove also removes dependencies nothing else needs.|True · False
best|Safety|bool|False|True = always demand the newest version or fail. False = fall back to an older one when the newest can't install (Fedora's default; friendlier with COPRs).|False · True
skip_if_unavailable|Safety|bool|True|If a repo can't be reached (a COPR missing your release right after an upgrade), skip it instead of failing the whole update.|True (recommended with COPRs) · False (strict)
excludepkgs|Safety|text|__absent__|Packages dnf must never install or update (globs OK). For pinning after a regression.|(unset) · mesa* · kernel*
max_parallel_downloads|Speed|int:1:20|10|Packages downloaded at once (default 3, max 20).|3 (default) · 10 (recommended) · 20 (max)
max_downloads_per_mirror|Speed|int:1:20|3|Parallel downloads from a single mirror.|3 (default) · 5
fastestmirror|Speed|bool|False|Probe mirror latency and pick the fastest. Fedora's metalink already geo-sorts; probing usually costs more than it saves.|False (recommended) · True (bad local mirrors)
metadata_expire|Speed|custom|43200|How often repo metadata is re-checked. Seconds, or with s/m/h/d suffix, or never.|172800 (default 48h) · 43200 (12h) · 6h · never
zchunk|Speed|bool|True|Delta-download repo metadata when available. Smaller, faster refreshes.|True · False
keepcache|Speed|bool|False|Keep downloaded RPMs after installing.|False (saves SSD) · True (offline reinstalls)
install_weak_deps|Speed|bool|True|Install Recommends/Supplements too. False = leaner installs, occasionally missing an expected extra.|True · False
timeout|Speed|int:5:300|30|Seconds a slow connection may stay under minrate before aborting.|30 (default) · 60 (bad Wi-Fi)
defaultyes|Candy|bool|True|Enter means Yes at prompts (you're still asked).|True · False
color_list_available_upgrade|Candy|color|bold,cyan|Color for upgradable packages in lists.|bold,cyan · bold,blue
color_list_available_downgrade|Candy|color|dim,magenta|Color for downgrades.|dim,magenta
color_list_available_reinstall|Candy|color|bold,green|Color for reinstallable packages.|bold,green
color_list_available_install|Candy|color|bold,blue|Color for installable packages.|bold,blue
color_update_installed|Candy|color|dim,red|Installed version in update listings.|dim,red
color_update_local|Candy|color|dim,green|Locally available version in update listings.|dim,green
color_update_remote|Candy|color|bold,magenta|Remote (new) version in update listings.|bold,magenta · bold,green
color_search_match|Candy|color|bold,magenta|Highlight of the matched text in dnf search.|bold,magenta · bold,yellow
EOF
)"
declare -A GROUP TYPE REC CURV CHOICE EXPL EXMP; KEYS=()
cur_val() { awk -v k="$1" -F= '/^\[main\]/{m=1;next} /^\[/{m=0} m && $1==k {sub(/^[^=]*=/,""); v=$0} END{print (v==""?"__absent__":v)}' "$CUR"; }
while IFS='|' read -r k g t r e x; do
  [[ -z "$k" ]] && continue
  KEYS+=("$k"); GROUP[$k]="$g"; TYPE[$k]="$t"; REC[$k]="$r"; EXPL[$k]="$e"; EXMP[$k]="$x"
  CURV[$k]="$(cur_val "$k")"
  [[ "${CURV[$k]}" != __absent__ ]] && CHOICE[$k]="${CURV[$k]}" || CHOICE[$k]="${REC[$k]}"
done <<<"$OPTS"

opt_note() { [[ "$1" == installonly_limit && "$PAGESZ" == 16384 ]] && echo "    ${YEL}asahi:${R} each kernel-16k set is ~100–300 MB in /boot + /lib/modules"; return 0; }
opt_validate() {
  local k="$1" v="$2" t
  case "$k" in
    gpgcheck) [[ "$v" == False ]] && { warn "gpgcheck=False disables package signature checks"; return 2; } ;;
    installonly_limit)
      [[ "$v" =~ ^[0-9]+$ ]] || { echo "    ${RED}✗${R} a whole number"; return 1; }
      (( v == 1 )) && { echo "    ${RED}✗${R} 1 isn't allowed (it would block kernel upgrades)"; return 1; }
      (( v == 0 )) && { warn "0 = keep every kernel forever"; return 2; } ;;
    metadata_expire)
      [[ "$v" =~ ^([0-9]+[smhd]?|-1|never)$ ]] || { echo "    ${RED}✗${R} seconds, 6h-style, -1 or never"; return 1; } ;;
    color_*)
      for t in ${v//,/ }; do
        [[ "$t" =~ ^(black|red|green|yellow|blue|magenta|cyan|white|bold|dim|underline|blink|reverse)$ ]] || { echo "    ${RED}✗${R} '$t' isn't a dnf5 color word"; return 1; }
      done ;;
    max_parallel_downloads) (( v > 15 )) && warn "above ~15 rarely helps and some mirrors rate-limit" ;;
  esac
  return 0
}

if [[ "$CMD" == walk ]]; then
  echo; echo "  ${B}${BLU}Step 1 · dnf.conf [main]${R}  ${D}Enter = keep · r = recommended · - = unset · s = skip to repos${R}"
  options_walk
  echo; echo "  ${B}${BLU}Step 2 · repositories (aarch64)${R}  ${D}e enable · d disable · k/Enter keep · c category · q review${R}"
  (( LIVE )) && note "--live: checking each repo for an aarch64 build as you go"
  repo_walk
else
  # non-interactive enable/disable of named repos; dnf.conf stays as it is
  for k in "${KEYS[@]}"; do CHOICE[$k]="${CURV[$k]}"; done
  (( ${#NAMES[@]} )) || die "name at least one repo (see: configure-dnf.sh list)"
  for n in "${NAMES[@]}"; do
    [[ -n "$(rget "$n" kind)" ]] || die "[$n] isn't in the catalog (see: configure-dnf.sh list)"
    card "$n"
    if [[ "$CMD" == enable ]]; then try_enable "$n" && echo "    ${GRN}✓ will be ON${R}"; else try_disable "$n" && echo "    ${D}✓ will be OFF${R}"; fi
  done
fi
enforce_refusals
for n in "${RNAMES[@]}"; do   # dependency: e.g. rpmfusion-free-tainted needs rpmfusion-free
  d="$(rget "$n" needs)"; [[ -n "$d" && "${WANT[$n]}" == on && "${WANT[$d]}" != on ]] && { warn "[$n] needs [$d] → enabling [$d] too"; WANT[$d]="on"; }
done

# ----------------------------------------------------------------- render ---
cp "$TEMPLATE" "$STAGE"
set_kv() {   # set_kv KEY VALUE|__absent__  (inside [main])
  awk -v k="$1" -v v="$2" '
    FNR==NR { if ($0 ~ /^\[main\]/) m=1; else if ($0 ~ /^\[/) m=0
              if (m && ($0 ~ "^#?" k "=")) { if (!f) f=FNR }
              if (m && $0 !~ /^[[:space:]]*$/) last=FNR; next }
    { if ($0 ~ /^\[main\]/) m=1; else if ($0 ~ /^\[/) m=0 }
    m && FNR==f { if (v=="__absent__") { print ($0 ~ /^#/) ? $0 : "#" $0 }
                  else { cur=$0; sub(/^[^=]*=/, "", cur); print ($0 !~ /^#/ && cur==v) ? $0 : k "=" v }
                  next }
    m && f && ($0 ~ "^" k "=") { next }
    { print }
    !f && v!="__absent__" && FNR==last { print k "=" v }' "$STAGE" "$STAGE" > "$STAGE.tmp" && mv "$STAGE.tmp" "$STAGE"
}
for k in "${KEYS[@]}"; do set_kv "$k" "${CHOICE[$k]}"; done
# keep any [main] keys you set that this configurator doesn't manage
extra="$(awk -F= '/^\[main\]/{m=1;next} /^\[/{m=0} m && /^[a-z_]+=/ {print $1}' "$CUR" | while read -r k; do
  [[ " ${KEYS[*]} " == *" $k "* ]] || grep -m1 "^$k=" "$CUR"; done)"
[[ -n "$extra" ]] && printf '\n# --- carried over from your previous dnf.conf ---\n%s\n' "$extra" >> "$STAGE"
awk '/^\[/ && !/^\[main\]/{s=1} s' "$CUR" >> "$STAGE"

repo_plan > "$PLAN.new"
cp "$STAGE" "$STAGED"; mv "$PLAN.new" "$PLAN"; cp "$STAGE" "$STAGE_DIR/dnf.conf.$(date +%Y%m%d-%H%M%S)"

echo; hr; echo "  ${B}${BLU}Review${R}"; hr
for k in "${KEYS[@]}"; do [[ "${CHOICE[$k]}" != "${CURV[$k]}" ]] && printf '    %-32s %s → %s\n' "$k" "$(shown "${CURV[$k]}")" "$(shown "${CHOICE[$k]}")"; done
while read -r act n; do [[ -n "${act:-}" ]] && printf '    %-32s %s\n' "[$n]" "$act"; done < "$PLAN"
echo; echo "  ${B}${BLU}Diff: current → staged dnf.conf${R}"
diff -u --label "current $TARGET_CONF" --label staged "$CUR" "$STAGE" && echo "  (identical)"

echo; echo "  ${B}${BLU}Dry run of the apply step${R}"
bash "$SELF" apply --dry-run --stage-dir "$STAGE_DIR" ${CONF_OVERRIDE:+--conf "$CONF_OVERRIDE"} ${REPOS_FROM:+--repos-from "$REPOS_FROM"}
rc=$?
echo
if (( rc == 0 )); then echo "  ${GRN}${B}Staged and dry-run tested.${R} To apply it:  ${CYN}$SELF apply${CONF_OVERRIDE:+ --conf $CONF_OVERRIDE}${REPOS_FROM:+ --repos-from $REPOS_FROM}${R}"
else echo "  ${RED}${B}The dry run failed${R} — nothing was changed."; fi
exit "$rc"
