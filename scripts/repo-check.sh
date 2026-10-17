#!/usr/bin/env bash
# Is this clone safe to build on, branch from, or promote to master from?
# Read-only apart from `git fetch` (which only updates remote-tracking refs).
#
#   scripts/repo-check.sh                # fetch origin, check this clone
#   scripts/repo-check.sh --peer asahi   # also compare the other machine (read-only, over ssh)
#   scripts/repo-check.sh --no-fetch     # use the refs already here (offline)
#   scripts/repo-check.sh --promoting    # you are about to push master: local master being AHEAD is expected
#
# Exit status: 0 clean · 1 warnings (a repo review is suggested) · 2 alert (do NOT merge into
# master or push master until the repo has been reviewed).
#
# Env for --peer: PEER_USER (daripper)  PEER_REPO (/home/daripper/Projects/PolyGet)
set -uo pipefail

FETCH=1
PROMOTING=0
PEER=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-fetch) FETCH=0 ;;
        --promoting) PROMOTING=1 ;;
        --peer) PEER="${2:?--peer needs a tailnet name}"; shift ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PEER_USER="${PEER_USER:-daripper}"
PEER_REPO="${PEER_REPO:-/home/daripper/Projects/PolyGet}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
G="git --no-optional-locks"

LEVEL=0
ok()    { echo "OK    $*"; }
warn()  { echo "WARN  $*"; [[ $LEVEL -lt 1 ]] && LEVEL=1; return 0; }
alert() { echo "ALERT $*"; LEVEL=2; }
# "<ahead> <behind>" of $1 relative to $2
rel() { $G rev-list --left-right --count "$1...$2" 2>/dev/null | tr '\t' ' '; }

if [[ -x .venv/bin/python ]]; then
    echo "machine: $(.venv/bin/python run.py system 2>/dev/null | tail -1 | tr -s ' ')"
fi

if [[ $FETCH -eq 1 ]]; then
    timeout 30 git fetch -q origin || warn "could not fetch origin; results below use possibly stale refs"
fi

BRANCH="$($G branch --show-current)"
$G rev-parse -q --verify refs/remotes/origin/master >/dev/null || { alert "origin/master not found"; exit 2; }
ORIGIN_MASTER="$($G rev-parse --short origin/master)"

# 1. Local master vs origin/master
MASTER_DRIFT=0
if $G rev-parse -q --verify refs/heads/master >/dev/null; then
    read -r A B <<<"$(rel master origin/master)"
    if   [[ $A -eq 0 && $B -eq 0 ]]; then ok "local master matches origin/master ($ORIGIN_MASTER)"
    elif [[ $A -eq 0 && $PROMOTING -eq 1 ]]; then MASTER_DRIFT=2; alert "local master is $B commit(s) BEHIND origin/master: a push would be rejected. Fetch and merge first"
    elif [[ $A -eq 0 ]]; then MASTER_DRIFT=1; warn "local master is $B commit(s) BEHIND origin/master: the stable line moved elsewhere. Catch up with: git fetch origin master:master"
    elif [[ $B -eq 0 && $PROMOTING -eq 1 ]]; then ok "local master is $A commit(s) ahead of origin/master and fast-forwards cleanly: ready to push"
    elif [[ $B -eq 0 ]]; then MASTER_DRIFT=2; alert "local master has $A commit(s) origin/master does not have. Do not build on it; review how they got there (if you mean to push them, re-run with --promoting)"
    else MASTER_DRIFT=2; alert "local master has DIVERGED from origin/master ($A local-only, $B remote-only). Review before doing anything with master"
    fi
else
    ok "no local master branch (fine for a beta-only clone)"
fi

# 2. Current branch vs its own remote branch
BRANCH_SYNCED=0
if [[ -n "$BRANCH" && "$BRANCH" != master ]]; then
    if $G rev-parse -q --verify "refs/remotes/origin/$BRANCH" >/dev/null; then
        read -r A B <<<"$(rel HEAD "origin/$BRANCH")"
        if   [[ $A -eq 0 && $B -eq 0 ]]; then BRANCH_SYNCED=1; ok "$BRANCH matches origin/$BRANCH"
        elif [[ $B -eq 0 ]]; then warn "$BRANCH has $A unpushed commit(s): they exist only on this machine"
        elif [[ $A -eq 0 ]]; then warn "$BRANCH is $B commit(s) behind origin/$BRANCH (pushed from another machine?)"
        else alert "$BRANCH has DIVERGED from origin/$BRANCH ($A local-only, $B remote-only)"
        fi
    else
        warn "$BRANCH has not been pushed: it exists only on this machine"
    fi

    # 3. Has the stable line moved on since this beta last merged it?
    BEHIND_MASTER="$($G rev-list --count "HEAD..origin/master")"
    if [[ $BEHIND_MASTER -gt 0 ]]; then
        warn "origin/master has $BEHIND_MASTER commit(s) $BRANCH has not merged: merge origin/master into $BRANCH before promoting"
    else
        ok "$BRANCH already contains everything on origin/master"
    fi
fi

# 4. The quiet trap: the beta looks fine, but master does not match its remote.
# MASTER_DRIFT: 1 = merely behind (a fast-forward fixes it), 2 = ahead or diverged (dangerous).
if [[ $BRANCH_SYNCED -eq 1 && $MASTER_DRIFT -ge 1 ]]; then
    msg="$BRANCH matches its remote but local master does NOT match origin/master. A beta in sync can hide a drifted master: review the repo before merging or promoting."
    if [[ $MASTER_DRIFT -eq 2 ]]; then alert "$msg"; else warn "$msg"; fi
fi

# 5. Uncommitted work
DIRTY="$($G status --porcelain | wc -l)"
if [[ $DIRTY -gt 0 ]]; then warn "$DIRTY uncommitted entr$([[ $DIRTY -eq 1 ]] && echo y || echo ies) here: that work exists only in this working tree"
else ok "working tree is clean"; fi

# 6. The other machine (read-only)
if [[ -n "$PEER" ]]; then
    # The remote login shell may not be bash (Asahi uses fish), so always feed a script to `bash -s`.
    OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$PEER_USER@$PEER" bash -s 2>/dev/null <<REMOTE
cd '$PEER_REPO' || exit 1
G="git --no-optional-locks"
echo "\$(\$G branch --show-current) \$(\$G rev-parse --short master 2>/dev/null || echo none) \$(\$G rev-parse --short origin/master 2>/dev/null || echo none) \$(\$G status --porcelain | wc -l)"
REMOTE
)"
    if [[ -z "$OUT" ]]; then
        warn "could not read $PEER over ssh; its state is unknown"
    else
        read -r P_BRANCH P_MASTER P_OMASTER P_DIRTY <<<"$OUT"
        echo "peer $PEER: on '$P_BRANCH', master=$P_MASTER, its origin/master=$P_OMASTER, uncommitted=$P_DIRTY"
        [[ "$P_OMASTER" != "$ORIGIN_MASTER" ]] && warn "$PEER last saw origin/master at $P_OMASTER but it is $ORIGIN_MASTER now: it needs a fetch"
        [[ "$P_MASTER" != none && "$P_MASTER" != "$ORIGIN_MASTER" ]] && warn "$PEER's local master ($P_MASTER) differs from origin/master ($ORIGIN_MASTER): review it"
        [[ "$P_DIRTY" -gt 0 ]] && warn "$PEER has $P_DIRTY uncommitted entries that no branch or remote contains"
    fi
fi

case $LEVEL in
    0) echo "RESULT: clean. Nothing suggests a review." ;;
    1) echo "RESULT: warnings. A repo review is suggested before promoting to master." ;;
    2) echo "RESULT: ALERT. Do not merge into master or push master until the repo has been reviewed." ;;
esac
exit $LEVEL
