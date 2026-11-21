# dryrun-gate.sh — "dry run must pass before anything changes", shared by all scripts.
#
# Rules
#   1. Every script starts in DRY RUN.
#   2. A dry run that finishes successfully records a fingerprint of everything
#      the script depends on (its own code, its arguments, the config files it
#      reads or changes — so any line commented/uncommented counts).
#   3. The NEXT run applies automatically, but only if the fingerprint still
#      matches and the dry run is younger than GATE_MAX_AGE (default 24h).
#   4. If anything changed, or the dry run failed, it's back to dry run.
#   5. After an apply, the stamp is cleared: the following run is a dry run again.
#
# Flags understood by gate_parse (scripts pass "$@" through it):
#   --dry-run   force a dry run (refreshes the stamp if it passes)
#   --apply     accepted for habit; only applies if rule 3 holds
#   --reset     forget any passed dry run for this script
#
# Usage inside a script:
#   source lib/dryrun-gate.sh
#   gate_parse "$@"; set -- "${GATE_ARGS[@]}"     # strips gate flags
#   GATE_NAME="setup-repos"
#   GATE_INPUTS=(/etc/pacman.conf "$HERE/pacman.conf" "$0")
#   GATE_EXTRA="$(hostname) $*"
#   gate_begin                                    # sets APPLY=0/1
#
# Internal: a parent script that already passed its own dry run (which ran the
# child's dry run too) calls the child with DRYRUN_GATE_CHAINED=1 to apply.
# Children called from a parent's dry run get --dry-run + DRYRUN_GATE_NOSTAMP=1.

GATE_MAX_AGE="${GATE_MAX_AGE:-86400}"
# Scripts add their own cleanup here instead of setting an EXIT trap:
#   GATE_CLEANUP+='rm -f "$TMP";'
GATE_CLEANUP="${GATE_CLEANUP:-}"
GATE_REQ="auto"
GATE_ARGS=()
APPLY=0

gate_parse() {
  GATE_ARGS=()
  local a
  for a in "$@"; do
    case "$a" in
      --dry-run) GATE_REQ="dry" ;;
      --apply)   [[ "$GATE_REQ" == "dry" ]] || GATE_REQ="apply" ;;
      --reset)   GATE_REQ="reset" ;;
      *) GATE_ARGS+=("$a") ;;
    esac
  done
}

_gate_dir() {
  if [[ -n "${GATE_DIR:-}" ]]; then echo "$GATE_DIR"
  else echo "${XDG_STATE_HOME:-${HOME:-/root}/.local/state}/dryrun-gate"; fi
}

_gate_hash() { if command -v sha256sum >/dev/null; then sha256sum; else cksum; fi; }

gate_fingerprint() {
  local f
  {
    for f in "${GATE_INPUTS[@]}"; do
      if [[ -d "$f" ]]; then
        echo "dir $f"
        find "$f" -type f \( -name PKGBUILD -o -name '*.conf' -o -name '*.sh' -o -name '*.env' -o -name '*.properties' -o -name '*.yml' -o -name '*.template' \) -print0 2>/dev/null \
          | sort -z | xargs -0 cat 2>/dev/null
      elif [[ -e "$f" ]]; then
        echo "file $f"; cat "$f" 2>/dev/null || echo "unreadable $f"
      else
        echo "missing $f"
      fi
    done
    echo "extra ${GATE_EXTRA:-}"
  } | _gate_hash | cut -d' ' -f1
}

_gate_now() { date +%s; }

gate_begin() {
  : "${GATE_NAME:?gate_begin needs GATE_NAME}"
  local dir stamp fp sfp sts age
  dir="$(_gate_dir)"; stamp="$dir/$GATE_NAME.ok"
  mkdir -p "$dir" 2>/dev/null || true

  if [[ "$GATE_REQ" == "reset" ]]; then
    rm -f "$stamp"; echo "dry-run gate: cleared for $GATE_NAME"; exit 0
  fi

  if [[ "${DRYRUN_GATE_CHAINED:-0}" == "1" ]]; then
    APPLY=1
    echo "dry-run gate: APPLY (chained from a parent whose dry run passed)"
    _GATE_MODE="chained"; trap '_gate_end $?' EXIT; return
  fi

  fp="$(gate_fingerprint)"
  _GATE_FP="$fp"; _GATE_STAMP="$stamp"

  if [[ "$GATE_REQ" != "dry" && -f "$stamp" ]]; then
    read -r sfp sts < "$stamp" || true
    age=$(( $(_gate_now) - ${sts:-0} ))
    if [[ "$sfp" == "$fp" ]] && (( age >= 0 && age < GATE_MAX_AGE )); then
      APPLY=1
      echo "dry-run gate: ✓ dry run passed $(( age / 60 )) min ago for this exact state → APPLYING"
    elif [[ "$sfp" != "$fp" ]]; then
      APPLY=0
      echo "dry-run gate: something changed since the last dry run → DRY RUN again"
    else
      APPLY=0
      echo "dry-run gate: last dry run is older than $(( GATE_MAX_AGE / 3600 ))h → DRY RUN again"
    fi
  else
    APPLY=0
    if [[ "$GATE_REQ" == "dry" ]]; then
      echo "dry-run gate: DRY RUN (forced)"
    else
      echo "dry-run gate: no passing dry run for this state yet → DRY RUN"
      [[ "$GATE_REQ" == "apply" ]] && echo "dry-run gate: --apply ignored until a dry run passes"
    fi
  fi
  _GATE_MODE=$([[ $APPLY == 1 ]] && echo apply || echo dry)
  trap '_gate_end $?' EXIT
}

_gate_end() {
  local rc="$1"
  [[ -n "$GATE_CLEANUP" ]] && eval "$GATE_CLEANUP" || true
  case "${_GATE_MODE:-}" in
    dry)
      if [[ "${DRYRUN_GATE_NOSTAMP:-0}" == "1" ]]; then :
      elif (( rc == 0 )); then
        printf '%s %s\n' "$_GATE_FP" "$(_gate_now)" > "$_GATE_STAMP" 2>/dev/null || true
        echo
        echo "dry-run gate: ✓ dry run PASSED. Run the same command again to apply."
        echo "              (any change to the inputs first → it dry-runs again)"
      else
        rm -f "$_GATE_STAMP" 2>/dev/null || true
        echo
        echo "dry-run gate: ✗ dry run FAILED (exit $rc). Fix it and run again — nothing was applied."
      fi ;;
    apply)
      rm -f "$_GATE_STAMP" 2>/dev/null || true
      echo
      if (( rc == 0 )); then
        echo "dry-run gate: applied. Next run of $GATE_NAME will dry-run first."
      else
        echo "dry-run gate: apply exited with $rc. Next run will dry-run first."
      fi ;;
  esac
}

# Loader used by every script (copy as-is):
#   for _g in "$HERE/lib/dryrun-gate.sh" "$HERE/../lib/dryrun-gate.sh" /usr/local/lib/dryrun-gate.sh; do
#     [[ -f "$_g" ]] && { source "$_g"; break; }; done
#   declare -F gate_begin >/dev/null || { echo "missing lib/dryrun-gate.sh" >&2; exit 1; }
