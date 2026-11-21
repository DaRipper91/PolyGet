# walk.sh — shared engine for configure-dnf.sh and configure-apt.sh
#
# Provides:
#   UI helpers ........ hr, die, warn, note, wrap, ask, confirm_yes
#   catalog_load FILE . parses an INI-style repo catalog into R_* arrays
#   options_walk ...... one-by-one walk over KEYS[] (Enter keep · r recommended · - unset · s skip)
#   repo_walk ......... one card per repo (e enable · d disable · k keep · c category · q review)
#
# Catalog format (one block per repo, blank line between blocks):
#   [name]
#   cat: <Category>            one of CATS[]
#   kind: <type>               interpreted by the calling script
#   top: a, b, c               flagship packages
#   info: one line description
#   warn: shown before enabling; needs "yes"
#   setup: REFUSED — reason    hard-blocked
#   signed: no                 unsigned/unverified → needs "yes"
#   testing: yes               pre-release → needs "yes"
#   required: yes              can't be disabled
#   needs-root: yes            blocked when the device isn't rooted
#   any other "key: value" line is kept in R_<KEY> style via rget NAME KEY

if [[ -t 1 ]]; then
  B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'; RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'
  BLU=$'\e[38;5;75m'; VIO=$'\e[38;5;141m'; CYN=$'\e[36m'
else B=; D=; R=; RED=; GRN=; YEL=; BLU=; VIO=; CYN=; fi
hr()   { printf '%s\n' "${D}──────────────────────────────────────────────────────────────────────────${R}"; }
die()  { echo "${RED}ERROR:${R} $*" >&2; exit 1; }
warn() { echo "  ${YEL}!${R} $*"; }
note() { echo "  ${D}$*${R}"; }
wrap() { fold -s -w 76 | sed 's/^/    /'; }
ask()  { local __v; if ! IFS= read -r -p "  ${VIO}›${R} $2 " __v; then __v=""; echo; fi; printf -v "$1" '%s' "$__v"; }
confirm_yes() { local a; ask a "$1 Type ${B}yes${R} to confirm:"; [[ "$a" == "yes" ]]; }
shown() { case "$1" in __absent__) echo "${D}(unset — default)${R}" ;; *) echo "${B}$1${R}" ;; esac; }

CATS=("Official & Core Overlays" "Prebuilt AUR & Convenience" "Dev, Toolchains & Scientific" "Desktop, Apps & Pro Audio"
      "Kernels & Graphics Bleeding-Edge" "Security & Infrastructure" "Personal & Single-Maintainer AUR" "Refused / Incompatible")

# ------------------------------------------------------------ catalog ---
declare -A RFIELD      # RFIELD["name|key"]=value
RNAMES=()
catalog_load() {
  local line name="" k v
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^\[([^]]+)\]$ ]]; then name="${BASH_REMATCH[1]}"; RNAMES+=("$name"); continue; fi
    [[ -z "$line" ]] && { name=""; continue; }
    [[ -n "$name" && "$line" =~ ^([A-Za-z0-9_-]+):[[:space:]]?(.*)$ ]] || continue
    k="${BASH_REMATCH[1]}"; v="${BASH_REMATCH[2]}"
    if [[ -n "${RFIELD[$name|$k]+x}" ]]; then RFIELD[$name|$k]+=$'\n'"$v"; else RFIELD[$name|$k]="$v"; fi
  done < "$1"
}
rget() { printf '%s' "${RFIELD[$1|$2]:-}"; }

# ------------------------------------------------------- options walk ---
# Caller sets: KEYS[] and assoc arrays GROUP TYPE REC CURV CHOICE EXPL EXMP
# Types: bool (True/False) · flag (on/off) · int:LO:HI · enum:a;b;c · text · path · custom
# Optional hooks: opt_note KEY (extra lines) · opt_validate KEY VALUE → 0 ok · 1 reject · 2 confirm
options_walk() {
  local k t lastg="" a hint lo hi ok v rc
  SKIP_OPTS=0
  for k in "${KEYS[@]}"; do
    (( SKIP_OPTS )) && break
    t="${TYPE[$k]}"
    if [[ "${GROUP[$k]}" != "$lastg" ]]; then lastg="${GROUP[$k]}"; echo; hr; echo "  ${B}${VIO}${lastg}${R}"; hr; fi
    echo; echo "  ${B}${CYN}$k${R}"
    echo "${EXPL[$k]}" | wrap
    declare -F opt_note >/dev/null && opt_note "$k"
    echo "    current: $(shown "${CURV[$k]}")   recommended: $(shown "${REC[$k]}")   ${D}Enter keeps:${R} $(shown "${CHOICE[$k]}")"
    echo "    ${D}examples: ${EXMP[$k]}${R}"
    while :; do
      case "$t" in bool|flag) hint="[y/n]" ;; *) hint="value" ;; esac
      ask a "$k $hint:"
      case "$a" in
        "")  break ;;
        s|S) SKIP_OPTS=1; break ;;
        r|R) CHOICE[$k]="${REC[$k]}"; break ;;
        -)   if [[ "$t" == flag ]]; then CHOICE[$k]="off"; else CHOICE[$k]="__absent__"; fi; break ;;
      esac
      v=""; rc=1
      case "$t" in
        bool) case "$a" in y|Y|yes|true|True|1) v="True"; rc=0 ;; n|N|no|false|False|0) v="False"; rc=0 ;; *) echo "    ${RED}✗${R} y or n" ;; esac ;;
        flag) case "$a" in y|Y|yes|on) v="on"; rc=0 ;; n|N|no|off) v="off"; rc=0 ;; *) echo "    ${RED}✗${R} y or n" ;; esac ;;
        int:*) IFS=: read -r _ lo hi <<<"$t"
               if [[ "$a" =~ ^[0-9]+$ ]] && (( a >= lo && a <= hi )); then v="$a"; rc=0; else echo "    ${RED}✗${R} whole number $lo–$hi"; fi ;;
        enum:*) ok=0; local vals; IFS=';' read -ra vals <<<"${t#enum:}"; local x; for x in "${vals[@]}"; do [[ "$a" == "$x" ]] && ok=1; done
                (( ok )) && { v="$a"; rc=0; } || echo "    ${RED}✗${R} one of: ${t#enum:}" ;;
        path) [[ "$a" == /* ]] && { v="$a"; rc=0; } || echo "    ${RED}✗${R} absolute path required" ;;
        *)    v="$a"; rc=0 ;;
      esac
      (( rc == 0 )) || continue
      if declare -F opt_validate >/dev/null; then
        opt_validate "$k" "$v"; rc=$?
        if (( rc == 1 )); then continue; fi
        if (( rc == 2 )); then confirm_yes "Use it anyway?" || continue; fi
      fi
      CHOICE[$k]="$v"; break
    done
  done
}

# ---------------------------------------------------------- repo walk ---
# Caller sets: RNAMES (via catalog_load), assoc WANT and RCUR (on/off), and may define
#   repo_extra NAME (extra card lines, e.g. live data) · repo_valid NAME (0 = show, 1 = hide)
declare -A WANT RCUR
is_refused() { [[ "$(rget "$1" setup)" == REFUSED* ]]; }
needs_root_blocked() { [[ "$(rget "$1" needs-root)" == yes && "${ROOTED:-0}" != 1 ]]; }

card() {
  local n="$1" st
  [[ "${WANT[$n]}" == on ]] && st="${GRN}${B}ON${R}" || st="${D}OFF${R}"
  { is_refused "$n" || needs_root_blocked "$n"; } && st="${RED}${B}REFUSED${R}"
  echo; hr
  printf '  %s  %s   %s\n' "${B}${CYN}[$n]${R}" "$st" "${D}now: ${RCUR[$n]} · $(rget "$n" cat)${R}"
  [[ -n "$(rget "$n" info)" ]] && rget "$n" info | wrap
  local sig="signed"; [[ "$(rget "$n" signed)" == no ]] && sig="${YEL}UNSIGNED / unverified${R}"
  echo "    signing: $sig   ${D}kind: $(rget "$n" kind)${R}"
  [[ -n "$(rget "$n" warn)" ]] && echo "    ${YEL}warn:${R} $(rget "$n" warn)"
  [[ -n "$(rget "$n" setup)" ]] && echo "    ${RED}setup:${R} $(rget "$n" setup)"
  needs_root_blocked "$n" && echo "    ${RED}blocked:${R} needs a rooted device"
  echo "    top: $(rget "$n" top)"
  declare -F repo_extra >/dev/null && repo_extra "$n"
}

try_enable() {
  local n="$1"
  if is_refused "$n"; then echo "    ${RED}✗ blocked:${R} $(rget "$n" setup | sed 's/^REFUSED — //')"; return 1; fi
  if needs_root_blocked "$n"; then echo "    ${RED}✗ blocked:${R} needs root, and this device isn't rooted"; return 1; fi
  if [[ "$(rget "$n" testing)" == yes ]]; then warn "[$n] is a testing/pre-release repo"; confirm_yes "Enable it?" || return 1; fi
  if [[ "$(rget "$n" signed)" == no ]]; then warn "[$n] is unsigned/unverified"; confirm_yes "Enable it?" || return 1; fi
  if [[ -n "$(rget "$n" warn)" && "$(rget "$n" testing)" != yes && "$(rget "$n" signed)" != no ]]; then
    warn "$(rget "$n" warn)"; confirm_yes "Enable it?" || return 1
  fi
  WANT[$n]="on"
}
try_disable() {
  local n="$1"
  if [[ "$(rget "$n" required)" == yes ]]; then echo "    ${RED}✗ blocked:${R} [$n] is required on this system"; return 1; fi
  WANT[$n]="off"
}

pick_category() {
  local i n cnt a
  echo; echo "  ${B}Categories${R}"; echo "    0) all"
  for i in "${!CATS[@]}"; do
    cnt=0; for n in "${RNAMES[@]}"; do [[ "$(rget "$n" cat)" == "${CATS[$i]}" ]] && ((cnt++)); done
    printf '    %d) %-36s %s\n' $((i+1)) "${CATS[$i]}" "${D}$cnt repos${R}"
  done
  ask a "category number:"
  if [[ "$a" =~ ^[0-9]+$ ]] && (( a >= 0 && a <= ${#CATS[@]} )); then
    (( a == 0 )) && FILTER="" || FILTER="${CATS[$((a-1))]}"; return 0
  fi
  echo "    ${RED}✗${R} not a category"; return 1
}

repo_walk() {
  local i=0 n a
  FILTER=""
  while (( i < ${#RNAMES[@]} )); do
    n="${RNAMES[$i]}"
    if [[ -n "$FILTER" && "$(rget "$n" cat)" != "$FILTER" ]] || { declare -F repo_valid >/dev/null && ! repo_valid "$n"; }; then ((i++)); continue; fi
    card "$n"
    ask a "[$n] (e/d/k/c/q):"
    case "$a" in
      e|E) try_enable "$n" && echo "    ${GRN}✓ will be ON${R}" ;;
      d|D) try_disable "$n" && echo "    ${D}✓ will be OFF${R}" ;;
      c|C) pick_category && { i=0; echo "    ${D}filter: ${FILTER:-all}${R}"; }; continue ;;
      q|Q) break ;;
      ""|k|K) ;;
      *) echo "    ${RED}✗${R} e, d, k, c or q"; continue ;;
    esac
    ((i++))
  done
}

# Force refused / root-blocked repos off; report it
enforce_refusals() {
  local n
  for n in "${RNAMES[@]}"; do
    if { is_refused "$n" || needs_root_blocked "$n"; } && [[ "${WANT[$n]}" == on ]]; then
      warn "[$n] is ON but refused here → will be disabled"; WANT[$n]="off"
    fi
  done
}

# Print a plan of repo changes: "enable NAME" / "disable NAME"
repo_plan() {
  local n
  for n in "${RNAMES[@]}"; do
    [[ "${WANT[$n]}" == "${RCUR[$n]}" ]] && continue
    [[ "${WANT[$n]}" == on ]] && echo "enable $n" || echo "disable $n"
  done
}
