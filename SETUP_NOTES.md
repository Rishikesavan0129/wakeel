# Wakeel v2 -- Agentic EDA Flow Orchestrator

Drives OpenLane and OpenROAD-flow-scripts (ORFS) end to end from a natural
language prompt: discovers the design, writes physical constraints, runs
the flow, and self-corrects on failure. Fully offline -- no cloud API,
no API key, no `google-generativeai` dependency anywhere in this package.

## What changed from v1

| | v1 | v2 |
|---|---|---|
| Prompt parsing | Gemini 2.5 Flash (required) | Regex parser (always available) + optional local model |
| Config generation | ~12 hardcoded f-string params | 101-entry schema, 74 previously-inert KB params now reachable |
| KB corrections | Only 3 numeric params actually applied | Every `adjustments` key resolves onto a real config var and gets applied |
| Design lookup | Exact folder-name match only | Fuzzy search (`difflib`) across OpenLane, ORFS, and custom roots |
| Error correction fallback | Gemini API call | Optional local model (Ollama), or bounded heuristic -- never blocks |
| Shell safety | `design`/`top_mod` interpolated raw into `rm -rf ...` | Every identifier passes `sanitize_identifier()` + `shlex.quote()` first |

## Module map

```
wakeel/
  config_schema.json   # the parameter registry -- ADD PARAMS HERE, not in .py
  config_generator.py  # generic schema -> config.tcl / config.mk renderer
  design_discovery.py  # fuzzy folder search, top-module detection, config seeding
  knowledge_base.py    # scored KB matching + applying corrections to real params
  local_llm.py         # optional Ollama-backed corrector, off by default
  orchestrator.py       # ties it together; run_agentic_flow_stream() entrypoint
wakeel_core.py          # 4-line shim so wakeel_api.py needs zero changes
wakeel_api.py            # FastAPI/WebSocket gateway
wakeel_knowledge_base.json  # unchanged from v1, just now fully wired up
```

## Making it "dynamically expandable"

Adding a new OpenLane or ORFS parameter is a JSON edit, not a code change:

```json
"NEW_PARAM": {
  "tool": "openlane",
  "type": "float",
  "default": 1.0,
  "format": "tcl_scalar",
  "category": "routing",
  "description": "...",
  "advisory": false,
  "maps_to": null
}
```

It's immediately: renderable by `config_generator.render()`, targetable by a
KB rule's `adjustments` block, and seedable from an existing config via
`design_discovery.read_existing_config()`. No other file needs to change.

Unknown keys aren't silently dropped either -- `render()` still emits them
with a `# WARN: not in schema` comment, so you can try an experimental knob
once before deciding it's worth a permanent schema entry.

## Enabling the local model (optional)

Everything works with zero LLM involvement -- the KB + regex parser handle
the large majority of cases deterministically. To add a local model as a
second-tier fallback (design intent: DeepSeek via Ollama, but any
Ollama-compatible model works):

```bash
ollama pull deepseek-coder-v2:16b
export WAKEEL_LOCAL_LLM_ENABLED=1
export WAKEEL_LOCAL_LLM_MODEL=deepseek-coder-v2:16b   # optional, this is the default
pip install httpx
```

If it's disabled, unreachable, or returns something unparseable, the
orchestrator falls through to the bounded heuristic (nudge utilization/
density down) -- it never blocks or crashes a run.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WAKEEL_OPENLANE_PATH` | `~/OpenLane` | OpenLane install root |
| `WAKEEL_ORFS_PATH` | `~/ORFS_7nm` | ORFS install root |
| `WAKEEL_EXTRA_DESIGN_ROOTS` | (empty) | `:`-separated extra folders to search for designs |
| `WAKEEL_ALLOWED_ORIGIN` | `http://127.0.0.1:5500` | Dashboard origin for CORS (was `*`) |
| `WAKEEL_LOCAL_LLM_ENABLED` | `0` | Enable the optional local-model fallback |
| `WAKEEL_LOCAL_LLM_URL` | `http://127.0.0.1:11434/api/generate` | Ollama (or compatible) endpoint |
| `WAKEEL_LOCAL_LLM_MODEL` | `deepseek-coder-v2:16b` | Model name to request |

## Known gaps / next steps

- `config_schema.json`'s per-type defaults for the ~101 entries are standard
  OpenLane/ORFS conventions but weren't validated against your exact tool
  versions -- review before trusting them in a real run, especially the
  CTS/PDN/signoff categories.
- The KB's non-numeric `adjustments` (e.g. `"increase halo/blockage"`) are
  currently logged as advisory-only rather than auto-applied, since
  guessing a magnitude from free text is exactly the kind of thing that
  should be a deliberate schema decision, not silent behavior. Converting
  the highest-traffic ones into structured overrides in the KB is the
  natural next KB-authoring pass.
- `write_physical_constraints()` still shells out via
  `asyncio.create_subprocess_shell` for the actual flow run
  (`flow.tcl`/`docker_shell make ...`) -- necessary since those are
  multi-stage shell pipelines, but every interpolated value going into that
  string is now sanitized/quoted first.
