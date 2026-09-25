# Review of `AGENTS.md`

## Summary

The guide is concise, well organized, and accurately describes the repository’s main modules,
Qt headless testing approach, driver architecture, and subprocess safety rule. It is within the
requested length and gives useful commands and naming examples.

## Findings

### Medium — Test setup is not reproducible from the documented environment

`AGENTS.md:20-27` tells contributors to install only `requirements.txt`, then run `pytest`, but
`requirements.txt` does not include `pytest`. A fresh virtual environment following the guide can
therefore fail with `pytest: command not found`. Add `pytest` to a development requirements file
(for example, `requirements-dev.txt`) and document its installation, or explicitly include
`python -m pip install pytest` in the setup instructions. Prefer `python -m pytest` so the test
runner is guaranteed to come from the active interpreter.

### Low — Coverage policy is unspecified

The testing section (`AGENTS.md:40-44`) names pytest and test naming conventions but does not say
whether coverage is measured or whether a threshold exists. The repository currently has no
coverage configuration, so this is not a factual error; adding “No coverage threshold is
currently enforced” would remove ambiguity for contributors.

### Low — GUI runtime requirements could be clearer

The guide documents `QT_QPA_PLATFORM=offscreen` for tests, but `python run.py` assumes a graphical
session. A short note that the GUI needs a display (and that headless contributors should use the
offscreen test command) would prevent confusion in CI or remote shells.

## Positive Notes

- The structure section points contributors to `docs/plans/` before changing behavior.
- The explicit `shell=True` prohibition and distro-routing rule capture important project
  invariants.
- The commit guidance is grounded in recent history and the PR checklist is actionable.

## Recommendation

Address the missing pytest installation path before treating the guide as complete. The remaining
items are clarity improvements rather than blockers.
