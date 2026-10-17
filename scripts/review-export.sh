#!/usr/bin/env bash
# Rebuild the read-only review copy of a branch, for the OTHER machine to read over the shared mount.
# The live worktree is a poor thing to review: its .git file points at a path that exists only here, and
# the sshfs mount is read-write and noexec. This exports plain tracked files instead (no .git, no venv).
#
#   scripts/review-export.sh                       # CachyOS/stable-candidate, diffed against master
#   scripts/review-export.sh BRANCH [BASE]
#     --report FILE     copy FILE into the export as REPORT.md
#     --tested "TEXT"   record what was tested; shown in README.txt (omitted when not given)
#     --force           rebuild even if this exact commit was already exported
#     --keep            keep older exports of this branch (default: delete them once the new one is complete)
#
# Result: $REVIEW_DIR/<branch>-<sha>/ (files/, candidate-vs-<base>.patch, diffstat.txt, README.txt[, REPORT.md]) made
# read-only, plus a relative symlink <branch>-latest that always points at the newest export.
# Env: REVIEW_DIR (default ~/Projects/_review)   PEER_MOUNT (how the other machine sees this one's home,
#      default '$HOME/remotes/da-nvme', used only in the README text)
set -euo pipefail

BRANCH="CachyOS/stable-candidate"; BASE="master"; REPORT=""; TESTED=""; FORCE=0; KEEP=0; pos=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --report) REPORT="${2:?--report needs a file}"; shift ;;
        --tested) TESTED="${2:?--tested needs text}"; shift ;;
        --force) FORCE=1 ;;
        --keep) KEEP=1 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) pos=$((pos+1)); [[ $pos -eq 1 ]] && BRANCH="$1" || BASE="$1" ;;
    esac
    shift
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${REVIEW_DIR:-$HOME/Projects/_review}"
PEER_MOUNT="${PEER_MOUNT:-\$HOME/remotes/da-nvme}"
G=(git -C "$REPO")

"${G[@]}" rev-parse -q --verify "$BRANCH^{commit}" >/dev/null || { echo "no such branch/commit: $BRANCH" >&2; exit 1; }
"${G[@]}" rev-parse -q --verify "$BASE^{commit}" >/dev/null || { echo "no such base: $BASE" >&2; exit 1; }
[[ -z "$REPORT" || -f "$REPORT" ]] || { echo "report file not found: $REPORT" >&2; exit 1; }

SHA="$("${G[@]}" rev-parse --short "$BRANCH")"
TAG="${BRANCH//\//-}"
NAME="$TAG-$SHA"
OUT="$ROOT/$NAME"
BASE_TAG="${BASE//\//-}"

unlock() { [[ -e "$1" ]] && chmod -R u+w "$1" || true; }
point_latest() { ln -sfn "$NAME" "$ROOT/$TAG-latest"; }

mkdir -p "$ROOT"
if [[ -d "$OUT" && $FORCE -eq 0 ]]; then
    point_latest
    echo "already exported: $OUT (commit $SHA unchanged; use --force to rebuild)"
    exit 0
fi

# Build beside the target and move into place, so a reader never sees a half-written export.
TMP="$ROOT/.$NAME.tmp"
unlock "$TMP"; rm -rf "$TMP"; mkdir -p "$TMP/files"
"${G[@]}" archive --format=tar "$BRANCH" | tar -x -C "$TMP/files"
"${G[@]}" diff "$BASE" "$BRANCH" > "$TMP/candidate-vs-$BASE_TAG.patch"
"${G[@]}" diff --stat "$BASE" "$BRANCH" > "$TMP/diffstat.txt"
[[ -n "$REPORT" ]] && cp "$REPORT" "$TMP/REPORT.md"

for leak in .git .venv __pycache__; do
    [[ -e "$TMP/files/$leak" ]] && { echo "export leaked $leak; aborting" >&2; rm -rf "$TMP"; exit 1; }
done
for gov in BRANCHING.md AGENT_REPORT.md scripts/repo-check.sh docs/reports; do
    [[ -e "$TMP/files/$gov" ]] && echo "WARN  $gov is in this export; a stable candidate should not carry governance files" >&2
done

{
    echo "REVIEW COPY OF $BRANCH (read-only; made $(date -Is) on $(hostname -s))"
    echo "  commit   : $("${G[@]}" rev-parse "$BRANCH")"
    echo "  diffed vs: $BASE ($("${G[@]}" rev-parse --short "$BASE"))"
    [[ -n "$TESTED" ]] && echo "  tested   : $TESTED"
    echo
    echo "  files/                          the branch's tracked files (plain files, no .git)"
    echo "  candidate-vs-$BASE_TAG.patch    the change on top of $BASE ($("${G[@]}" diff --shortstat "$BASE" "$BRANCH" | sed 's/^ //'))"
    echo "  diffstat.txt                    per-file summary"
    [[ -n "$REPORT" ]] && echo "  REPORT.md                       what is going on and what to check; read this first"
    echo
    echo "HOW TO REVIEW (this folder is on a read-write, noexec sshfs mount: read it, do not run or write anything here)"
    echo "  Read the diff : less $PEER_MOUNT/Projects/_review/$NAME/candidate-vs-$BASE_TAG.patch"
    echo "  Real commit   : git fetch /home/daripper/remotes/da-nvme/Projects/PolyGet $BRANCH:refs/remotes/cachy/${BRANCH##*/}"
    echo "                  (reads this machine's repo, writes only to the fetching machine's .git; use git --no-optional-locks)"
    echo "  Run the tests : copy files/ to a LOCAL folder and use that machine's own venv, never run on the mount:"
    echo "                  rsync -a $PEER_MOUNT/Projects/_review/$NAME/files/ ~/Projects/_review-local/$TAG/"
    echo "  Always newest : $PEER_MOUNT/Projects/_review/$TAG-latest/"
} > "$TMP/README.txt"

unlock "$OUT"; rm -rf "$OUT"
mv "$TMP" "$OUT"
chmod -R a-w "$OUT"
point_latest

if [[ $KEEP -eq 0 ]]; then
    for old in "$ROOT/$TAG"-*; do
        n="$(basename "$old")"
        [[ -d "$old" && ! -L "$old" && "$n" != "$NAME" ]] || continue
        [[ "${n#"$TAG"-}" =~ ^[0-9a-f]{7,40}$ ]] || continue   # only this branch's own exports, never a lookalike
        unlock "$old"; rm -rf "$old"; echo "removed older export: $n"
    done
fi
echo "exported $BRANCH @ $SHA -> $OUT ($(find "$OUT/files" -type f | wc -l) files)"
echo "latest -> $ROOT/$TAG-latest"
