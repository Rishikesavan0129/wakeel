"""
Wakeel orchestrator -- Gemini fully removed.

Correction order is now strictly:
  1. KnowledgeBase (deterministic, scored keyword match against 50+ rules)
  2. Optional local model via wakeel.local_llm (off by default, Ollama-backed)
  3. Bounded numeric fallback (nudge core_util/place_density down, same
     floor logic the original had) if neither of the above produced anything

No step requires network access or an API key. The whole pipeline runs
offline by default.
"""
from __future__ import annotations
import asyncio
import glob
import json
import os
import re
import shlex
import shutil
import signal
from collections import deque

from . import local_llm
from . import metrics_parser
from . import openlane_docker
from . import physical_profile
from .config_generator import ConfigSchema, build_params, render
from .design_discovery import DesignSearch, find_loose_rtl, stage_design
from .knowledge_base import KnowledgeBase

ORFS_PATH = os.path.expanduser(os.getenv("WAKEEL_ORFS_PATH", "~/ORFS_7nm"))
OPENLANE_PATH = os.path.expanduser(os.getenv("WAKEEL_OPENLANE_PATH", "~/OpenLane"))
EXTRA_SEARCH_ROOTS = [p for p in os.getenv("WAKEEL_EXTRA_DESIGN_ROOTS", "").split(":") if p]
# v3: a SEPARATE, narrower list from EXTRA_SEARCH_ROOTS above -- those are
# expected to look like real design folders (with a src/ dir, optionally an
# existing config); RTL_SEARCH_ROOTS is for bare .v/.sv files living
# anywhere in a small, user-specified list of project folders, found via
# design_discovery.find_loose_rtl() and staged into the right engine's
# design root on demand. See that function's docstring for why this is
# never a whole-filesystem crawl.
RTL_SEARCH_ROOTS = [p for p in os.getenv("WAKEEL_RTL_SEARCH_ROOTS", "").split(":") if p]

# v3: watchdog timeout for a single subprocess invocation (one sweep-point
# attempt). A hung container (waiting on a swallowed interactive prompt, a
# license-server deadlock, whatever) used to block the orchestrator
# forever with nothing to time it out. Generous default because a real
# full-flow PnR run can legitimately take hours -- override via env for a
# tighter bound in CI/smoke-test contexts.
RUN_TIMEOUT_SECONDS = int(os.getenv("WAKEEL_RUN_TIMEOUT_SECONDS", str(4 * 3600)))

# v3: DEFAULT cap on a caller-specified sweep -- a sanity default, not a
# hard engineering limit. Callers can raise it per-request (see
# build_sweep_clocks_ps's max_points arg / wakeel_api.py's "max_sweep_points"
# payload key), but ABSOLUTE_MAX_SWEEP_POINTS below is the one that can't be
# overridden -- that's the real backstop against a malformed request
# accidentally queueing an unbounded number of multi-hour PnR runs.
MAX_SWEEP_POINTS = 50
ABSOLUTE_MAX_SWEEP_POINTS = 200

# v3: same pattern for the self-heal retry budget -- DEFAULT_MAX_RETRIES is
# what run_agentic_flow_stream uses unless a caller asks for a different
# number (see "max_retries" in wakeel_api.py's payload / cli_run.py's
# --max-retries), bounded by ABSOLUTE_MAX_RETRIES so a request can't set it
# to something that burns an unreasonable amount of compute chasing a
# failure the knowledge base clearly isn't going to fix.
DEFAULT_MAX_RETRIES = 3
ABSOLUTE_MAX_RETRIES = 10

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")

# v3: one asyncio.Lock per (engine, design name), so two concurrent runs
# targeting the same design can't race on _clean_run_dir -- one run
# wiping the run directory a second, in-flight run is still writing into.
# Module-level and in-process only: correct for the single-worker uvicorn
# process this app runs as (see wakeel_api.py); would need a real
# cross-process lock (file lock / redis) if that ever changes.
_design_locks: dict[str, asyncio.Lock] = {}


def _get_design_lock(engine: str, design_name: str) -> asyncio.Lock:
    key = f"{engine}:{design_name}"
    if key not in _design_locks:
        _design_locks[key] = asyncio.Lock()
    return _design_locks[key]


def sanitize_identifier(name: str, fallback: str = "unknown_design") -> str:
    """Any name that will end up inside a shell command or filesystem path
    must pass through this first. Rejects anything outside [A-Za-z0-9_] --
    which every real Verilog module/design-folder name already satisfies --
    instead of trying to escape arbitrary strings. This is what closes the
    `rm -rf {path}/{design}` injection surface from the previous version:
    design/top_mod can now never contain shell metacharacters, `..`, or
    path separators, full stop."""
    if name and _IDENTIFIER_RE.match(name):
        return name
    return fallback


# ==========================================================================
# Prompt -> structured run parameters (regex-first; local LLM optional)
# ==========================================================================

def offline_fallback_parser(prompt: str) -> dict:
    """Deterministic regex parser. This is the ONLY required parser --
    local_llm.parse_prompt() is tried first if enabled, but this always
    runs and its result is what actually gets used if the model is off,
    unreachable, or returns something unparseable."""
    params = {
        "design_query": None,
        "clock_period_ps": [1000],
        "engine": "orfs",
        "core_util": None,
        "place_density": None,
        # BUGFIX (real incident): these used to default to concrete strings
        # ("absolute" / "0 0 1500 1500") instead of None. Since orchestrator.py's
        # base_params filter only drops None values, a prompt that never
        # mentions floorplan sizing at all would ALWAYS overwrite whatever
        # was manually edited into an existing seeded config -- silently
        # reverting a deliberate "set FP_SIZING to relative" edit back to
        # absolute on the very next run, with no warning. Same bug class as
        # PDK/QUIT_ON_XOR_ERROR/RUN_KLAYOUT_XOR earlier tonight, just at the
        # parser level instead of the schema level. None here means "don't
        # touch it, let whatever's seeded win" -- only set a real value when
        # the prompt actually says something explicit.
        "fp_sizing": None,
        "die_area": None,
        "resource_mode": None,  # resolved below, engine-dependent
    }
    p = prompt.lower()

    if "130nm" in p or "sky130" in p or "openlane" in p:
        params["engine"] = "openlane"
    if "7nm" in p or "asap7" in p or "orfs" in p:
        params["engine"] = "orfs"
    if "relative" in p:
        params["fp_sizing"] = "relative"
    elif "absolute" in p:
        params["fp_sizing"] = "absolute"

    ghz_matches = re.findall(r'([\d.]+)\s*ghz', p)
    if ghz_matches:
        params["clock_period_ps"] = [int(1000 / float(g)) for g in ghz_matches]
    else:
        mhz_matches = re.findall(r'([\d.]+)\s*mhz', p)
        if mhz_matches:
            params["clock_period_ps"] = [int(1_000_000 / float(m)) for m in mhz_matches]

    # Design name candidate: prefer explicit underscore_style identifiers
    # (matches how these design folders are actually named), fall back to
    # any bare word -- DesignSearch.find() does the real fuzzy resolution
    # against the filesystem afterwards, so this only needs to be a
    # reasonable guess, not an exact match.
    underscore_matches = re.findall(r'\b([a-zA-Z][a-zA-Z0-9]*_[a-zA-Z0-9_]+)\b', prompt)
    if underscore_matches:
        params["design_query"] = underscore_matches[0]
    else:
        words = [w for w in re.findall(r'[a-zA-Z]{3,}', prompt)
                 if w.lower() not in {"run", "the", "project", "design", "at", "mhz", "ghz", "for"}]
        params["design_query"] = words[0] if words else None

    # Hardware-aware default: a full 7nm ORFS flow through detailed place/
    # CTS/route is genuinely CPU-heavy (that's where the cost actually is,
    # not synthesis). Default to synth + pre-layout power estimate only for
    # ORFS runs, and only go full if the prompt explicitly asks for it --
    # place and route, tapeout, GDS, or "full flow" style phrasing.
    if params["engine"] == "orfs":
        params["resource_mode"] = _infer_resource_mode(prompt, "orfs")
    else:
        params["resource_mode"] = "full"

    return params


_FULL_FLOW_KEYWORDS = ("full flow", "full run", "complete flow", "place and route",
                        "place & route", "pnr", "route to gds", "gdsii", "tapeout",
                        "finish the flow", "full pnr")


def _infer_resource_mode(prompt: str, engine: str) -> str:
    """Factored out of offline_fallback_parser so run_agentic_flow_stream can
    re-derive resource_mode correctly when an explicit engine_override
    changes which engine actually applies -- the prompt-parsed
    resource_mode was computed against whatever engine the PROMPT implied,
    which may not be the engine the UI's toggle actually selected."""
    p = prompt.lower()
    if engine == "orfs":
        return "full" if any(k in p for k in _FULL_FLOW_KEYWORDS) else "synth_power_only"
    return "full"


class SweepConfigError(ValueError):
    """Raised for a caller-specified sweep config that doesn't make sense
    (empty, negative/zero frequencies, or over the point cap) -- these are
    always user-input problems, never a flow/tool failure, so they're
    reported back to the client immediately rather than attempted."""


def build_sweep_clocks_ps(sweep_cfg: dict, max_points: int = MAX_SWEEP_POINTS) -> list[int]:
    """Turns a user-specified sweep config into a list of clock periods in
    ps, the unit the rest of the pipeline already works in. Two shapes are
    accepted:

      {"frequencies_ghz": [0.2, 0.5, 1.0]}          -- an explicit list
      {"start_ghz": 0.2, "end_ghz": 1.0, "step_ghz": 0.2}  -- an inclusive range

    This is what lets a sweep be driven by real UI controls instead of
    regex-parsing whatever GHz/MHz numbers happen to appear in the free-text
    prompt (offline_fallback_parser's ghz_matches/mhz_matches) -- when the
    caller supplies this, it replaces the prompt-parsed sweep entirely
    rather than merging with it, so there's exactly one unambiguous source
    of truth for what gets run.

    `max_points`: caller-adjustable point cap (see MAX_SWEEP_POINTS /
    ABSOLUTE_MAX_SWEEP_POINTS) -- always clamped to
    ABSOLUTE_MAX_SWEEP_POINTS regardless of what's passed in, so this
    knob can only be tightened or loosened within a hard ceiling, never
    disabled outright.
    """
    max_points = min(max_points, ABSOLUTE_MAX_SWEEP_POINTS)
    if "frequencies_ghz" in sweep_cfg:
        freqs = sweep_cfg["frequencies_ghz"]
        if not isinstance(freqs, list) or not freqs:
            raise SweepConfigError("frequencies_ghz must be a non-empty list.")
    elif "start_ghz" in sweep_cfg and "end_ghz" in sweep_cfg:
        start, end = float(sweep_cfg["start_ghz"]), float(sweep_cfg["end_ghz"])
        step = float(sweep_cfg.get("step_ghz", 0.1))
        if step <= 0:
            raise SweepConfigError("step_ghz must be > 0.")
        if end < start:
            raise SweepConfigError("end_ghz must be >= start_ghz.")
        freqs = []
        f = start
        # small epsilon guards against float step accumulation stopping
        # one step short of `end` (e.g. 0.1 + 0.1 + 0.1 != 0.3 exactly).
        while f <= end + step * 1e-6:
            freqs.append(round(f, 6))
            f += step
    else:
        raise SweepConfigError(
            "sweep must contain either 'frequencies_ghz' (a list) or "
            "'start_ghz'/'end_ghz' (optionally 'step_ghz')."
        )

    if len(freqs) > max_points:
        raise SweepConfigError(
            f"Sweep would produce {len(freqs)} points, over the {max_points}-point cap "
            f"(hard ceiling: {ABSOLUTE_MAX_SWEEP_POINTS}). Narrow the range/step, split it "
            f"into multiple requests, or raise max_sweep_points up to the ceiling."
        )
    for g in freqs:
        if g <= 0:
            raise SweepConfigError(f"Frequency {g} GHz is not > 0.")

    return [int(round(1000.0 / g)) for g in freqs]


async def resolve_params(prompt: str) -> dict:
    llm_params = await local_llm.parse_prompt(prompt)
    regex_params = offline_fallback_parser(prompt)
    if llm_params and llm_params.get("design_query"):
        # local model result wins only where it actually returned something;
        # regex fills any gaps so a partial/odd model response never leaves
        # a required field empty.
        merged = {**regex_params, **{k: v for k, v in llm_params.items() if v}}
        return merged
    return regex_params


# ==========================================================================
# Self-healing: KB first, optional local model second, bounded fallback last
# ==========================================================================

async def heal(error_log: str, params: dict, engine: str, kb: KnowledgeBase,
                schema: ConfigSchema, websocket, excluded_rule_ids: set | None = None
                ) -> tuple[dict, str, dict]:
    """Returns (params, explanation, meta). meta = {"source": "kb"|"local_llm"|
    "bounded", "rule_id": str|None, "touched_keys": set[str]} -- the caller
    (run_agentic_flow_stream) uses this to (a) detect a rule oscillating
    across retries via excluded_rule_ids, and (b) tell physical_profile
    which of its owned keys a KB fix already claimed this attempt, so it
    doesn't silently overwrite the fix on the next retry (see
    physical_profile.apply's `locked_keys`).
    """
    matches = kb.match(error_log, top_n=1, exclude_ids=excluded_rule_ids)
    if matches:
        rule_id = matches[0].rule.get("id", "?")
        params, explanation, touched_keys = kb.apply(matches[0], params, engine)
        await _send(websocket, "warning", f"[KB:{rule_id}] {explanation}")
        return params, explanation, {"source": "kb", "rule_id": rule_id, "touched_keys": touched_keys}

    try:
        adjustments, explanation = await local_llm.suggest_fix(error_log, params, engine)
        touched_keys = set()
        for raw_key, delta in adjustments.items():
            real_key = schema.resolve_alias(raw_key, engine) or raw_key
            spec = schema.spec(real_key, engine)
            current = params.get(real_key, spec.default if spec else None)
            if isinstance(delta, (int, float)) and isinstance(current, (int, float)):
                params[real_key] = round(current + delta, 6)
            else:
                params[real_key] = delta
            touched_keys.add(real_key)
        await _send(websocket, "warning", f"[LOCAL-LLM] {explanation}")
        return params, explanation, {"source": "local_llm", "rule_id": None, "touched_keys": touched_keys}
    except local_llm.LocalCorrectorUnavailable as e:
        await _send(websocket, "warning", f"[AUTO-HEAL HEURISTICS] No KB match, local model unavailable ({e}). "
                                            "Applying bounded fallback nudge.")

    util_key = schema.resolve_alias("core_util", engine) or "core_util"
    density_key = schema.resolve_alias("place_density", engine) or "place_density"
    touched_keys = set()
    if util_key in params and isinstance(params[util_key], (int, float)):
        params[util_key] = max(20, params[util_key] - 5)
        touched_keys.add(util_key)
    if density_key in params and isinstance(params[density_key], (int, float)):
        params[density_key] = max(0.20, round(params[density_key] - 0.05, 3))
        touched_keys.add(density_key)
    return params, "Bounded fallback: reduced utilization/density.", {
        "source": "bounded", "rule_id": None, "touched_keys": touched_keys,
    }


# ==========================================================================
# Physical constraint writing (now schema-driven, see config_generator.py)
# ==========================================================================

def generate_sdc(top_mod: str, clk_period_ps: float) -> str:
    io_delay = float(clk_period_ps) * 0.2
    return f"""# WAKEEL SDC CONSTRAINTS
current_design {top_mod}
create_clock -name clk -period {clk_period_ps} [get_ports clk]
set_input_delay {io_delay} -clock clk [all_inputs]
set_output_delay {io_delay} -clock clk [all_outputs]
"""


def write_physical_constraints(design_info, params: dict, schema: ConfigSchema,
                                current_clock_ps: float, preview_dir: str | None = None,
                                locked_keys: set | None = None) -> tuple[str, list[str]]:
    """Returns (engine_path, profile_notes). profile_notes are human-readable
    strings describing any frequency-aware adjustments physical_profile.apply()
    made -- callers should surface these to the user (websocket or print),
    since silently changing SYNTH_STRATEGY/resizer settings behind someone's
    back is exactly the kind of thing that should be visible, not implicit.

    BUGFIX (safety, real incident): this function always writes for real --
    that's correct and necessary for the actual GUI/orchestrator flow, but
    dry_run.py was calling this exact same function with no way to avoid
    it, meaning every "dry run" was silently overwriting the REAL
    config.tcl/config.mk on disk, permanently destroying whatever was there
    before (including, in one real case, losing the ability to tell whether
    an existing design's config had ever set PDK/STD_CELL_LIBRARY at all).
    `preview_dir`, when given, redirects every write (config file, SDC,
    staged sources) to that folder instead of the real design directory --
    the real design tree is never touched. dry_run.py now always passes
    this; the real orchestrator.run_agentic_flow_stream never does, so its
    behavior is completely unchanged.
    """
    engine = design_info.engine
    freq_ghz = round(1000.0 / current_clock_ps, 4)
    overrides = dict(params)
    overrides["DESIGN_NAME"] = design_info.top_module
    overrides["CLOCK_PERIOD"] = (current_clock_ps if engine == "orfs"
                                  else round(current_clock_ps / 1000.0, 3))

    if engine == "openlane":
        target_dir = design_info.design_dir if preview_dir is None else preview_dir
        os.makedirs(os.path.join(target_dir, "src") if preview_dir is None else target_dir, exist_ok=True)
        overrides["VERILOG_FILES"] = (
            f'[glob -nocomplain $::env(DESIGN_DIR)/src/*.v $::env(DESIGN_DIR)/src/*.sv]'
        )
        full_params = build_params("openlane", schema, overrides)
        full_params, notes = physical_profile.apply(full_params, "openlane", freq_ghz, locked_keys)

        # BUGFIX (real incident): a schema DEFAULT can never override a value
        # that's explicitly present in a seeded existing config -- that's
        # correct/intentional layering (proven with PDK/STD_CELL_LIBRARY
        # earlier), but it means a plain default for QUIT_ON_XOR_ERROR=False
        # silently does nothing for any design that already has a prior
        # real run's config.tcl on disk with QUIT_ON_XOR_ERROR=1 baked in --
        # which wakeel_alu did, causing this exact override to appear to
        # "not work" despite being applied correctly. Force it the same way
        # physical_profile.py forces its own owned keys: applied AFTER
        # seeding, unconditionally, every run, so it can't be silently
        # shadowed by whatever a previous run happened to write to disk.
        full_params["QUIT_ON_XOR_ERROR"] = False
        full_params["RUN_KLAYOUT_XOR"] = False
        notes.append("[FORCED OVERRIDE] QUIT_ON_XOR_ERROR set to False, RUN_KLAYOUT_XOR set to False "
                      "regardless of seeded config -- skips the Magic/KLayout XOR agreement check entirely "
                      "(it's a tooling cross-check, not a design-correctness check; DRC already covers that "
                      "separately, and this check alone took ~17 minutes on a trivial design last run). "
                      "This also lets the flow continue on to LVS instead of stopping at step 29.")

        config_text = render("openlane", full_params, schema)
        with open(os.path.join(target_dir, "config.tcl"), "w") as f:
            f.write(config_text)
        return OPENLANE_PATH, notes

    else:
        # BUGFIX: design_discovery.py always finds ORFS designs' source
        # files already sitting inside <design_dir>/src -- that's the only
        # place it looks. The old code here unconditionally copied
        # design_info.v_files into design_info.src_dir, which for a design
        # already living in the standard ORFS tree means copying a file
        # onto itself (shutil.SameFileError) every single run. The only
        # case that genuinely needs staging is a design found via
        # WAKEEL_EXTRA_DESIGN_ROOTS, i.e. living somewhere the ORFS docker
        # container can't see -- and even then, the correct destination is
        # the canonical ORFS-tree path, not design_info.src_dir itself.
        if preview_dir is not None:
            target_dir = preview_dir
            target_src_dir = os.path.join(target_dir, "src")
        else:
            orfs_target_dir = os.path.join(ORFS_PATH, "flow", "designs", "asap7", design_info.name)
            already_in_orfs_tree = os.path.abspath(design_info.design_dir) == os.path.abspath(orfs_target_dir)
            target_dir = design_info.design_dir if already_in_orfs_tree else orfs_target_dir
            target_src_dir = os.path.join(target_dir, "src")
        os.makedirs(target_src_dir, exist_ok=True)

        sdc_content = generate_sdc(design_info.top_module, current_clock_ps)
        with open(os.path.join(target_dir, "constraint.sdc"), "w") as f:
            f.write(sdc_content)
        overrides["SDC_FILE"] = f"/OpenROAD-flow-scripts/flow/designs/asap7/{design_info.name}/constraint.sdc"

        docker_v_files = []
        for f in design_info.v_files:
            dest = os.path.join(target_src_dir, os.path.basename(f))
            if preview_dir is None:
                _safe_copy(f, dest)
            docker_v_files.append(
                f"/OpenROAD-flow-scripts/flow/designs/asap7/{design_info.name}/src/{os.path.basename(f)}"
            )
        overrides["VERILOG_FILES"] = " ".join(docker_v_files)

        if design_info.saif_file:
            saif_basename = os.path.basename(design_info.saif_file)
            if preview_dir is None:
                _safe_copy(design_info.saif_file, os.path.join(target_src_dir, saif_basename))
            overrides["SAIF_FILE"] = f"/OpenROAD-flow-scripts/flow/designs/asap7/{design_info.name}/src/{saif_basename}"

        full_params = build_params("orfs", schema, overrides)
        full_params, notes = physical_profile.apply(full_params, "orfs", freq_ghz, locked_keys)
        config_text = render("orfs", full_params, schema)
        with open(os.path.join(target_dir, "config.mk"), "w") as f:
            f.write(config_text)
        return ORFS_PATH, notes


def _safe_copy(src: str, dest: str):
    """shutil.copy but a no-op if src and dest already resolve to the same
    file, instead of raising SameFileError -- this is the normal case for
    any design already living in its expected search-root location."""
    if os.path.exists(dest) and os.path.samefile(src, dest):
        return
    shutil.copy(src, dest)


async def _send(websocket, type_: str, message: str):
    await websocket.send_text(json.dumps({"type": type_, "message": message}))


async def _send_json(websocket, type_: str, data: dict):
    """v3: structured companion to _send(). The UI used to reconstruct PPA
    numbers by regex-matching human-readable log strings like
    '-> Performance: 1.23 GHz' (fragile -- any wording change silently
    breaks the chart). This sends the real numbers as real JSON instead,
    keyed by `type_` so the client can dispatch on it directly."""
    await websocket.send_text(json.dumps({"type": type_, **data}))


async def _send_final(websocket, status: str):
    """Frontend checks BOTH data.status and data.message for the final
    event (see index.html) -- send both so the success banner actually
    fires regardless of which field it ends up reading."""
    await websocket.send_text(json.dumps({"type": "final", "status": status, "message": status}))


def build_power_analysis_tcl(orfs_path: str, top_module: str, synth_netlist: str,
                              sdc_path: str, saif_path: str | None = None,
                              vcd_path: str | None = None, corner: str = "typical") -> str:
    """Generates a standalone OpenSTA/OpenROAD Tcl script for a pre-layout
    (post-synthesis) power estimate -- the fast path used for design-space
    exploration (`synth_power_only` resource mode), not a post-route
    signoff number.

    ---------------------------------------------------------------------
    WHAT THIS DOES AND DOESN'T COVER (read this before trusting a number)
    ---------------------------------------------------------------------
    Covers:
      - Internal, switching, and leakage power broken out by cell group
        (Sequential / Combinational / Macro / Pad), matching OpenSTA's
        standard `report_power` table.
      - Real switching-activity annotation from a SAIF or VCD file when
        one is supplied (SAIF preferred when both exist -- it's smaller
        and purpose-built for power analysis; a VCD works too, just
        larger). `report_units` is called first specifically so every
        report from this script is self-documenting about the units its
        numbers are in -- an unlabeled power number is not a usable
        number, full stop.

    Does NOT cover (this is the "estimate" in "power estimate"):
      - Real parasitics. This reads the pre-layout synthesized netlist,
        not a placed-and-routed one -- there is no SPEF here, so
        interconnect capacitance is estimated from wire-load models or
        similar, not measured from real layout. Post-route power from
        real parasitics is a materially different (usually higher, and
        more accurate) number.
      - Multi-corner analysis. This runs a single corner (see `corner`,
        currently informational only -- OpenSTA's corner-specific power
        flags depend on how your liberty/corner setup is structured, so
        wire this up against YOUR platform's actual multi-corner setup
        before trusting it for anything beyond a single nominal-corner
        estimate; don't take that as done just because the parameter
        exists).
      - Real signoff power. If you need that, it's what a full post-route
        ORFS/OpenLane flow's own report_power step already produces --
        this script is specifically the fast estimate Wakeel runs BEFORE
        committing to a full flow run, not a replacement for it.

    If neither a SAIF nor a VCD is supplied, this falls back to
    OpenSTA's default activity assumption (a fixed toggle rate applied
    uniformly), which is a well-known source of misleading power numbers
    -- rather than let that pass silently, the generated script prints an
    explicit WAKEEL_POWER_WARNING banner so it shows up in the run log,
    not just in a comment nobody reads.

    Assumes ASAP7 platform .lib files live under
    $ORFS_PATH/flow/platforms/asap7/**/*.lib -- matches the standard ORFS
    repo layout; verify against your checkout if this comes back empty.
    """
    platform_dir = os.path.join(orfs_path, "flow", "platforms", "asap7")
    lib_glob = os.path.join(platform_dir, "**", "*.lib").replace("\\", "/")

    if saif_path:
        activity_cmd = f'read_saif -scope "{top_module}" "{saif_path}"'
        activity_source = "SAIF"
    elif vcd_path:
        # NOTE: modeled on read_saif's -scope argument pattern (OpenSTA
        # keeps consistent argument conventions across its activity-file
        # readers) -- if your OpenSTA build's read_vcd signature differs,
        # adjust this one line; everything else in the script is
        # independent of which activity source was used.
        activity_cmd = f'read_vcd -scope "{top_module}" "{vcd_path}"'
        activity_source = "VCD"
    else:
        activity_cmd = (
            'puts "WAKEEL_POWER_WARNING: no SAIF or VCD supplied -- report_power below uses '
            'OpenSTA\'s default activity assumption (a fixed toggle rate applied uniformly across '
            'the design), NOT real switching behavior. Treat this number as a rough sanity check '
            'only, not a design decision input. Supply a SAIF (preferred) or VCD from an actual '
            'testbench run to get a meaningful estimate."'
        )
        activity_source = "NONE (default toggle rate)"

    return f"""# =============================================================
# WAKEEL pre-layout power estimate -- {top_module}, corner: {corner}
# Activity source: {activity_source}
# Generated by wakeel/orchestrator.py:build_power_analysis_tcl -- see that
# function's docstring for exactly what this number does and doesn't mean
# before using it for anything beyond quick design-space comparison.
# =============================================================

# self-documenting units -- printed before anything else so every number
# below this line in the log has a stated unit attached to it.
report_units

foreach lib_file [glob -nocomplain "{lib_glob}"] {{
    read_liberty $lib_file
}}
read_verilog "{synth_netlist}"
link_design {top_module}
read_sdc "{sdc_path}"
{activity_cmd}

report_checks -path_delay max -format summary

puts "WAKEEL_POWER_REPORT_START"
report_power
puts "WAKEEL_POWER_REPORT_END"
"""


# Backward-compatible alias -- earlier versions of this module exposed
# this function as build_power_estimate_tcl(); kept so any external
# script/notebook calling it directly doesn't break silently.
def build_power_estimate_tcl(orfs_path: str, top_module: str, synth_netlist: str,
                              sdc_path: str, saif_path: str | None = None) -> str:
    return build_power_analysis_tcl(orfs_path, top_module, synth_netlist, sdc_path, saif_path=saif_path)


# ==========================================================================
# Main entrypoint (same signature wakeel_api.py already calls)
# ==========================================================================

async def run_agentic_flow_stream(prompt: str, websocket, sweep_override: dict | None = None,
                                   max_retries: int = DEFAULT_MAX_RETRIES,
                                   max_sweep_points: int = MAX_SWEEP_POINTS,
                                   engine_override: str | None = None):
    """`sweep_override`, when given, is a dict in the shape
    build_sweep_clocks_ps() accepts ({"frequencies_ghz": [...]} or
    {"start_ghz","end_ghz","step_ghz"}) -- see wakeel_api.py, which reads
    it from an optional "sweep" key in the client's request. When present
    it REPLACES whatever frequencies offline_fallback_parser/local_llm
    would have parsed out of the free-text prompt, so there's exactly one
    source of truth for what gets swept, driven by explicit UI controls
    instead of regex guesses over prose.

    `engine_override` ("openlane" | "orfs" | None): same idea, for engine
    selection. Real incident this fixes: a prompt can correctly say "7nm"
    and still end up running on OpenLane/sky130, because DesignSearch.find()
    only treats an engine preference as a tiebreak -- if the requested
    engine has no matching design folder at all, it silently falls back to
    whichever engine DOES have one, with no warning. An explicit toggle in
    the UI doesn't fix that fallback by itself (the design still might not
    exist under the requested engine), but it does two things regex-parsing
    a prompt can't: it's unambiguous about what the user actually asked
    for, and it lets this function detect and LOUDLY report the mismatch
    instead of the user having to notice "Manufacturing Mode (Google/
    SkyWater 130nm)" scroll by in a log and realize on their own that
    something didn't do what they asked. See also the auto-stage step
    below, which tries to resolve the mismatch entirely rather than just
    report it, when RTL_SEARCH_ROOTS is configured.

    `max_retries`: self-heal attempts per sweep point before giving up on
    that frequency (clamped to ABSOLUTE_MAX_RETRIES).
    `max_sweep_points`: point-count cap for sweep_override (clamped to
    ABSOLUTE_MAX_SWEEP_POINTS) -- see build_sweep_clocks_ps.
    """
    max_retries = max(1, min(max_retries, ABSOLUTE_MAX_RETRIES))
    schema = ConfigSchema()
    kb = KnowledgeBase(schema)
    searcher = DesignSearch(OPENLANE_PATH, ORFS_PATH, EXTRA_SEARCH_ROOTS)

    try:
        if sweep_override:
            try:
                sweep_clocks_ps = build_sweep_clocks_ps(sweep_override, max_points=max_sweep_points)
            except SweepConfigError as e:
                await _send(websocket, "error", f"[SWEEP CONFIG] {e}")
                return
        else:
            sweep_clocks_ps = None

        raw_params = await resolve_params(prompt)
        engine = engine_override or raw_params.get("engine", "orfs")
        if engine_override and engine_override != raw_params.get("engine"):
            # the prompt's own words implied a different engine than the
            # explicit toggle selected -- the toggle wins (it's what the
            # user actually clicked), but resource_mode was computed
            # against the WRONG engine's conventions inside
            # offline_fallback_parser, so it must be re-derived here rather
            # than trusted from raw_params.
            resource_mode = _infer_resource_mode(prompt, engine)
        else:
            resource_mode = raw_params.get("resource_mode", "synth_power_only" if engine == "orfs" else "full")

        query = raw_params.get("design_query") or ""
        design_info = searcher.find(query, prefer_engine=engine)

        # v3: auto-stage -- if the requested engine has no matching design
        # folder (design_info is None entirely, or find() fell back to a
        # DIFFERENT engine than requested), try to resolve it by finding a
        # bare RTL file with a matching name somewhere in the user's own
        # configured project folders (RTL_SEARCH_ROOTS) and staging it into
        # a fresh folder under the REQUESTED engine's design root. This is
        # what turns the "you asked for ORFS but it ran on OpenLane"
        # surprise into something that just works, instead of merely
        # reporting the mismatch (see the ENGINE FALLBACK warning below,
        # which now only fires when this step doesn't apply or doesn't
        # find anything).
        if query and RTL_SEARCH_ROOTS and (design_info is None or design_info.engine != engine):
            rtl_path = find_loose_rtl(query, RTL_SEARCH_ROOTS)
            if rtl_path:
                target_root = (searcher.openlane_designs_root() if engine == "openlane"
                                else searcher.orfs_designs_root())
                staged_name = sanitize_identifier(os.path.splitext(os.path.basename(rtl_path))[0])
                try:
                    os.makedirs(target_root, exist_ok=True)
                    stage_design(target_root, staged_name, rtl_path)
                    await _send(websocket, "copilot",
                                f"[AUTO-STAGE] Found '{os.path.basename(rtl_path)}' under "
                                f"{os.path.dirname(rtl_path)} -- copied into the {engine} design root as "
                                f"'{staged_name}'. No config.tcl/config.mk existed for it yet, so a fresh "
                                f"one will be generated from the schema.")
                    restaged = searcher.find(staged_name, prefer_engine=engine)
                    if restaged and restaged.engine == engine:
                        design_info = restaged
                except FileExistsError as e:
                    await _send(websocket, "warning", f"[AUTO-STAGE] {e}")

        if design_info is None:
            await _send(websocket, "error",
                        f"No design matching '{raw_params.get('design_query')}' found under "
                        f"OpenLane, ORFS, or extra search roots. Registered roots: "
                        f"{OPENLANE_PATH}, {ORFS_PATH}, {EXTRA_SEARCH_ROOTS}"
                        + (f", RTL search roots: {RTL_SEARCH_ROOTS}" if RTL_SEARCH_ROOTS else ""))
            return

        # v3: the exact real incident this fixes -- a prompt/toggle can
        # correctly request one engine, but DesignSearch.find() only treats
        # `engine` as a tiebreak, not a requirement; if that engine has no
        # matching design folder at all, it silently returns whatever
        # engine DOES have one. Surface that loudly rather than let
        # "Manufacturing Mode (Google/SkyWater 130nm)" be the only signal
        # something didn't run where the user asked it to. Only reached
        # when the auto-stage step above either wasn't configured
        # (RTL_SEARCH_ROOTS empty) or didn't find a matching RTL file.
        if design_info.engine != engine:
            engine_label = {"openlane": "OpenLane/sky130 (130nm)", "orfs": "ORFS/ASAP7 (7nm)"}
            await _send(websocket, "warning",
                        f"[ENGINE FALLBACK] You requested {engine_label.get(engine, engine)}, but no "
                        f"'{design_info.name}' design folder exists under that engine's design root. "
                        f"Found it under {engine_label.get(design_info.engine, design_info.engine)} instead -- "
                        f"running there. To fix this permanently, add a design folder for "
                        f"'{design_info.name}' under the {engine} engine's design root"
                        + (", or register its project folder in WAKEEL_RTL_SEARCH_ROOTS so Wakeel can "
                           "auto-stage it next time." if not RTL_SEARCH_ROOTS else "."))
            engine = design_info.engine
            resource_mode = _infer_resource_mode(prompt, engine)

        # Sanitize before ANYTHING touches a shell command or filesystem path
        # built via string interpolation -- this is the fix for the
        # injection surface in the previous version.
        design_info.name = sanitize_identifier(design_info.name)
        design_info.top_module = sanitize_identifier(design_info.top_module, f"{design_info.name}_top")

        if not design_info.v_files:
            await _send(websocket, "error", f"Source files missing in {design_info.src_dir}.")
            return

        if design_info.match_score < 1.0:
            await _send(websocket, "copilot",
                        f"Fuzzy-matched '{raw_params.get('design_query')}' -> "
                        f"'{design_info.name}' (confidence {design_info.match_score:.0%})")

        # Seed from an existing config if one's already there, instead of
        # starting from bare schema defaults every run.
        seed = {}
        if design_info.existing_config_path:
            seed = searcher.read_existing_config(design_info.existing_config_path, design_info.engine)
            await _send(websocket, "copilot",
                        f"Found existing {os.path.basename(design_info.existing_config_path)} -- "
                        f"seeding {len(seed)} params from it.")

        base_params = {**seed, "core_util": raw_params.get("core_util"),
                       "place_density": raw_params.get("place_density"),
                       "fp_sizing": raw_params.get("fp_sizing"),
                       "die_area": raw_params.get("die_area")}
        base_params = {k: v for k, v in base_params.items() if v is not None}

        if sweep_clocks_ps is not None:
            clocks_to_sweep = sweep_clocks_ps
            await _send(websocket, "copilot",
                        f"[SWEEP] Using {len(clocks_to_sweep)} caller-specified frequency point(s) -- "
                        f"ignoring any GHz/MHz mentioned in the prompt text.")
        else:
            clocks_to_sweep = raw_params.get("clock_period_ps", [1000])

        # Restores the "Manufacturing Mode" / "Academic Mode" copilot text
        # index.html's chart-title switch is listening for.
        mode_label = ("Manufacturing Mode (Google/SkyWater 130nm)" if design_info.engine == "openlane"
                       else "Academic Mode (ASAP7 7nm FinFET)")
        await _send(websocket, "copilot",
                    f"Wakeel Target: {design_info.top_module} | Engine: {design_info.engine} "
                    f"| {mode_label} | KB rules loaded: {kb.stats()['total_rules']}")

        if design_info.engine == "orfs":
            if resource_mode == "synth_power_only":
                await _send(websocket, "copilot",
                            "[RESOURCE MODE] 7nm ORFS run: synthesis + pre-layout power estimate only "
                            "(detailed place/CTS/route skipped -- those stages are what actually need a "
                            "high core-count CPU like an i9/Ryzen 7+9; say 'full flow' or 'place and route' "
                            "in the prompt if you have the hardware and want the complete PnR run).")
            else:
                await _send(websocket, "warning",
                            "[RESOURCE MODE] Full ORFS place-and-route requested. This is genuinely CPU-heavy "
                            "(detailed placement/CTS/routing) -- expect a much longer run and higher memory use.")

        os.makedirs("ppa_reports", exist_ok=True)
        csv_file = os.path.join("ppa_reports", f"{design_info.top_module}_Sweep_Benchmark.csv")
        with open(csv_file, "w") as csv:
            csv.write("Target_Period(ps),Freq(GHz),Area(um2),Power(W),Mode,Status\n")

        # v3: serialize concurrent runs against the same design so two
        # in-flight requests can't race on _clean_run_dir / config writes.
        design_lock = _get_design_lock(design_info.engine, design_info.name)
        async with design_lock:
            for current_clock in clocks_to_sweep:
                freq_ghz = round(1000 / current_clock, 2)
                await _send(websocket, "phase", f"=== SWEEP: {freq_ghz} GHz ({current_clock} ps) ===")

                await _clean_run_dir(design_info)

                params = dict(base_params)
                success = False
                metrics = {"freq_ghz": None, "area_um2": None, "power_w": None}

                # v3: reset per sweep point. kb_locked_keys tells
                # physical_profile which of its owned keys a KB fix already
                # set THIS sweep point's retries (see physical_profile.apply);
                # applied_rule_ids is the oscillation guard -- a rule that
                # already fired for this frequency and didn't resolve the
                # failure won't be reapplied verbatim on a later attempt.
                kb_locked_keys: set = set()
                applied_rule_ids: set = set()

                for attempt in range(max_retries):
                    engine_path, profile_notes = write_physical_constraints(
                        design_info, params, schema, current_clock, locked_keys=kb_locked_keys)
                    for note in profile_notes:
                        await _send(websocket, "warning", note)
                    try:
                        cmd = await _build_run_command(design_info, engine_path, resource_mode)
                    except openlane_docker.OpenLaneDockerResolutionError as e:
                        await _send(websocket, "error", f"[DOCKER RESOLUTION FAILED] {e}")
                        break

                    log_buffer, returncode = await _run_and_stream(cmd, websocket)

                    if returncode == 0:
                        if design_info.engine == "orfs" and resource_mode == "synth_power_only":
                            metrics = await _run_power_estimate(design_info, engine_path, current_clock, websocket)
                        elif design_info.engine == "openlane":
                            metrics = metrics_parser.parse_openlane_metrics(design_info.design_dir)
                        metrics.setdefault("freq_ghz", freq_ghz)

                        with open(csv_file, "a") as csv:
                            csv.write(f"{current_clock},{freq_ghz},{metrics.get('area_um2','N/A')},"
                                      f"{metrics.get('power_w','N/A')},{resource_mode},SUCCESS\n")

                        stage_label = "SYNTH+POWER" if resource_mode == "synth_power_only" else "FULL PnR"
                        await _send(websocket, "success", f"[SWEEP OK: {stage_label}] {freq_ghz} GHz completed.")
                        if metrics.get("freq_ghz") is not None:
                            await _send(websocket, "success", f"-> Performance: {metrics['freq_ghz']:.2f} GHz")
                        if metrics.get("area_um2") is not None:
                            await _send(websocket, "success", f"-> Logic Area: {metrics['area_um2']:.2f} um2")
                        if metrics.get("power_w") is not None:
                            await _send(websocket, "success", f"-> Total Power: {metrics['power_w']:.6f} W")

                        # v3: structured companion to the log lines above --
                        # this, not string-parsed log text, is what the UI's
                        # results table/chart should read from.
                        await _send_json(websocket, "ppa_summary", {
                            "target_period_ps": current_clock,
                            "target_freq_ghz": freq_ghz,
                            "achieved_freq_ghz": metrics.get("freq_ghz"),
                            "area_um2": metrics.get("area_um2"),
                            "power_w": metrics.get("power_w"),
                            "mode": resource_mode,
                            "status": "SUCCESS",
                            "attempts": attempt + 1,
                        })
                        success = True
                        break
                    else:
                        if returncode == -9:
                            await _send(websocket, "error",
                                        f"[TIMEOUT] {freq_ghz} GHz attempt {attempt + 1} exceeded "
                                        f"{RUN_TIMEOUT_SECONDS}s and was killed.")
                        if attempt < max_retries - 1:
                            failure_text = "\n".join(log_buffer)
                            report_text = _read_signoff_reports(log_buffer, design_info)
                            if report_text:
                                failure_text += "\n\n=== SIGNOFF REPORT CONTENTS ===\n" + report_text
                            params, _, meta = await heal(failure_text, params, design_info.engine,
                                                          kb, schema, websocket, excluded_rule_ids=applied_rule_ids)
                            if meta["rule_id"]:
                                if meta["rule_id"] in applied_rule_ids:
                                    await _send(websocket, "warning",
                                                f"[OSCILLATION GUARD] Rule {meta['rule_id']} already applied for "
                                                f"{freq_ghz} GHz this sweep point -- treating as unresolved rather "
                                                f"than reapplying it verbatim.")
                                applied_rule_ids.add(meta["rule_id"])
                            owned = physical_profile.OWNED_KEYS.get(design_info.engine, set())
                            kb_locked_keys |= (meta["touched_keys"] & owned)
                        else:
                            with open(csv_file, "a") as csv:
                                csv.write(f"{current_clock},{freq_ghz},N/A,N/A,{resource_mode},FAILED\n")
                            await _send(websocket, "error",
                                        f"[SWEEP FAILED] {freq_ghz} GHz after {max_retries} attempt(s).")
                            await _send_json(websocket, "ppa_summary", {
                                "target_period_ps": current_clock,
                                "target_freq_ghz": freq_ghz,
                                "achieved_freq_ghz": None,
                                "area_um2": None,
                                "power_w": None,
                                "mode": resource_mode,
                                "status": "FAILED",
                                "attempts": max_retries,
                            })

        # v3: "parse the metrics.csv after a successful run" -- rather than
        # trusting only the in-memory `metrics` dicts collected along the
        # way, re-read the CSV file this run actually wrote to disk and
        # send it back as one authoritative, structured summary. This is
        # what the UI's results table renders from -- it's guaranteed to
        # match what's persisted in ppa_reports/, not just what happened to
        # still be in memory at the end of the loop.
        sweep_rows = _read_sweep_csv(csv_file)
        await _send_json(websocket, "sweep_summary", {
            "design": design_info.top_module,
            "engine": design_info.engine,
            "csv_path": csv_file,
            "rows": sweep_rows,
        })

        await _send_final(websocket, "SUCCESS")

    except Exception as e:
        await _send(websocket, "error", f"Global Fault: {e}")
    finally:
        await websocket.send_text(json.dumps({"type": "finished"}))
        try:
            await websocket.close()
        except Exception:
            pass


def _read_sweep_csv(csv_file: str) -> list[dict]:
    """Reads the sweep benchmark CSV this run just wrote back off disk and
    returns it as a list of dicts -- the authoritative post-run parse
    described in run_agentic_flow_stream's sweep_summary event. Never
    raises: a missing/malformed file returns an empty list rather than
    failing the whole run over a reporting step."""
    import csv as csv_module
    rows = []
    try:
        with open(csv_file, newline="") as f:
            for row in csv_module.DictReader(f):
                rows.append(row)
    except OSError:
        pass
    return rows


async def _clean_run_dir(design_info):
    if design_info.engine == "openlane":
        clean_cmd = f"rm -rf {shlex.quote(OPENLANE_PATH)}/designs/{shlex.quote(design_info.name)}/runs/*"
    else:
        top = shlex.quote(design_info.top_module)
        clean_cmd = (
            f"rm -rf {shlex.quote(ORFS_PATH)}/flow/results/asap7/{top} "
            f"{shlex.quote(ORFS_PATH)}/flow/logs/asap7/{top} "
            f"{shlex.quote(ORFS_PATH)}/flow/reports/asap7/{top} "
            f"{shlex.quote(ORFS_PATH)}/flow/objects/asap7/{top}"
        )
    proc = await asyncio.create_subprocess_shell(clean_cmd)
    await proc.wait()


async def _run_and_stream(cmd: str, websocket, timeout_seconds: int = RUN_TIMEOUT_SECONDS) -> tuple[list, int]:
    """v3: previously had no watchdog at all -- a hung container (a
    swallowed interactive prompt, a license-server deadlock, anything)
    blocked the orchestrator forever with nothing to time it out. Now
    tracks a deadline across the whole read loop: each stdout line read is
    individually bounded so a stall mid-stream is caught too, not just a
    process that never produces output at all. On timeout the process
    (and its process group, since `cmd` is a shell pipeline) is killed and
    this returns returncode -9, which the caller treats as an ordinary
    failed attempt -- it still gets a self-heal attempt / retry budget
    like any other failure, it just doesn't hang the whole run.

    Also handles asyncio.CancelledError (a user-initiated stop from the
    UI's Stop button, or the client disconnecting -- see wakeel_api.py's
    concurrent stop-listener) the same way: kill the whole process group,
    then re-raise so the cancellation actually propagates and the outer
    run stops, instead of a stray OpenLane/ORFS container continuing to
    run headless in the background after the UI says the run ended.
    """
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # own process group -- lets us kill the whole tree, not just the shell
    )

    def _kill_process_group():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except ProcessLookupError:
                pass

    log_buffer = deque(maxlen=2000)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    timed_out = False
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                timed_out = True
                break
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                timed_out = True
                break
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").strip()
            log_buffer.append(text)
            await _send(websocket, "log", text)
    except asyncio.CancelledError:
        _kill_process_group()
        await process.wait()
        raise

    if timed_out:
        await _send(websocket, "error",
                    f"[TIMEOUT] No progress within {timeout_seconds}s -- killing the run and its subprocesses.")
        _kill_process_group()
        await process.wait()
        return list(log_buffer), -9

    await process.wait()
    return list(log_buffer), process.returncode


def _read_signoff_reports(log_buffer, design_info) -> str:
    """BUGFIX (real architectural gap, found during a live debugging session):
    self-heal previously only ever saw OpenLane's terminal stdout, never the
    actual report files (drc.rpt, lvs.rpt, etc.) it writes to disk. The
    terminal only prints generic lines like "Total Number of violations is 2"
    -- the specific diagnostic text a KB rule needs to match (e.g. "nwell.4")
    only exists in the report file itself. This finds the run directory from
    the "Run Directory: /openlane/..." line OpenLane prints, translates the
    in-container path to the real host path (docker mounts OPENLANE_PATH at
    /openlane), and reads back whatever signoff report files it can find.
    Best-effort throughout: returns whatever it can read, never raises --
    a missing/unreadable report file should degrade to the old
    terminal-only behavior, not crash the run.
    """
    run_dir_container = None
    for line in log_buffer:
        m = re.search(r"Run Directory:\s*(/openlane/\S+)", line)
        if m:
            run_dir_container = m.group(1)
            break
    if not run_dir_container:
        return ""

    run_dir_host = run_dir_container.replace("/openlane", OPENLANE_PATH, 1)
    reports_dir = os.path.join(run_dir_host, "reports", "signoff")
    if not os.path.isdir(reports_dir):
        return ""

    collected = []
    for fname in sorted(os.listdir(reports_dir)):
        if fname.endswith((".rpt",)):
            fpath = os.path.join(reports_dir, fname)
            try:
                with open(fpath, errors="ignore") as f:
                    content = f.read().strip()
                if content:
                    collected.append(f"--- {fname} ---\n{content}")
            except OSError:
                continue
    return "\n\n".join(collected)


async def _run_power_estimate(design_info, orfs_path: str, clock_ps: float, websocket) -> dict:
    """Runs a standalone OpenROAD power-estimate pass on the just-synthesized
    netlist. Returns {'freq_ghz','area_um2','power_w'} with whatever it
    could actually parse -- None for anything the report format didn't
    match, never raises."""
    metrics = {"freq_ghz": None, "area_um2": None, "power_w": None}

    synth_log_path = metrics_parser.find_latest_orfs_log(orfs_path, design_info.top_module, "1_1_yosys")
    if synth_log_path:
        try:
            with open(synth_log_path) as f:
                metrics["area_um2"] = metrics_parser.parse_yosys_area(f.read())
        except OSError:
            pass

    synth_netlist = os.path.join(orfs_path, "flow", "results", "asap7",
                                  design_info.top_module, "base", "1_synth.v")
    sdc_path = os.path.join(design_info.design_dir, "constraint.sdc")
    if os.path.exists(synth_netlist):
        activity_note = ("SAIF" if design_info.saif_file else "VCD" if design_info.vcd_file
                          else "none (default toggle-rate estimate)")
        tcl_script = build_power_analysis_tcl(
            orfs_path, design_info.top_module, synth_netlist, sdc_path,
            saif_path=design_info.saif_file, vcd_path=design_info.vcd_file,
        )
        tcl_path = os.path.join(design_info.design_dir, "_wakeel_power_estimate.tcl")
        with open(tcl_path, "w") as f:
            f.write(tcl_script)

        await _send(websocket, "log",
                    f"[POWER-EST] Running pre-layout power estimate via OpenROAD (activity source: {activity_note})...")
        cmd = f"cd {shlex.quote(orfs_path)}/flow && ./util/docker_shell openroad -no_init -exit {shlex.quote(tcl_path)}"
        log_lines, returncode = await _run_and_stream(cmd, websocket)
        report_text = "\n".join(log_lines)
        metrics["power_w"] = metrics_parser.parse_openroad_power(report_text)
        if metrics["power_w"] is None:
            await _send(websocket, "warning",
                        "[POWER-EST] Could not parse a total-power line from the OpenROAD report -- "
                        "check the log above; the report_power table format may not match what this "
                        "parser expects for your OpenROAD version.")
    else:
        await _send(websocket, "warning",
                    f"[POWER-EST] Expected synthesized netlist not found at {synth_netlist} -- "
                    "skipping power estimate. This path is assumed from standard ORFS layout; "
                    "verify against your checkout if synth otherwise succeeded.")

    return metrics


async def _build_run_command(design_info, engine_path: str, resource_mode: str = "full") -> str:
    """
    BUGFIX (real incident): OpenLane 1.x (the version this project targets)
    runs entirely inside Docker -- `./flow.tcl` on the bare host isn't a
    supported invocation at all, even though it starts up far enough to
    print its own version banner before failing with "Container manifest
    not found". The correct invocation, per OpenLane's own Makefile, goes
    through `make mount`'s docker run (PDK/std-cell/arch/image flags all
    resolved by Python helper scripts inside the Makefile, not something
    safe to hand-reconstruct). Rather than guess at those flags, this now
    asks the Makefile directly (`make -n mount`, dry-run) and reuses its
    exact resolved command -- see wakeel/openlane_docker.py.
    """
    titanium_flags = ("export LD_BIND_NOW=1 && export OPENBLAS_CORETYPE=GENERIC && "
                       "export MKL_CBWR=COMPATIBLE && export GOTO_NUM_THREADS=1 && ")
    design = shlex.quote(design_info.name)

    if design_info.engine == "openlane":
        return await openlane_docker.resolve_flow_command(engine_path, design_info.name, titanium_flags)

    # ORFS: 'synth' target stops after synthesis (cheap); the bare default
    # target runs the full flow through detailed route + finish (expensive
    # -- this is the i9/Ryzen-class stage). Gate on resource_mode.
    make_target = "synth" if resource_mode == "synth_power_only" else ""
    return (f"cd {shlex.quote(engine_path)}/flow && {titanium_flags} "
            f"./util/docker_shell make {make_target} DESIGN_CONFIG=designs/asap7/{design}/config.mk < /dev/null")
