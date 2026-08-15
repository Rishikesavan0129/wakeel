"""
Dry-run harness -- exercises the full pipeline up to (but not including) the
actual OpenLane/ORFS subprocess call, so you can see exactly what Wakeel
would do before spending real CPU time on it.

Usage:
    python3 dry_run.py "run hafiz_core at 1 GHz on 7nm"
    python3 dry_run.py "do a full flow place and route on basir_rx at 500 MHz 7nm"
"""
import asyncio
import os
import sys

from wakeel.config_generator import ConfigSchema
from wakeel.design_discovery import DesignSearch
from wakeel.knowledge_base import KnowledgeBase
from wakeel.orchestrator import (
    OPENLANE_PATH, ORFS_PATH, EXTRA_SEARCH_ROOTS,
    resolve_params, sanitize_identifier, write_physical_constraints,
    _build_run_command,
)


class FakeWebSocket:
    """Swallows every _send() call and just prints it, instead of needing a
    real WebSocket connection for this dry run."""
    async def send_text(self, text):
        print(f"  [WS] {text}")


async def main(prompt: str):
    print(f"PROMPT: {prompt!r}\n")

    schema = ConfigSchema()
    kb = KnowledgeBase(schema)
    searcher = DesignSearch(OPENLANE_PATH, ORFS_PATH, EXTRA_SEARCH_ROOTS)

    raw_params = await resolve_params(prompt)
    engine = raw_params.get("engine", "orfs")
    resource_mode = raw_params.get("resource_mode", "synth_power_only" if engine == "orfs" else "full")

    print("=== PARSED PARAMS ===")
    for k, v in raw_params.items():
        print(f"  {k}: {v}")
    print(f"  resolved resource_mode: {resource_mode}\n")

    design_info = searcher.find(raw_params.get("design_query") or "", prefer_engine=engine)
    if design_info is None:
        print(f"NO DESIGN MATCH for '{raw_params.get('design_query')}'")
        print(f"Searched roots: {OPENLANE_PATH}, {ORFS_PATH}, {EXTRA_SEARCH_ROOTS}")
        return

    design_info.name = sanitize_identifier(design_info.name)
    design_info.top_module = sanitize_identifier(design_info.top_module, f"{design_info.name}_top")

    print("=== DESIGN MATCH ===")
    print(f"  name:        {design_info.name}")
    print(f"  engine:      {design_info.engine}")
    print(f"  top_module:  {design_info.top_module}")
    print(f"  match_score: {design_info.match_score:.2f}")
    print(f"  design_dir:  {design_info.design_dir}")
    print(f"  v_files:     {design_info.v_files}")
    print(f"  saif_file:   {design_info.saif_file}")
    print(f"  existing config: {design_info.existing_config_path}\n")

    if not design_info.v_files:
        print("WARNING: no source files found -- a real run would stop here with an error.\n")
        return

    print("=== WHAT WOULD RUN (not executed) ===")
    clocks = raw_params.get("clock_period_ps", [1000])
    for clock_ps in clocks:
        try:
            cmd = await _build_run_command(design_info, OPENLANE_PATH if engine == "openlane" else ORFS_PATH, resource_mode)
            print(f"  clock={clock_ps}ps -> {cmd}")
        except Exception as e:
            print(f"  clock={clock_ps}ps -> COULD NOT RESOLVE REAL COMMAND: {e}")
            print("  (this means a real run would fail at this exact step -- worth fixing before trying for real)")
    print()

    print("=== CONFIG FILE THAT WOULD BE WRITTEN ===")

    # BUGFIX: this harness was printing existing_config_path but never
    # actually reading it, unlike the real orchestrator.run_agentic_flow_stream
    # -- meaning a dry run for a design that already has a tuned config.tcl
    # was silently ignoring it and showing bare schema defaults instead of
    # what would really be written (existing settings preserved, only the
    # prompt's explicit overrides changed). Seed here too, for parity.
    seed = {}
    if design_info.existing_config_path:
        seed = searcher.read_existing_config(design_info.existing_config_path, design_info.engine)
        print(f"(seeding {len(seed)} params from existing {design_info.existing_config_path})\n")
    else:
        print("(no existing config found -- writing from schema defaults)\n")

    base_params = {**seed, **{k: v for k, v in {
        "core_util": raw_params.get("core_util"),
        "place_density": raw_params.get("place_density"),
        "fp_sizing": raw_params.get("fp_sizing"),
        "die_area": raw_params.get("die_area"),
    }.items() if v is not None}}

    # SAFETY FIX: previously this wrote straight into the real design's
    # config.tcl/config.mk -- meaning every "dry run" permanently
    # overwrote whatever was there before, no backup, no way back. That's
    # what caused a real incident where an existing hafiz_core config got
    # silently clobbered and we lost the ability to tell what its original
    # PDK/STD_CELL_LIBRARY settings (if any) actually were. Now every
    # preview goes into ./wakeel_dry_run_previews/<design>/ instead --
    # the real design directory is never touched by this script, full stop.
    preview_dir = os.path.join("wakeel_dry_run_previews", design_info.name)
    engine_path, profile_notes = write_physical_constraints(
        design_info, base_params, schema, clocks[0], preview_dir=preview_dir
    )
    if profile_notes:
        print("=== FREQUENCY-AWARE PROFILE ADJUSTMENTS ===")
        for note in profile_notes:
            print(f"  {note}")
        print()
    config_path = (f"{preview_dir}/config.tcl" if engine == "openlane"
                    else f"{preview_dir}/config.mk")
    with open(config_path) as f:
        print(f.read())

    print(f"\nPreview written to: {config_path}")
    print(f"(the REAL {design_info.design_dir} was NOT touched)")
    print("Nothing was executed against OpenLane/ORFS. Review the config above, then run for real.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 dry_run.py \"<your prompt>\"")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
