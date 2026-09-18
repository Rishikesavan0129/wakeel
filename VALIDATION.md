# Validation status

This file exists because "trust me it works" isn't good enough for an EDA
tool — see `CHANGELOG_v3.md`'s note on this. It's split into what's
actually been exercised and how, vs. what still needs a real toolchain
run and hasn't happened yet. Update it whenever you validate something
new; that's more valuable to a reviewer than almost any single feature.

## Real toolchain runs (confirmed live, not sandboxed)

- **2026-09-12, `wakeel_alu`, OpenLane/sky130, 1.0 GHz** — physical_profile
  correctly classified 1 GHz as `extreme` for sky130, set
  `SYNTH_STRATEGY=DELAY 1`, enabled resizer optimizations, and surfaced
  the accurate "past comfortable range" warning. Progressed cleanly
  through synthesis → floorplan → IO placement → PDN → global placement →
  detailed placement → into CTS with no unexpected failures. Confirms the
  physical-profile tier-classification fix works against a real OpenLane
  invocation, not just the synthetic schema in `tests/test_physical_profile.py`.
- **2026-09-12, same run** — mid-CTS, a live Stop request was sent from
  the UI. Log stream ended cleanly at `[STOP REQUESTED] Killing the live
  subprocess...` with no further output, confirming the process group was
  actually killed rather than the UI merely going quiet. First real
  confirmation of the v3 cancellation path (`_run_and_stream`'s
  `asyncio.CancelledError` handling + `wakeel_api.py`'s concurrent
  stop-listener).
- **2026-09-12, engine-fallback warning** — a prompt/toggle explicitly
  requesting ORFS/7nm for `wakeel_alu` (no ORFS-side folder existing yet)
  correctly produced the `[ENGINE FALLBACK]` warning explaining the
  mismatch and why it fell back to OpenLane/sky130, instead of silently
  running on the wrong engine with no explanation (the original bug this
  fixed).

## What CI validates on every push

`tests/` (38 tests) — the KB engine's boolean/confidence-floor logic,
`physical_profile`'s ownership arbitration and tier classification for
both engines, the sweep-config builder, `sanitize_identifier`'s injection
resistance, the power-analysis TCL generator, and engine-override/
resource-mode recomputation. All against synthetic schemas/configs — this
proves the orchestration logic is correct in isolation, not that a real
flow run succeeds.

## Sandbox-level validation (no Docker/PDK available)

Run 2026-08-27, against `wakeel/dry_run.py` (config generation only —
never executes a real flow) with a design tree structurally identical to
a real OpenLane/ORFS install (`designs/<name>/src/*.v`,
`flow/designs/asap7/<name>/config.mk`), using `wakeel_alu.v` from this
repo:

| Check | Engine | Result |
|---|---|---|
| Design discovery (fuzzy match, top-module extraction from real Verilog) | both | Correct |
| Existing-config seeding from a real `config.mk` | ORFS | Correct |
| Physical-profile tier classification: comfortable (0.5 GHz) | ORFS | `SYNTH_MAX_FANOUT=20`, `SYNTH_FLAT_TOP=0` — tier default, as expected |
| Physical-profile tier classification: aggressive (2.5 GHz) | ORFS | `SYNTH_MAX_FANOUT=12` — escalated correctly |
| Physical-profile tier classification: extreme (0.8 GHz, OpenLane's tighter bands) | OpenLane | `SYNTH_STRATEGY="DELAY 1"` — escalated correctly |
| Full config file rendering (schema-driven, both formats) | both | Produced valid `.tcl`/`.mk` output |
| `LVS-003` KB rule against the real `wakeel_knowledge_base.json` | OpenLane | Confirmed it now actually sets both resizer flags to `False` (the bug this fixed — see `CHANGELOG_v3.md` item 2) |

This confirms the pipeline up to "the config Wakeel would hand to
OpenLane/ORFS is correct" — the real-toolchain entries above are what
carries this further, into an actual live flow run.

## Not yet validated — needs your machine

- [ ] A real ORFS `synth_power_only` and full-flow run (all confirmed
      real runs so far are OpenLane/sky130 — ORFS/ASAP7 still needs a
      design folder staged there, or the RTL auto-stage feature
      exercised for real, to get its first live run).
- [ ] The `wakeel_alu` OpenLane/sky130 1 GHz run above completing (or
      genuinely failing) past CTS — it was intentionally stopped
      mid-flow to test the Stop button, not run to completion.
- [ ] At least one genuine self-heal cycle against a REAL failure (not a
      synthetic log) — i.e. a run that actually fails, gets diagnosed by
      the KB, retries, and succeeds. This is the differentiator; it needs
      to be shown working on a real signoff report, not just asserted.
- [ ] The loose-RTL auto-stage path (`find_loose_rtl`/`stage_design`)
      against a real `WAKEEL_RTL_SEARCH_ROOTS` list and a real design
      living outside either engine's folder structure.
- [ ] The sweep feature (list + range) run against a real multi-point
      sweep, confirming `ppa_summary`/`sweep_summary` match the CSV on
      disk after a real run.
- [ ] The Docker resolution path (`openlane_docker.py`'s `make -n mount`
      parsing) — implicitly exercised by the real runs above (they did
      reach the Docker-invoked OpenLane container), but not stress-tested
      against Makefile variations.
- [ ] More than one design. Everything above uses `wakeel_alu` — a second,
      structurally different design (different port list, a design with
      macros, something with multiple clock domains) would catch a lot
      that a single ALU won't.

## How to add to this file

Run something for real, then add a row/checkbox with: date, design,
engine, frequency, resource mode, and outcome (including failures —
a documented failure with what you learned from it is worth more here
than another silent success). Screenshots or a log excerpt in
`Example Output/` are welcome alongside the entry.
