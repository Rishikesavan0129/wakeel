"""
Frequency-aware physical profile.

Static config defaults can't be right for every target frequency at once --
area-optimized synthesis + resizer optimizations off is reasonable for a
relaxed 20 MHz target and actively wrong for an aggressive 1 GHz target on
the same node (wrong in the "will fail STA" sense, not just "suboptimal").
This module classifies how aggressive a requested clock period is relative
to the target node, and escalates synthesis strategy + resizer settings
accordingly -- instead of picking one static default and being wrong half
the time.

The frequency bands below are rule-of-thumb guardrails for triggering a
strategy change and a warning, NOT verified silicon physics for your exact
design. They're deliberately isolated in one small dict so they're easy to
tune against your own actual timing closure results as you gather them --
treat the numbers here as a starting guess, not gospel.
"""
from __future__ import annotations

# freq (GHz) at/below which the flow is in "comfortable" territory for a
# typical synthesizable digital design on this node/flow, and at/below which
# it's "aggressive" (past that: "extreme"). OpenLane/sky130-class numbers
# assume a standard-cell design with no hand-pipelining; ORFS/asap7-class
# numbers assume the same for the predictive PDK.
FREQUENCY_BANDS_GHZ = {
    "openlane": {"comfortable": 0.30, "aggressive": 0.60},
    "orfs": {"comfortable": 1.50, "aggressive": 2.50},
}


def classify(engine: str, freq_ghz: float) -> str:
    band = FREQUENCY_BANDS_GHZ.get(engine, FREQUENCY_BANDS_GHZ["openlane"])
    if freq_ghz <= band["comfortable"]:
        return "comfortable"
    if freq_ghz <= band["aggressive"]:
        return "aggressive"
    return "extreme"


def apply(params: dict, engine: str, freq_ghz: float) -> tuple[dict, list[str]]:
    """Returns (possibly-modified params, list of human-readable notes to
    surface to the user). Only touches keys that exist in `params`'/the
    engine's schema already -- callers apply this AFTER build_params() so
    every key it might set is already a legal schema key for that engine.

    BUGFIX: this now ALWAYS sets its owned keys (SYNTH_STRATEGY + the 4
    resizer flags) based on the current classification, for every tier
    including 'comfortable' -- not just for aggressive/extreme. The
    original version only touched these keys when escalating, and left
    them untouched otherwise. Combined with existing-config seeding, that
    made the result order-dependent: run an aggressive frequency once, and
    every SUBSEQUENT comfortable-frequency run on the same design would
    silently inherit the aggressive settings from disk, forever, until
    something else happened to reset them. Same prompt should produce the
    same config regardless of run history -- these 5 keys are now a pure
    function of (engine, freq_ghz), full stop.
    """
    tier = classify(engine, freq_ghz)
    notes = []

    if engine == "openlane":
        if tier == "comfortable":
            params["SYNTH_STRATEGY"] = "AREA 0"
            params["PL_RESIZER_TIMING_OPTIMIZATIONS"] = False
            params["PL_RESIZER_DESIGN_OPTIMIZATIONS"] = False
            params["GLB_RESIZER_TIMING_OPTIMIZATIONS"] = False
            params["GLB_RESIZER_DESIGN_OPTIMIZATIONS"] = False
            notes.append(
                f"[PHYSICAL PROFILE] {freq_ghz:.3f} GHz classified as 'comfortable' for OpenLane/sky130-class "
                f"flow -- set SYNTH_STRATEGY to 'AREA 0' and resizer optimizations off. This overrides whatever "
                f"was seeded from an existing config for these 5 keys specifically, so results stay reproducible "
                f"regardless of what a prior run at a different frequency left on disk."
            )
            return params, notes

        strategy = "DELAY 1" if tier == "extreme" else "DELAY 0"
        params["SYNTH_STRATEGY"] = strategy
        params["PL_RESIZER_TIMING_OPTIMIZATIONS"] = True
        params["PL_RESIZER_DESIGN_OPTIMIZATIONS"] = True
        params["GLB_RESIZER_TIMING_OPTIMIZATIONS"] = True
        params["GLB_RESIZER_DESIGN_OPTIMIZATIONS"] = True
        notes.append(
            f"[PHYSICAL PROFILE] {freq_ghz:.3f} GHz classified as '{tier}' for OpenLane/sky130-class flow -- "
            f"switched SYNTH_STRATEGY to '{strategy}' and enabled resizer timing/design optimizations "
            f"(were area-optimized/off by default, which fights a tight clock target)."
        )
        if tier == "extreme":
            band = FREQUENCY_BANDS_GHZ["openlane"]
            notes.append(
                f"[PHYSICAL PROFILE WARNING] {freq_ghz:.3f} GHz is well past this flow's typical comfortable "
                f"range (<= {band['comfortable']} GHz) for a standard-cell design with no custom pipelining. "
                f"Even with aggressive synthesis + resizer settings, expect real setup-timing violations without "
                f"design-level pipelining. This is a rule-of-thumb guardrail, not a guarantee either way -- "
                f"treat it as 'budget time for STA debugging', not 'this will definitely fail'."
            )

    elif engine == "orfs":
        # NOTE: the ORFS schema currently has no exposed equivalent to
        # SYNTH_STRATEGY or the resizer toggles -- ORFS's yosys/OpenROAD
        # invocation doesn't route through the same config-driven knobs
        # OpenLane exposes, at least not any I've verified against your
        # ORFS checkout. This can only warn for ORFS right now, not
        # actually adjust strategy -- flagged here rather than silently
        # pretending parity with the OpenLane branch.
        if tier != "comfortable":
            band = FREQUENCY_BANDS_GHZ["orfs"]
            notes.append(
                f"[PHYSICAL PROFILE WARNING] {freq_ghz:.3f} GHz classified as '{tier}' for ASAP7/ORFS "
                f"(comfortable <= {band['comfortable']} GHz). Unlike the OpenLane path, this flow doesn't yet "
                f"have a verified synthesis-strategy or resizer knob wired into the schema to auto-escalate -- "
                f"this is a warning only. If you hit setup violations, check ORFS's own SYNTH_STRATEGY-equivalent "
                f"and resizer flags manually; adding them to config_schema.json is the natural next step here."
            )

    return params, notes
