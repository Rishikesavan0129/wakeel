# Contributing to Wakeel

Thanks for taking a look. This is a young project (see `CHANGELOG_v3.md` for
where it currently stands) — issues and PRs on anything below are welcome,
but a few things will make a review faster.

## Before you open a PR

1. **Run the test suite.**
   ```bash
   pip install -r requirements-dev.txt
   pytest tests/ -v
   ```
   `tests/` is deliberately built against synthetic schemas/configs, not a
   real OpenLane/ORFS install — it should run in a couple hundred
   milliseconds on any machine, no Docker or PDK required. If you're adding
   logic to `wakeel/orchestrator.py`, `knowledge_base.py`, or
   `physical_profile.py`, add a test in the matching `tests/test_*.py`
   rather than only validating manually against a real design.

2. **If your change touches a real flow run** (config generation, the
   Docker command builder, the self-heal loop), validate it against an
   actual OpenLane and/or ORFS checkout before opening the PR, and say so
   in the PR description — which design(s), which engine, what you saw.
   See `VALIDATION.md` for the current state of real-flow validation; add
   your run to it if it's new ground (new design, new PDK corner, a
   previously-unvalidated resource mode).

3. **Keep the "why" in the code, not just the "what."** A lot of the
   existing code has comments explaining a bug that was fixed and why the
   fix looks the way it does (e.g. `knowledge_base.py`'s note on the
   bool-vs-int adjustment bug) — that's deliberate. If you're fixing
   something non-obvious, leave the next person the same trail.

## Where things live

- `wakeel/config_generator.py` — the schema (what OpenLane/ORFS keys exist,
  their types/defaults) and config file generation.
- `wakeel/knowledge_base.py` — the self-heal matching/adjustment engine.
  `wakeel_knowledge_base.json` is the actual rule data.
- `wakeel/physical_profile.py` — frequency-tier-driven parameter
  escalation, deliberately a pure function of `(engine, freq_ghz)` plus
  whatever the knowledge base has locked for the current attempt (see the
  module docstring on `locked_keys` before changing the ownership model).
- `wakeel/orchestrator.py` — the actual run loop: resolve → seed → write
  config → execute → heal on failure → report.
- `wakeel/openlane_docker.py` — resolves the Docker invocation by reading
  OpenLane's own `make -n mount` output rather than reimplementing it.
  If OpenLane changes its Makefile structure, this is usually where it
  breaks first — a `wakeel doctor`-style health check is on the roadmap
  for exactly this reason.
- `wakeel/design_discovery.py` — design-folder discovery for both engines,
  plus the loose-RTL auto-discovery/staging path (`find_loose_rtl`/
  `stage_design`) that lets a design living outside either engine's proper
  folder structure get picked up and staged on demand.

## Growing the knowledge base

The self-heal loop is the project's actual differentiator (see the
architecture notes) — a new `wakeel_knowledge_base.json` rule is one of
the most valuable single-file contributions you can make, especially for
a failure mode from a real signoff report you've hit yourself. When
adding one:

- `error_keywords` should be specific enough that `MIN_MATCH_SCORE`
  (currently 0.34 — see `knowledge_base.py`) won't reject a legitimate
  match, but not so generic it fires on unrelated failures.
- `adjustments` values must match the schema's declared `type` for that
  key semantically (a boolean key's adjustment is a SET, not a delta —
  `true`/`false`, not `0`/`1` for "off"/"on", even though the engine now
  coerces either correctly; write it the readable way).
- Add a test case asserting the rule matches its intended log text AND
  does NOT match a plausible near-miss, if the keywords are at all
  ambiguous.

## Reporting a bug

Include: the prompt/sweep config you ran, the engine (OpenLane/ORFS), the
full log output around the failure, and whether it reproduces with
`dry_run.py` (config generation only, no real flow execution) or only
against a live run.

## Security issues

Please see `SECURITY.md` rather than opening a public issue.
