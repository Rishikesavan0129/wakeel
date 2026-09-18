# Wakeel — Agentic EDA Flow Orchestrator

[![tests](https://github.com/Rishikesavan0129/wakeel/actions/workflows/tests.yml/badge.svg)](https://github.com/Rishikesavan0129/wakeel/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE.txt)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](requirements.txt)

**Prompt-driven, self-healing RTL-to-GDSII orchestration for OpenLane and OpenROAD-flow-scripts (ORFS).** Open source. Deterministic by default. No cloud API required.

> **Validation status:** the orchestration/config-generation logic is unit-tested (see badge above) and has been exercised against design-tree structures matching real OpenLane/ORFS installs. Full flow-execution validation against a live toolchain (Docker + PDK) is tracked honestly in [`VALIDATION.md`](VALIDATION.md) — check there before assuming any specific claim (e.g. "self-heals a real LVS failure") has been proven end-to-end rather than just implemented.

> "Run `wakeel_alu` at 200MHz on 130nm" → Wakeel finds the design, generates a schema-driven config, launches the real flow, and automatically corrects known failure signatures against real signoff tool output — without a human touching a config file mid-run.

---

## What this actually is

Wakeel is **not** an EDA tool. It doesn't place cells, route wires, or run DRC — [OpenLane](https://github.com/The-OpenROAD-Project/OpenLane), [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD), Magic, KLayout, and Netgen do all of that, exactly as they always have. Wakeel is the **orchestration and self-healing layer** on top: it turns a natural-language prompt into a correct, schema-validated config, launches the real flow, watches real tool output for known failure signatures, and retries with a corrected config automatically.

**Design principle: real EDA engines verify everything, always.** Wakeel never decides a run passed — Magic's DRC engine, Netgen's LVS, and OpenROAD's STA do, exactly as they would with zero AI involved. Wakeel's only job is closing the loop faster when something fails in a way it's already learned to recognize.

## Architecture

```
prompt ──▶ design discovery ──▶ schema-driven config generation ──▶ real OpenLane/ORFS run
                                                                            │
                                                    ┌───────────────────────┘
                                                    ▼
                                            failure? ──▶ read real signoff report files
                                                    │           │
                                                    │           ▼
                                                    │    match against deterministic
                                                    │    keyword-scored knowledge base
                                                    │           │
                                                    │           ▼
                                                    │    apply correction, re-render config
                                                    └───────────┘
                                                    (up to 3 attempts, every correction logged)
```

- **Design discovery** — fuzzy-matches a design name across your OpenLane/ORFS trees (typos and partial names resolve correctly).
- **Schema-driven config generation** — every OpenLane/ORFS variable is a typed, versioned entry, auto-discoverable from your own install (`wakeel.schema_refresh` reads your real `configuration/*.tcl` files, not a hand-maintained guess).
- **Physical-profile awareness** — synthesis strategy and resizer optimization scale with how aggressive the target clock is relative to the node, instead of one static default fighting every frequency.
- **Knowledge-base self-healing** — 50+ deterministic, keyword-scored rules mapped to real OpenLane/ORFS parameter adjustments. No LLM call required for the common failure modes. An optional local model (Ollama-backed, off by default) can handle failures the KB doesn't recognize — nothing in this project requires a cloud API key.
- **Report-level failure diagnosis** — self-heal reads actual signoff report files (`drc.rpt`, `lvs.rpt`), not just terminal output, so corrections can target the *specific* violation, not just "something failed."

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

## What's validated vs. what's in progress

Being direct about this rather than overselling it:

| | Status |
|---|---|
| OpenLane / sky130, single design, single frequency point | ✅ Verified — real, complete, clean signoff |
| Deterministic KB-first self-healing | ✅ Verified against a real, previously-undiagnosed failure |
| Broader design/frequency coverage on OpenLane | 🔶 In progress |
| ORFS / ASAP7 real-run validation | 🔶 Config generation verified; real end-to-end run not yet completed |
| "Deterministic" | True **by default** — the optional local-LLM fallback (off unless explicitly enabled) is the one non-deterministic path, used only when the KB has no match |

## Quick start

```bash
git clone <this-repo>
cd wakeel_v2
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export WAKEEL_OPENLANE_PATH=~/OpenLane
export WAKEEL_ORFS_PATH=~/ORFS_7nm

python3 -m wakeel.schema_refresh   # pulls real variables from your OpenLane install
python3 wakeel_api.py              # starts the server
```

In another terminal:
```bash
python3 cli_run.py "run my_design at 100 MHz on 130nm"
```

Or open `index.html` for the full dashboard with live logs and PPA charts.

## Repo layout

```
wakeel/
  config_schema.json     # typed variable registry -- auto-expandable, see schema_refresh.py
  config_generator.py    # schema -> config.tcl / config.mk renderer
  design_discovery.py    # fuzzy design search
  knowledge_base.py      # deterministic self-heal matching + correction
  local_llm.py           # optional Ollama fallback, off by default
  openlane_docker.py     # resolves the real docker invocation from your own Makefile
  physical_profile.py    # frequency-aware synthesis/resizer strategy
  schema_refresh.py      # auto-discovers real variables from your OpenLane install
  orchestrator.py        # ties it all together
wakeel_api.py             # FastAPI/WebSocket gateway
cli_run.py                 # terminal client, no browser needed
index.html                  # dashboard
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
