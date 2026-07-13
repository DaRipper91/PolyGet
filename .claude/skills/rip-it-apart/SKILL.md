---
description: Use when the user wants a full honest audit/teardown of this repository — real bugs, security/exposure risks, dead code, stale references — ending in a cited, task-by-task fix-plan file rather than a chat summary. Trigger on "run the audit", "audit this repo", "rip this apart", "tear this codebase apart", "full teardown of this project".
allowed-tools: Task, Read, Write, Bash, Grep, Glob
---

# rip-it-apart

A six-stage audit pipeline run as real subagent delegations via the Task tool, not one long pass
in your own voice. Each stage is a separate subagent defined in `.claude/agents/rip-it-apart-*.md`,
invoked explicitly in strict order, with a shared handoff file (`.audit/SCRATCH.md`) carrying state
between them so nothing depends on this session's own context window holding everything.

Do not collapse this into a single pass yourself. The whole point is that each stage is a distinct,
narrow subagent — that's what keeps bug-hunting from crowding out "what's actually good," and what
lets the critic stage genuinely check earlier work instead of agreeing with itself.

## Setup

1. Confirm you're at the repo root (check for `.git`, `README.md`, or similar). If not, stop and
   ask which repo to audit rather than guessing.
2. Create `.audit/` if it doesn't exist, and write `.audit/SCRATCH.md`:

```markdown
# Audit Scratch — <repo name> — started <date>

## Known Fragile Areas (repo-specific — check every stage)
- The "no shell=True, ever" rule is load-bearing: every subprocess call must use
  asyncio.create_subprocess_exec with argument lists, never a shell string. Flag any
  shell=True or string-built command as Critical, not stylistic.
- Distro-awareness must route through app/core/distro.py. Any command whose behavior
  differs by distro family (Arch vs Fedora) that's hardcoded outside distro.py is a bug,
  even if it happens to work on the machine it was written on.
- Previously confirmed real bugs in this repo: Flatpak driver's broken -j flag, Pipx
  driver's fake PyPI lookup (returns success without checking PyPI), Pacman driver's
  inverted exit-code convention. Confirm these are still fixed, not regressed, rather than
  re-discovering them fresh each audit.
- app/core/catalog.py exists specifically to show managers the user could install, not
  just ones already present. A change that makes the catalog only list installed managers
  is a regression against this repo's actual design intent, not a neutral change.
- This repo's cloud environment (Ubuntu-based) cannot run pacman or dnf natively — Docker
  is used for Arch-driver testing there. If core-verification can't exercise the Pacman or
  DNF driver directly, note that as an environment limitation, not as "untested code" with
  the same severity as a real gap.

## 01 — Recon
(pending)

## 02 — Core Verification
(pending)

## 03 — Bug Hunt
(pending)

## 04 — Strengths
(pending)

## 05 — Critic Pass
(pending)
```

## Stage execution

Invoke each subagent by name using the Task tool — do not rely on automatic delegation for this
chain, since the stages must run in strict order and automatic delegation doesn't guarantee that.

After each invocation reports back, read `.audit/SCRATCH.md` yourself and confirm that stage's
section is no longer `(pending)` and contains cited, concrete content (real file paths, real line
references, real command output — not generic statements) before moving to the next stage. If a
stage's output is empty, vague, or clearly weak, invoke that same subagent again with a note about
what's missing before proceeding. Don't silently continue with a gap.

### Stage 1 — Recon
- Subagent: `rip-it-apart-recon-mapper`
- Task: "Map this repository per your instructions. Append your findings to `.audit/SCRATCH.md`
  under `## 01 — Recon`, replacing `(pending)`."

### Stage 2 — Core Verification
- Subagent: `rip-it-apart-core-verifier`
- Task: "Read `.audit/SCRATCH.md`'s `## 01 — Recon` section for the repo map and complexity
  hotspots. Verify the core logic per your instructions — run real tests, check git history, run
  any available scanners/linters. Append findings under `## 02 — Core Verification`, replacing
  `(pending)`."

### Stage 3 — Bug Hunt
- Subagent: `rip-it-apart-bug-hunter`
- Task: "Read `.audit/SCRATCH.md`'s `## 01` and `## 02` sections. Run the fixed bug-class
  checklist from your instructions against this repository. Append findings under
  `## 03 — Bug Hunt`, replacing `(pending)`."

### Stage 4 — Strengths Scout
- Subagent: `rip-it-apart-strengths-scout`
- Task: "Read all of `.audit/SCRATCH.md` so far. Identify what this codebase genuinely does well
  — patterns worth preserving or reusing elsewhere, not just an absence of bugs. Append findings
  under `## 04 — Strengths`, replacing `(pending)`."

### Stage 5 — Critic Pass
- Subagent: `rip-it-apart-critic`
- Task: "Read all of `.audit/SCRATCH.md`. Independently verify stages 1–4: spot-check at least
  three specific claims against the actual code, flag anything unsupported, overstated, or
  contradicted by what you find. Append your findings under `## 05 — Critic Pass`, replacing
  `(pending)`. Do not soften findings to agree with earlier stages — the value of this stage is
  disagreement where warranted."

### Stage 6 — Fix-Plan Writer
- Subagent: `rip-it-apart-fix-plan-writer`
- Task: "Read the entire `.audit/SCRATCH.md`. Reconcile stage 5's corrections into stages 1–4's
  findings — where the critic disputed something, use the critic's version. Write a complete,
  task-by-task, severity-ranked fix-plan file to the repo root (or update if the file already
  exists), named `RIP_IT_APART_FIXPLAN_<date>.md`. Every finding must cite a real file path and,
  where applicable, a line number or range. Do not include anything from the scratch file that
  wasn't independently confirmed by at least stage 2 or stage 3's verification work."

## After completion

Report back to the user with: a one-paragraph summary of the most severe finding, the path to the
generated fix-plan file, and a note on how many findings were flagged versus disputed by the critic
stage. Do not paste the entire fix-plan file into the chat — the file itself is the deliverable.
