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

# The keys this module claims ownership of per engine -- kept as one
# explicit constant (rather than scattered string literals) so the
# orchestrator can tell, generically, when a KB self-heal rule has touched
# a key physical_profile would otherwise force back to its tier default on
# the next attempt. See `locked_keys` in apply() below.
OWNED_KEYS = {
    "openlane": {
        "SYNTH_STRATEGY",
        "PL_RESIZER_TIMING_OPTIMIZATIONS",
        "PL_RESIZER_DESIGN_OPTIMIZATIONS",
        "GLB_RESIZER_TIMING_OPTIMIZATIONS",
        "GLB_RESIZER_DESIGN_OPTIMIZATIONS",
    },
    # v3: ORFS previously had no real knob here at all -- only a warning.
    # SYNTH_MAX_FANOUT and SYNTH_FLAT_TOP are both real, schema-verified
    # ORFS keys (confirmed against config_schema.json) that genuinely
    # affect how hard yosys works to close timing at a tight target, so
    # this now gives ORFS actual parity instead of a permanent TODO.
    "orfs": {"SYNTH_MAX_FANOUT", "SYNTH_FLAT_TOP"},
}


def classify(engine: str, freq_ghz: float) -> str:
    band = FREQUENCY_BANDS_GHZ.get(engine, FREQUENCY_BANDS_GHZ["openlane"])
    if freq_ghz <= band["comfortable"]:
        return "comfortable"
    if freq_ghz <= band["aggressive"]:
        return "aggressive"
    return "extreme"


def apply(params: dict, engine: str, freq_ghz: float,
          locked_keys: set | None = None) -> tuple[dict, list[str]]:
    """Returns (possibly-modified params, list of human-readable notes to
    surface to the user). Only touches keys that exist in `params`'/the
    engine's schema already -- callers apply this AFTER build_params() so
    every key it might set is already a legal schema key for that engine.

    BUGFIX: this now ALWAYS sets its owned keys (SYNTH_STRATEGY + the 4
    resizer flags on OpenLane; SYNTH_MAX_FANOUT/SYNTH_FLAT_TOP on ORFS)
    based on the current classification, for every tier including
    'comfortable' -- not just for aggressive/extreme. The original version
    only touched these keys when escalating, and left them untouched
    otherwise. Combined with existing-config seeding, that made the result
    order-dependent: run an aggressive frequency once, and every
    SUBSEQUENT comfortable-frequency run on the same design would silently
    inherit the aggressive settings from disk, forever, until something
    else happened to reset them. Same prompt should produce the same
    config regardless of run history -- these keys are now a pure function
    of (engine, freq_ghz), full stop.

    `locked_keys` (v3): the set of OWNED_KEYS this call should NOT force,
    because a knowledge-base self-heal rule already set them deliberately
    for the CURRENT sweep point (same frequency, a later retry attempt).
    Without this, physical_profile and the KB fought over the same keys --
    physical_profile always won on the next attempt, silently discarding
    whatever fix the KB had just applied, because write_physical_constraints()
    (and therefore this function) reruns on every retry, not just once per
    sweep point. This does NOT weaken the original bugfix above: locked
    keys are still a pure function of the current sweep point's own
    history, not leftover state from a different frequency or a different
    design -- the orchestrator resets the lock set at the start of every
    new sweep point.
    """
    tier = classify(engine, freq_ghz)
    notes = []
    locked_keys = locked_keys or set()

    def _set(key: str, value):
        """Set an owned key unless the KB already claimed it this attempt."""
        if key in locked_keys:
            notes.append(
                f"[PHYSICAL PROFILE] Deferring to a knowledge-base fix already applied to {key} this "
                f"attempt -- not forcing it back to the '{tier}' tier default."
            )
            return
        params[key] = value

    if engine == "openlane":
        if tier == "comfortable":
            _set("SYNTH_STRATEGY", "AREA 0")
            _set("PL_RESIZER_TIMING_OPTIMIZATIONS", False)
            _set("PL_RESIZER_DESIGN_OPTIMIZATIONS", False)
            _set("GLB_RESIZER_TIMING_OPTIMIZATIONS", False)
            _set("GLB_RESIZER_DESIGN_OPTIMIZATIONS", False)
            notes.append(
                f"[PHYSICAL PROFILE] {freq_ghz:.3f} GHz classified as 'comfortable' for OpenLane/sky130-class "
                f"flow -- set SYNTH_STRATEGY to 'AREA 0' and resizer optimizations off. This overrides whatever "
                f"was seeded from an existing config for these 5 keys specifically, so results stay reproducible "
                f"regardless of what a prior run at a different frequency left on disk."
            )
            return params, notes

        strategy = "DELAY 1" if tier == "extreme" else "DELAY 0"
        _set("SYNTH_STRATEGY", strategy)
        _set("PL_RESIZER_TIMING_OPTIMIZATIONS", True)
        _set("PL_RESIZER_DESIGN_OPTIMIZATIONS", True)
        _set("GLB_RESIZER_TIMING_OPTIMIZATIONS", True)
        _set("GLB_RESIZER_DESIGN_OPTIMIZATIONS", True)
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
        # v3: previously warning-only (no verified knob). SYNTH_MAX_FANOUT
        # and SYNTH_FLAT_TOP are both real, schema-confirmed ORFS keys --
        # tightening max fanout is a standard lever for helping yosys/ABC
        # close timing at an aggressive target, and flattening the design
        # at the extreme tier removes hierarchy boundaries that can block
        # cross-module optimization. These are still rule-of-thumb
        # guardrails, not verified-against-silicon numbers -- tune them
        # against real timing closure results the same way the OpenLane
        # bands should be tuned.
        default_fanout = 20
        if tier == "comfortable":
            _set("SYNTH_MAX_FANOUT", default_fanout)
            _set("SYNTH_FLAT_TOP", False)
            notes.append(
                f"[PHYSICAL PROFILE] {freq_ghz:.3f} GHz classified as 'comfortable' for ASAP7/ORFS -- "
                f"SYNTH_MAX_FANOUT at the default ({default_fanout}), hierarchy flattening off."
            )
            return params, notes

        fanout = 12 if tier == "aggressive" else 8
        _set("SYNTH_MAX_FANOUT", fanout)
        _set("SYNTH_FLAT_TOP", tier == "extreme")
        notes.append(
            f"[PHYSICAL PROFILE] {freq_ghz:.3f} GHz classified as '{tier}' for ASAP7/ORFS -- tightened "
            f"SYNTH_MAX_FANOUT to {fanout}" + (" and flattened the top module" if tier == "extreme" else "") + "."
        )
        band = FREQUENCY_BANDS_GHZ["orfs"]
        if tier == "extreme":
            notes.append(
                f"[PHYSICAL PROFILE WARNING] {freq_ghz:.3f} GHz is well past this flow's typical comfortable "
                f"range (<= {band['comfortable']} GHz) on ASAP7. Fanout tightening and flattening help, but "
                f"without design-level pipelining, expect real setup-timing violations -- budget time for STA "
                f"debugging."
            )

    return params, notes
