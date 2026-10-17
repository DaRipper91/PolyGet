#!/usr/bin/env bash
# Read-only look at ANOTHER machine's PolyGet checkout, over ssh (e.g. via Tailscale).
#
#   scripts/peer-snapshot.sh              # dry run: show what a snapshot of "asahi" would copy
#   scripts/peer-snapshot.sh --go         # snapshot its working tree (uncommitted work included)
#   scripts/peer-snapshot.sh --git        # fetch its COMMITTED branches into this repo as peer-asahi/*
#   scripts/peer-snapshot.sh --go da-nvme # from Asahi: snapshot the CachyOS desktop instead
#
# The snapshot lands in ~/Projects/_devices/<peer>/PolyGet, outside any working repo, and is made
# read-only. It is for READING. Never edit it, never run the app from it, never sync it back.
#
# Env overrides: PEER_USER (daripper)  PEER_REPO (/home/daripper/Projects/PolyGet)
#                DEVICES_DIR (~/Projects/_devices)
set -euo pipefail

MODE=dry
PEER=asahi
for arg in "$@"; do
    case "$arg" in
        --go) MODE=go ;;
        --git) MODE=git ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *) PEER="$arg" ;;
    esac
done

PEER_USER="${PEER_USER:-daripper}"
PEER_REPO="${PEER_REPO:-/home/daripper/Projects/PolyGet}"
DEVICES_DIR="${DEVICES_DIR:-$HOME/Projects/_devices}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$DEVICES_DIR/$PEER/PolyGet"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10)

# Never write a snapshot over (or inside) a working repo.
dest_real="$(realpath -m "$DEST")"
case "$dest_real/" in
    "$REPO_ROOT"/*) echo "refusing: $DEST is inside the working repo $REPO_ROOT" >&2; exit 1 ;;
esac
case "$REPO_ROOT/" in
    "$dest_real"/*) echo "refusing: $DEST contains the working repo $REPO_ROOT" >&2; exit 1 ;;
esac

if [[ "$MODE" == git ]]; then
    # Committed history only. Read-only on the peer; adds a remote to THIS clone's .git/config.
    remote="peer-$PEER"
    url="ssh://$PEER_USER@$PEER$PEER_REPO"
    git -C "$REPO_ROOT" remote get-url "$remote" >/dev/null 2>&1 || git -C "$REPO_ROOT" remote add "$remote" "$url"
    GIT_SSH_COMMAND="ssh ${SSH_OPTS[*]}" git -C "$REPO_ROOT" fetch "$remote"
    echo "Fetched $PEER's committed branches as $remote/*. Uncommitted work is NOT included (use --go)."
    exit 0
fi

# Things that must never cross between machines: git internals, CPU-specific environments,
# caches, per-machine settings, and anything that looks like a secret.
EXCLUDES=(
    --exclude='.git/' --exclude='.venv/' --exclude='venv/' --exclude='__pycache__/'
    --exclude='.pytest_cache/' --exclude='.ruff_cache/' --exclude='.mypy_cache/' --exclude='node_modules/'
    --exclude='*.pyc' --exclude='*.egg-info/' --exclude='.env' --exclude='.env.*'
    --exclude='*.pem' --exclude='*.key' --exclude='id_rsa*' --exclude='id_ed25519*'
    --exclude='.claude/settings.local.json'
)

RSYNC_ARGS=(-a --delete --itemize-changes -e "ssh ${SSH_OPTS[*]}" "${EXCLUDES[@]}")
[[ "$MODE" == dry ]] && RSYNC_ARGS+=(--dry-run)

if [[ "$MODE" == go ]]; then
    mkdir -p "$DEVICES_DIR/$PEER"
    [[ -d "$DEST" ]] && chmod -R u+w "$DEST"
    mkdir -p "$DEST"
fi

echo "[$MODE] $PEER_USER@$PEER:$PEER_REPO/  ->  $DEST/"
rsync "${RSYNC_ARGS[@]}" "$PEER_USER@$PEER:$PEER_REPO/" "$DEST/" | grep -v '^\.d' | head -60 || true

if [[ "$MODE" == dry ]]; then
    echo "Dry run only. Pass --go to copy."
    exit 0
fi

# Provenance goes beside the mirror (not inside it, so --delete cannot remove it).
{
    echo "SNAPSHOT of $PEER:$PEER_REPO"
    echo "taken:   $(date -Is) from $(hostname -s)"
    ssh "${SSH_OPTS[@]}" "$PEER_USER@$PEER" "cd '$PEER_REPO' && echo \"peer HEAD:    \$(git --no-optional-locks rev-parse --short HEAD) on \$(git --no-optional-locks branch --show-current)\" && echo \"uncommitted:  \$(git --no-optional-locks status --porcelain | wc -l) entries\""
    echo "READ ONLY. Do not edit, run, or sync this back. Re-run scripts/peer-snapshot.sh --go to refresh."
} > "$DEVICES_DIR/$PEER/SNAPSHOT_INFO.txt"

cat > "$DEVICES_DIR/README.md" <<'README'
# _devices: read-only copies of OTHER machines' repos

Each folder here is a snapshot pulled from another machine so it can be reviewed locally.
- **Never edit anything in here, never run the app from here, never sync it back.**
- `.git`, `.venv`, caches, and secrets are deliberately not copied.
- See `SNAPSHOT_INFO.txt` beside each mirror for where and when it came from.
Refresh with `scripts/peer-snapshot.sh --go [peer]` in the real repo.
README

chmod -R a-w "$DEST"
echo "Done. Read-only snapshot at $DEST"
cat "$DEVICES_DIR/$PEER/SNAPSHOT_INFO.txt"
