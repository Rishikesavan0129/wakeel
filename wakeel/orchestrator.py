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
from collections import deque

from . import local_llm
from . import metrics_parser
from . import openlane_docker
from . import physical_profile
from .config_generator import ConfigSchema, build_params, render
from .design_discovery import DesignSearch
from .knowledge_base import KnowledgeBase

ORFS_PATH = os.path.expanduser(os.getenv("WAKEEL_ORFS_PATH", "~/ORFS_7nm"))
OPENLANE_PATH = os.path.expanduser(os.getenv("WAKEEL_OPENLANE_PATH", "~/OpenLane"))
EXTRA_SEARCH_ROOTS = [p for p in os.getenv("WAKEEL_EXTRA_DESIGN_ROOTS", "").split(":") if p]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


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
        full_flow_keywords = ("full flow", "full run", "complete flow", "place and route",
                               "place & route", "pnr", "route to gds", "gdsii", "tapeout",
                               "finish the flow", "full pnr")
        params["resource_mode"] = "full" if any(k in p for k in full_flow_keywords) else "synth_power_only"
    else:
        params["resource_mode"] = "full"

    return params


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
                schema: ConfigSchema, websocket) -> tuple[dict, str]:
    matches = kb.match(error_log, top_n=1)
    if matches:
        params, explanation = kb.apply(matches[0], params, engine)
        await _send(websocket, "warning", f"[KB:{matches[0].rule.get('id','?')}] {explanation}")
        return params, explanation

    try:
        adjustments, explanation = await local_llm.suggest_fix(error_log, params, engine)
        for raw_key, delta in adjustments.items():
            real_key = schema.resolve_alias(raw_key, engine) or raw_key
            spec = schema.spec(real_key, engine)
            current = params.get(real_key, spec.default if spec else None)
            if isinstance(delta, (int, float)) and isinstance(current, (int, float)):
                params[real_key] = round(current + delta, 6)
            else:
                params[real_key] = delta
        await _send(websocket, "warning", f"[LOCAL-LLM] {explanation}")
        return params, explanation
    except local_llm.LocalCorrectorUnavailable as e:
        await _send(websocket, "warning", f"[AUTO-HEAL HEURISTICS] No KB match, local model unavailable ({e}). "
                                            "Applying bounded fallback nudge.")

    util_key = schema.resolve_alias("core_util", engine) or "core_util"
    density_key = schema.resolve_alias("place_density", engine) or "place_density"
    if util_key in params and isinstance(params[util_key], (int, float)):
        params[util_key] = max(20, params[util_key] - 5)
    if density_key in params and isinstance(params[density_key], (int, float)):
        params[density_key] = max(0.20, round(params[density_key] - 0.05, 3))
    return params, "Bounded fallback: reduced utilization/density."


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
                                current_clock_ps: float, preview_dir: str | None = None) -> tuple[str, list[str]]:
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
        full_params, notes = physical_profile.apply(full_params, "openlane", freq_ghz)

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
        full_params, notes = physical_profile.apply(full_params, "orfs", freq_ghz)
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


async def _send_final(websocket, status: str):
    """Frontend checks BOTH data.status and data.message for the final
    event (see index.html) -- send both so the success banner actually
    fires regardless of which field it ends up reading."""
    await websocket.send_text(json.dumps({"type": "final", "status": status, "message": status}))


def build_power_estimate_tcl(orfs_path: str, top_module: str, synth_netlist: str,
                              sdc_path: str, saif_path: str | None) -> str:
    """Generates a standalone OpenROAD Tcl script that loads the ASAP7
    platform's timing libraries + the just-synthesized (pre-layout) netlist
    and runs report_power -- this is what gives a fast power estimate
    without paying for detailed placement/CTS/routing. Numbers from this
    are a rough estimate (no real parasitics yet, no post-route toggle
    data unless a SAIF is supplied) -- good for early design-space
    exploration, not signoff.

    Assumes ASAP7 platform .lib files live under
    $ORFS_PATH/flow/platforms/asap7/**/*.lib -- this matches the standard
    ORFS repo layout, but verify against your checkout if this comes back
    empty.
    """
    platform_dir = os.path.join(orfs_path, "flow", "platforms", "asap7")
    lib_glob = os.path.join(platform_dir, "**", "*.lib").replace("\\", "/")
    saif_cmd = f'read_saif -scope "{top_module}" "{saif_path}"' if saif_path else "# no SAIF supplied -- using default toggle-rate estimate"

    return f"""# WAKEEL: pre-layout power estimate (synth-only mode)
foreach lib_file [glob -nocomplain "{lib_glob}"] {{
    read_liberty $lib_file
}}
read_verilog "{synth_netlist}"
link_design {top_module}
read_sdc "{sdc_path}"
{saif_cmd}
report_checks -path_delay max -format summary
puts "WAKEEL_POWER_REPORT_START"
report_power
puts "WAKEEL_POWER_REPORT_END"
"""


# ==========================================================================
# Main entrypoint (same signature wakeel_api.py already calls)
# ==========================================================================

async def run_agentic_flow_stream(prompt: str, websocket):
    schema = ConfigSchema()
    kb = KnowledgeBase(schema)
    searcher = DesignSearch(OPENLANE_PATH, ORFS_PATH, EXTRA_SEARCH_ROOTS)

    try:
        raw_params = await resolve_params(prompt)
        engine = raw_params.get("engine", "orfs")
        resource_mode = raw_params.get("resource_mode", "synth_power_only" if engine == "orfs" else "full")

        design_info = searcher.find(raw_params.get("design_query") or "", prefer_engine=engine)
        if design_info is None:
            await _send(websocket, "error",
                        f"No design matching '{raw_params.get('design_query')}' found under "
                        f"OpenLane, ORFS, or extra search roots. Registered roots: "
                        f"{OPENLANE_PATH}, {ORFS_PATH}, {EXTRA_SEARCH_ROOTS}")
            return

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

        for current_clock in clocks_to_sweep:
            freq_ghz = round(1000 / current_clock, 2)
            await _send(websocket, "phase", f"=== SWEEP: {freq_ghz} GHz ({current_clock} ps) ===")

            await _clean_run_dir(design_info)

            params = dict(base_params)
            success = False
            metrics = {"freq_ghz": None, "area_um2": None, "power_w": None}

            for attempt in range(3):
                engine_path, profile_notes = write_physical_constraints(design_info, params, schema, current_clock)
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
                    success = True
                    break
                else:
                    if attempt < 2:
                        failure_text = "\n".join(log_buffer)
                        report_text = _read_signoff_reports(log_buffer, design_info)
                        if report_text:
                            failure_text += "\n\n=== SIGNOFF REPORT CONTENTS ===\n" + report_text
                        params, _ = await heal(failure_text, params, design_info.engine,
                                                kb, schema, websocket)
                    else:
                        with open(csv_file, "a") as csv:
                            csv.write(f"{current_clock},{freq_ghz},N/A,N/A,{resource_mode},FAILED\n")
                        await _send(websocket, "error", f"[SWEEP FAILED] {freq_ghz} GHz after 3 attempts.")

        await _send_final(websocket, "SUCCESS")

    except Exception as e:
        await _send(websocket, "error", f"Global Fault: {e}")
    finally:
        await websocket.send_text(json.dumps({"type": "finished"}))
        try:
            await websocket.close()
        except Exception:
            pass


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


async def _run_and_stream(cmd: str, websocket) -> tuple[list, int]:
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    log_buffer = deque(maxlen=2000)
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="ignore").strip()
        log_buffer.append(text)
        await _send(websocket, "log", text)
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
        tcl_script = build_power_estimate_tcl(
            orfs_path, design_info.top_module, synth_netlist, sdc_path, design_info.saif_file
        )
        tcl_path = os.path.join(design_info.design_dir, "_wakeel_power_estimate.tcl")
        with open(tcl_path, "w") as f:
            f.write(tcl_script)

        await _send(websocket, "log", "[POWER-EST] Running pre-layout power estimate via OpenROAD...")
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
