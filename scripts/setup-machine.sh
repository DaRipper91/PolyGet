#!/usr/bin/env bash
# One-time, per-clone setup so merging between the machines keeps EACH machine's own agent
# reports instead of conflicting on them. Re-runnable. Local to this clone: nothing is committed.
#
# Why local: git only honours a merge rule that exists in the checkout doing the merge. A
# .gitattributes shipped on the incoming branch does not protect the receiving side.
# If this setup is skipped, a merge simply conflicts on the report files (safe, never silent loss).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ATTR="$(git -C "$REPO_ROOT" rev-parse --git-path info/attributes)"
case "$ATTR" in /*) ;; *) ATTR="$REPO_ROOT/$ATTR" ;; esac

git -C "$REPO_ROOT" config merge.ours.driver true
mkdir -p "$(dirname "$ATTR")"
grep -qxF '*AGENT_REPORT.md merge=ours' "$ATTR" 2>/dev/null || echo '*AGENT_REPORT.md merge=ours' >> "$ATTR"

echo "Configured $REPO_ROOT: AGENT_REPORT.md and (OLD) AGENT_REPORT.md keep this clone's version on merge."
