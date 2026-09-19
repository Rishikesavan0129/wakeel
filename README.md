# Wakeel — Agentic EDA Flow Orchestrator

[![tests](https://github.com/Rishikesavan0129/wakeel/actions/workflows/tests.yml/badge.svg)](https://github.com/Rishikesavan0129/wakeel/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE.txt)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](requirements.txt)

**Prompt-driven, self-healing RTL-to-GDSII orchestration for OpenLane and OpenROAD-flow-scripts (ORFS).** Open source. Deterministic by default. No cloud API required.

> **Validation status:** the orchestration/config-generation logic is unit-tested (38 tests, see badge above) and has been exercised against design-tree structures matching real OpenLane/ORFS installs, plus real live OpenLane/sky130 runs. Full flow-execution validation against a live toolchain (Docker + PDK) is tracked honestly in [`VALIDATION.md`](VALIDATION.md) — check there before assuming any specific claim (e.g. "self-heals a real LVS failure") has been proven end-to-end rather than just implemented.

> "Run `wakeel_alu` at 200MHz on 130nm" → Wakeel finds the design, generates a schema-driven config, launches the real flow, and automatically corrects known failure signatures against real signoff tool output — without a human touching a config file mid-run.

---

## What this actually is

Wakeel is **not** an EDA tool. It doesn't place cells, route wires, or run DRC — [OpenLane](https://github.com/The-OpenROAD-Project/OpenLane), [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD), Magic, KLayout, and Netgen do all of that, exactly as they always have. Wakeel is the **orchestration and self-healing layer** on top: it turns a natural-language prompt (or explicit UI/CLI controls) into a correct, schema-validated config, launches the real flow, watches real tool output for known failure signatures, and retries with a corrected config automatically.

**Design principle: real EDA engines verify everything, always.** Wakeel never decides a run passed — Magic's DRC engine, Netgen's LVS, and OpenROAD's STA do, exactly as they would with zero AI involved. Wakeel's only job is closing the loop faster when something fails in a way it's already learned to recognize.

## Architecture

```
prompt/UI ──▶ design discovery (+ loose-RTL auto-stage) ──▶ schema-driven config ──▶ real OpenLane/ORFS run
                                                                                            │
                                                    ┌───────────────────────────────────────┘
                                                    ▼
                                            failure? ──▶ read real signoff report files
                                                    │           │
                                                    │           ▼
                                                    │    match against deterministic
                                                    │    keyword-scored knowledge base
                                                    │    (confidence floor + oscillation guard)
                                                    │           │
                                                    │           ▼
                                                    │    apply correction, re-render config
                                                    └───────────┘
                                        (configurable retry budget, every correction logged,
                                         cancellable mid-run via Stop)
```

- **Design discovery** — fuzzy-matches a design name across your OpenLane/ORFS trees (typos and partial names resolve correctly). If a design only exists as loose RTL somewhere else on disk, the **loose-RTL auto-stage** path (`WAKEEL_RTL_SEARCH_ROOTS`) finds and copies it into the right engine's folder automatically.
- **Explicit engine/tech-node selection** — a UI toggle and `--engine`/payload option bypass prompt-text guessing entirely; if the requested engine still has no matching design, Wakeel surfaces an explicit `[ENGINE FALLBACK]` warning instead of silently running on the wrong one.
- **Schema-driven config generation** — every OpenLane/ORFS variable is a typed, versioned entry, auto-discoverable from your own install (`wakeel.schema_refresh` reads your real `configuration/*.tcl` files, not a hand-maintained guess).
- **Physical-profile awareness** — synthesis strategy and resizer optimization scale with how aggressive the target clock is relative to the node, for **both** OpenLane and ORFS, instead of one static default fighting every frequency. Arbitrated against the knowledge base so a self-heal fix never gets silently overwritten on the next retry.
- **Knowledge-base self-healing** — 51 deterministic, keyword-scored rules mapped to real OpenLane/ORFS parameter adjustments, with a confidence floor (a weak match is rejected, not trusted) and an oscillation guard (a rule that already fired won't reapply itself). No LLM call required for the common failure modes. An optional local model (Ollama-backed, off by default) can handle failures the KB doesn't recognize — nothing in this project requires a cloud API key.
- **Report-level failure diagnosis** — self-heal reads actual signoff report files (`drc.rpt`, `lvs.rpt`), not just terminal output, so corrections can target the *specific* violation, not just "something failed."
- **User-configurable sweeps** — an explicit frequency list or range (UI/CLI), not just whatever GHz/MHz the prompt text happens to mention, with a configurable retry budget and sweep-point cap.
- **Real cancellation** — a Stop button (or Ctrl+C on the CLI) actually kills the live subprocess's process group, not just the UI connection.
- **Industrial-practice power analysis** — the pre-layout power-estimate TCL supports real SAIF/VCD activity annotation and prints an explicit warning when neither is supplied, instead of silently trusting a default toggle-rate assumption.

## Case study: the `nwell.4` tap-cell desert

This is the clearest example of why the architecture is built the way it is, so it's worth documenting in detail rather than just claiming "self-healing works."

**The problem:** a small, DRC-clean, LVS-clean design kept failing final Magic DRC signoff with exactly 2 violations: `All nwells must contain metal-connected N+ taps (nwell.4)`. Routing DRC was clean. LVS was clean. Only this one signoff check failed, every time.

**What didn't work, and why that mattered:** the obvious fix — reduce `FP_TAPCELL_DIST` to increase tap-cell density — was tried across four different values (15→10→7→20). The violation's *position* shifted slightly each time, but its *size* stayed **exactly 0.840µm × 1.655µm** in every single case. Switching the floorplan from absolute (1500×1500µm) to relative sizing (a >14x smaller die) produced the identical 0.840×1.655µm box again. A real spacing problem would respond to spacing changes. This didn't — which is itself the diagnostic signal.

**Root cause:** this matches a documented upstream limitation in OpenROAD's own tap-cell insertion algorithm — [`OpenROAD#7118`, "tap: insertion pattern may leave 'tap deserts' with higher values"](https://github.com/The-OpenROAD-Project/OpenROAD/issues/7118). Certain row-boundary conditions can leave a fixed-size gap regardless of the configured tap distance. It's a tool-level artifact, not a design defect and not a config mistake — confirmed by four independent data points before accepting the conclusion, not assumed from the first failure.

**The fix, encoded as a real, generalizable rule:**

```json
{
  "id": "FP-007",
  "error_keywords": ["nwell.4", "metal-connected N+ taps", "Should be divided by 3 or 4"],
  "adjustments": { "QUIT_ON_MAGIC_DRC": false },
  "explanation": "Known upstream OpenROAD tap-desert artifact (issue #7118)..."
}
```

Not "ignore all DRC" — a precise keyword signature matched against the *actual report file content*, forcing exactly one flag off for exactly this failure pattern. Any future design hitting this same upstream limitation is handled automatically, with the reasoning logged inline, not silently.

**Result:** verified end-to-end on real hardware — the flow's own self-heal loop matched this rule against a real failing run, applied the correction, and completed a clean OpenLane signoff (LVS clean, 0 DRC violations, 0 setup violations, 0 hold violations) with zero manual config edits.

## What's new in v3

A from-scratch architecture review turned up real bugs and gaps in v2 — fixed and closed here, not just patched over. Full detail in [`CHANGELOG_v3.md`](CHANGELOG_v3.md); summary:

**Bug fixes**
- `physical_profile` vs. knowledge-base key collision — a self-heal fix could get silently overwritten by the tier default on the very next retry attempt
- A `0`/`1`-vs-boolean bug in 3 real KB rules — the adjustment silently no-op'd instead of applying
- ORFS physical-profile parity — was warning-only at aggressive/extreme frequencies, now sets real schema-verified knobs
- Oscillation guard — a KB rule can no longer reapply itself indefinitely across retries without resolving the failure
- Confidence floor on KB matching — a weak, coincidental keyword match is now rejected rather than trusted with full authority
- Silent engine fallback — a real incident where a prompt correctly requested ORFS/7nm but silently ran on OpenLane/sky130 with no warning; now surfaced explicitly

**New features**
- Configurable self-heal retry budget and sweep-point cap (server-clamped ceilings)
- Explicit engine/tech-node toggle, bypassing prompt-text guessing
- Loose-RTL auto-discovery and staging (`WAKEEL_RTL_SEARCH_ROOTS`) — a design living outside either engine's folder structure gets found and staged automatically
- Real Stop/cancel control — kills the actual subprocess, not just the UI connection
- Structured PPA output (`ppa_summary`/`sweep_summary` JSON events, re-read from the CSV Wakeel writes) instead of the UI regex-scraping log text
- User-configurable frequency sweep — explicit list or range, from the UI, CLI, or API payload
- Power-analysis TCL rewritten to industrial/academic standard — real SAIF/VCD activity support, explicit warning when neither is supplied
- Full UI rebuild — instrument-panel dashboard with a day/night ("blueprint") theme, replacing the earlier cyberpunk interface

**Process**
- 38-test automated suite (`tests/`), CI on every push (`.github/workflows/tests.yml`)
- `CONTRIBUTING.md`, `SECURITY.md`, `VALIDATION.md`, `CHANGELOG_v3.md`
- Pinned, cross-Python-version-compatible dependencies (`requirements.txt`/`requirements-dev.txt`)

## What's validated vs. what's in progress

Being direct about this rather than overselling it:

| | Status |
|---|---|
| OpenLane / sky130, single design, single frequency point | ✅ Verified — real, complete, clean signoff |
| Deterministic KB-first self-healing | ✅ Verified against a real, previously-undiagnosed failure |
| Engine-fallback warning, Stop/cancel control | ✅ Verified live against a real OpenLane/sky130 run |
| Broader design/frequency coverage on OpenLane | 🔶 In progress |
| ORFS / ASAP7 real-run validation | 🔶 Config generation verified; real end-to-end run not yet completed |
| Loose-RTL auto-stage against a real `WAKEEL_RTL_SEARCH_ROOTS` list | 🔶 Unit-tested; not yet exercised on a real live run |
| "Deterministic" | True **by default** — the optional local-LLM fallback (off unless explicitly enabled) is the one non-deterministic path, used only when the KB has no match |

See [`VALIDATION.md`](VALIDATION.md) for the full, dated log.

## Quick start

```bash
git clone https://github.com/Rishikesavan0129/wakeel.git
cd wakeel
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + pytest

export WAKEEL_OPENLANE_PATH=~/OpenLane
export WAKEEL_ORFS_PATH=~/ORFS_7nm
# optional: a colon-separated list of project folders to search for loose RTL
export WAKEEL_RTL_SEARCH_ROOTS=~/my_projects:~/other_stuff

python3 -m wakeel.schema_refresh   # pulls real variables from your OpenLane install
pytest tests/ -v                   # 38 tests, no Docker/PDK required
python3 wakeel_api.py              # starts the server
```

In another terminal:
```bash
python3 cli_run.py "run my_design at 100 MHz on 130nm"

# explicit sweep, engine, and self-heal knobs:
python3 cli_run.py "run my_design on 7nm" --sweep 0.2,0.5,1.0 --engine orfs --max-retries 5
```

Or open `index.html` for the full dashboard — live logs, PPA charts, sweep/engine controls, a Stop button, and a day/night theme.

## Repo layout

```
wakeel/
  config_schema.json     # typed variable registry -- auto-expandable, see schema_refresh.py
  config_generator.py    # schema -> config.tcl / config.mk renderer
  design_discovery.py    # fuzzy design search + loose-RTL auto-stage (find_loose_rtl/stage_design)
  knowledge_base.py      # deterministic self-heal matching + correction
  local_llm.py           # optional Ollama fallback, off by default
  openlane_docker.py     # resolves the real docker invocation from your own Makefile
  physical_profile.py    # frequency-aware synthesis/resizer strategy, both engines
  schema_refresh.py      # auto-discovers real variables from your OpenLane install
  orchestrator.py        # ties it all together -- the main run loop
tests/                    # 38 pytest tests, no Docker/PDK required
.github/workflows/        # CI -- runs the test suite on every push
wakeel_api.py             # FastAPI/WebSocket gateway
cli_run.py                 # terminal client, no browser needed
index.html                  # dashboard
requirements.txt            # runtime deps, pinned
requirements-dev.txt         # + pytest
CHANGELOG_v3.md               # what changed in v3, in detail
VALIDATION.md                  # what's actually been proven against real hardware
CONTRIBUTING.md                 # how to run tests, where things live
SECURITY.md                      # how to report a vulnerability privately
```

## Why this exists

Started because I wanted to run the ASAP7 predictive PDK without hand-editing `config.tcl`/`config.mk` every single time I changed a design or a target frequency. What began as a config-generation convenience turned into a genuine question: how much of physical-design flow babysitting can be handled deterministically, with real EDA tools as the final word on every decision?

## Related work

Wakeel is an orchestration/self-healing layer, not a parameter-search
tool — if what you actually want is automated PPA hyperparameter search
over ORFS, [OpenROAD AutoTuner](https://openroad-flow-scripts.readthedocs.io/en/latest/user/InstructionsForAutoTuner.html)
already does that (Bayesian optimization / Optuna / grid search, Ray-distributed)
and is the right tool for it — Wakeel doesn't try to replace it. Where
Wakeel is different: it reads real signoff report files (`drc.rpt`,
`lvs.rpt`, not just terminal exit codes) after a failure and proposes a
diagnosed, explained config correction, rather than searching the
parameter space blind against a PPA score. The two are complementary,
not competing — an AutoTuner-style search loop for the OpenLane path
specifically (which doesn't have one yet) is on the roadmap; see
`CHANGELOG_v3.md`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to run the test suite
and where things live in the codebase, [`VALIDATION.md`](VALIDATION.md)
for what's actually been proven against a real toolchain vs. only
unit-tested, and [`SECURITY.md`](SECURITY.md) to report a vulnerability
privately rather than as a public issue.

## License

Apache License 2.0 — see [`LICENSE.txt`](LICENSE.txt). Chosen for
compatibility with OpenLane (Apache-2.0) and ORFS (BSD-3-Clause).

## Acknowledgments

Built on [OpenLane](https://github.com/The-OpenROAD-Project/OpenLane), [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD), and [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts). Architected and debugged by the author; implementation assisted by Claude (Anthropic).
