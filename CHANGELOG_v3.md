# Wakeel v3 — Changelog

Everything below was verified: `python3 -m pytest tests/ -v` (38/38 passing),
live regression checks against real `wakeel_knowledge_base.json` runs, real
OpenLane/sky130 runs (see `VALIDATION.md`), and a `dry_run.py` smoke test.

## Fixed

1. **`physical_profile` vs. knowledge-base key collision.**
   `physical_profile.apply()` now accepts `locked_keys`, and the orchestrator
   tracks which of its OWNED_KEYS a KB self-heal rule touched during the
   current sweep point's retries. On the next attempt, `physical_profile`
   defers to that fix instead of silently forcing its own tier default back
   over it. Reset per sweep point, so it never leaks across frequencies or
   designs — the original order-independence guarantee is untouched.

2. **`0`/`1`-vs-boolean bug in the KB engine.** Three real rules
   (`LVS-002`, `LVS-003`, `SIG-005`) encoded a boolean SET as JSON `0`/`1`
   instead of `true`/`false`, which fell into the additive-numeric branch
   and silently no-op'd. Fixed the data, and hardened
   `KnowledgeBase.apply()` to branch on the **schema's declared type**
   for the key rather than the JSON literal's Python type — so a future
   rule authored the same way still works correctly.

3. **ORFS physical-profile parity.** No longer warning-only. Uses two
   real, schema-verified ORFS knobs (`SYNTH_MAX_FANOUT`, `SYNTH_FLAT_TOP`)
   to escalate synthesis aggressiveness by frequency tier, mirroring what
   the OpenLane branch already did with `SYNTH_STRATEGY`/resizer flags.

4. **Oscillation guard.** `heal()` now takes `excluded_rule_ids` and won't
   reapply a KB rule that already fired for the current sweep point without
   resolving the failure. Logged as `[OSCILLATION GUARD]` when it triggers.

5. **Confidence floor on KB matching.** `KnowledgeBase.match()` now drops
   any candidate scoring below `MIN_MATCH_SCORE` (0.34) instead of
   returning the top-ranked match regardless of how weak it is. A rejected
   weak match falls through to the local-LLM/bounded-fallback path.

6. **Test suite.** `tests/` — `test_knowledge_base.py`,
   `test_physical_profile.py`, `test_sweep_config.py`, `test_sanitize.py`,
   `test_power_analysis.py`, `test_engine_override.py`. 38 tests, no live
   OpenLane/ORFS install required.

7. **Operational robustness.**
   - `_run_and_stream()` now has a configurable watchdog
     (`WAKEEL_RUN_TIMEOUT_SECONDS`, default 4h) that kills the whole
     process group on a stall, instead of hanging forever.
   - A per-`(engine, design)` `asyncio.Lock` serializes concurrent runs
     against the same design directory.
   - `requirements.txt` is now pinned to compatible-release ranges instead
     of bare package names.

8. **Silent engine fallback.** `DesignSearch.find()` only ever treated an
   engine preference as a soft tiebreak — if the requested engine had no
   matching design folder, it silently ran on whichever engine did, with
   the only signal being "Manufacturing Mode (Google/SkyWater 130nm)"
   scrolling by in the log. Confirmed live: a prompt correctly saying
   "7nm" still ran on OpenLane/sky130 because no ORFS-side folder existed
   for that design. Now surfaced explicitly as an `[ENGINE FALLBACK]`
   warning naming both engines and what to do about it, and — when
   `WAKEEL_RTL_SEARCH_ROOTS` is configured — resolved automatically via
   the new auto-stage path (see below) instead of just reported.

## New

- **Structured PPA output.** Every successful sweep point emits a
  `ppa_summary` JSON event (not log-text the UI has to regex-parse). At
  the end of the run, the orchestrator re-reads the CSV it just wrote to
  `ppa_reports/` and sends it back as an authoritative `sweep_summary`
  event — the UI's table is guaranteed to match what's actually on disk.
- **User-configurable sweep.** `wakeel.orchestrator.build_sweep_clocks_ps()`
  accepts either `{"frequencies_ghz": [...]}` or
  `{"start_ghz", "end_ghz", "step_ghz"}`, validated and capped at
  `MAX_SWEEP_POINTS`/`ABSOLUTE_MAX_SWEEP_POINTS`. Wired through
  `wakeel_api.py`, `cli_run.py` (`--sweep`/`--sweep-range`), and `index.html`.
- **Configurable self-heal retry budget and sweep-point cap.**
  `max_retries` (default 3, `DEFAULT_MAX_RETRIES`/`ABSOLUTE_MAX_RETRIES=10`)
  and `max_sweep_points` (default 50, ceiling 200) are now per-request
  knobs, clamped server-side regardless of what's requested, exposed as an
  "Advanced parameters" disclosure in the UI and `--max-retries`/
  `--max-sweep-points` flags in `cli_run.py`.
- **Explicit engine/tech-node selection.** A UI toggle (Auto / ORFS·7nm /
  OpenLane·130nm) and an `"engine"` payload key bypass prompt-text
  guessing entirely — the direct fix for the silent-fallback issue above.
- **Loose-RTL auto-discovery and staging.** `WAKEEL_RTL_SEARCH_ROOTS`
  (colon-separated list of project folders — deliberately NOT a
  whole-filesystem crawl) lets Wakeel find a bare `.v`/`.sv` file matching
  a design query and copy (never reference in place) it into a fresh
  folder under the requested engine's design root, so a design that only
  ever existed as loose source under one engine gets real folder parity
  under the other automatically instead of requiring a manual copy.
- **Real Stop button.** `wakeel_api.py` now concurrently listens for a
  `{"type": "stop"}` message while a run is in flight and cancels the
  orchestrator task; `_run_and_stream` catches `asyncio.CancelledError`
  and kills the actual subprocess's process group via `SIGKILL` — the
  same mechanism the timeout watchdog already used. Confirmed live: a
  mid-CTS OpenLane run was actually killed, not just disconnected from.
  Side benefit: Ctrl+C on `cli_run.py` now also properly kills the
  backend subprocess, since disconnect goes through the same path.
- **Power analysis TCL rewritten to industrial/academic standard.**
  `build_power_analysis_tcl()` (old name `build_power_estimate_tcl` kept
  as a backward-compatible alias): supports both SAIF and VCD activity
  annotation (SAIF preferred), calls `report_units` first so every number
  is self-documenting about units, and — critically — prints an explicit
  `WAKEEL_POWER_WARNING` banner in the run log when neither is supplied,
  instead of silently trusting OpenSTA's default toggle-rate assumption.
  Documents clearly in its own docstring what it does and doesn't cover
  (no real parasitics, single-corner, pre-layout estimate only — not a
  signoff number).
- **UI rebuild + day/night theme.** Replaced the previous cyberpunk/
  matrix-rain interface with a plain instrument-panel dashboard: IBM Plex
  Mono/Sans, a graphite palette with semantic teal/green/amber/red, a
  sweep-point progress rail driven by real backend events, a PPA results
  table + chart. Night theme is the HUD look; day theme is a "blueprint"
  mode — pale engineering-schematic paper with a drafting grid, not just
  inverted colors, with glow traded for crisp borders. A small monogram
  badge + "by Youness Yunair" byline in the header and footer.

## Still open (flagged in the original review, not yet done)

- Frequency sweep points still run sequentially — could parallelize
  independent points if hardware allows.
- Self-heal events are still human-readable strings for the log stream;
  a fully structured event log (rule id + before/after diff) would enable
  golden-file regression tests without a live OpenLane/ORFS install.
- ORFS still needs its first real (not sandboxed) live run — see
  `VALIDATION.md`'s open items.
