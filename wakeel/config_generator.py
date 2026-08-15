"""
Schema-driven config.tcl / config.mk generator.

Design goal: adding support for a new OpenLane or ORFS parameter should be a
one-line JSON edit in config_schema.json, never a Python change. This module
only knows how to *render* whatever the schema + params dict hand it -- it
has zero hardcoded knowledge of specific PDK variables.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Any

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "config_schema.json")


class SchemaError(Exception):
    pass


@dataclass
class ParamSpec:
    key: str
    tool: str
    type: str
    default: Any
    format: str
    category: str
    description: str
    advisory: bool = False
    maps_to: dict | None = None


class ConfigSchema:
    """Loads config_schema.json and exposes lookups by tool.

    BUGFIX: internal storage is now keyed by "tool:KEY" composite strings,
    not bare KEY. The original flat-dict design let identically-named
    parameters that exist in both OpenLane and ORFS (DESIGN_NAME,
    CLOCK_PERIOD, VERILOG_FILES, SDC_FILE, CLOCK_PORT, SYNTH_MAX_FANOUT,
    SYNTH_FLAT_TOP, VERILATOR_RELAX) silently clobber each other at load
    time -- whichever tool's block was defined last in the schema file won,
    and the other tool's entry for that name simply didn't exist. Composite
    keys make that collision structurally impossible. External callers are
    unaffected: they still pass the bare name plus a tool, same as before.
    """

    def __init__(self, path: str = _SCHEMA_PATH):
        with open(path) as f:
            raw = json.load(f)
        self._by_composite: dict[str, ParamSpec] = {}
        for composite, v in raw["schema"].items():
            bare_key = v.get("key", composite.split(":", 1)[-1])
            self._by_composite[composite] = ParamSpec(key=bare_key, **{k: val for k, val in v.items() if k != "key"})
        self.advisory_aliases: dict[str, dict] = raw["advisory_aliases"]

    @staticmethod
    def _composite(key: str, tool: str) -> str:
        return f"{tool}:{key}"

    def for_tool(self, tool: str) -> dict[str, ParamSpec]:
        return {v.key: v for v in self._by_composite.values() if v.tool == tool}

    def defaults(self, tool: str) -> dict:
        return {k: v.default for k, v in self.for_tool(tool).items() if v.default is not None}

    def resolve_alias(self, name: str, tool: str) -> str | None:
        """Map an advisory/conceptual KB key (e.g. 'core_util') to the real
        schema key for a given tool (e.g. 'FP_CORE_UTIL'). Returns None if
        `name` isn't an alias (caller should then check it's a direct key)."""
        entry = self.advisory_aliases.get(name)
        if entry is None:
            return None
        return entry.get(tool)

    def spec(self, key: str, tool: str) -> ParamSpec | None:
        """Tool is now required -- a bare key alone is ambiguous whenever
        the same name exists for both OpenLane and ORFS (see class
        docstring). Every call site in this package already knows which
        tool/engine it's operating on, so this doesn't add real friction,
        just removes a footgun."""
        return self._by_composite.get(self._composite(key, tool))

    def add_or_update(self, key: str, tool: str, type_: str, default: Any,
                       format_: str, category: str = "custom",
                       description: str = "", persist: bool = False):
        """Register a new parameter at runtime (e.g. discovered from an
        existing project's config file that uses a var not yet in the
        schema). If persist=True, writes it back to config_schema.json so
        it's known permanently -- this is the 'dynamically expandable' path."""
        self._by_composite[self._composite(key, tool)] = ParamSpec(
            key, tool, type_, default, format_, category, description
        )
        if persist:
            self._save()

    def _save(self):
        schema = {
            composite: dict(key=v.key, tool=v.tool, type=v.type, default=v.default, format=v.format,
                             category=v.category, description=v.description,
                             advisory=v.advisory, maps_to=v.maps_to)
            for composite, v in self._by_composite.items()
        }
        with open(_SCHEMA_PATH, "w") as f:
            json.dump({"schema": schema, "advisory_aliases": self.advisory_aliases}, f,
                      indent=2, sort_keys=True)


def _fmt_tcl_value(type_: str, value: Any) -> str:
    if type_ == "bool":
        return "1" if value else "0"
    if type_ in ("int", "float"):
        return str(value)
    if type_ == "str" or type_ == "path":
        return f'"{value}"'
    return f'"{value}"'


def _fmt_mk_value(type_: str, value: Any) -> str:
    if type_ == "bool":
        return "1" if value else "0"
    return str(value)


def render(tool: str, params: dict, schema: ConfigSchema, extra_raw: str = "") -> str:
    """Render a full config.tcl (openlane) or config.mk (orfs) body from a
    flat {key: value} params dict, validated/typed against the schema.
    Unknown keys are still emitted (best-effort str()) with a WARN comment
    instead of being silently dropped -- new/experimental knobs shouldn't
    require a schema edit just to try them once.
    """
    lines = []
    header = "OPENLANE CONFIG.TCL" if tool == "openlane" else "ORFS CONFIG.MK"
    lines.append(f"# ===== WAKEEL GENERATED {header} (schema-driven, dynamically expandable) =====")

    for key, value in params.items():
        if value is None:
            continue
        spec = schema.spec(key, tool)
        if spec is None:
            lines.append(f"# WARN: '{key}' not in schema for tool={tool} -- emitted best-effort")
            if tool == "openlane":
                lines.append(f'set ::env({key}) "{value}"')
            else:
                lines.append(f"export {key} = {value}")
            continue

        if tool == "openlane":
            if spec.format == "tcl_raw":
                # value is expected to already be a valid Tcl expression, e.g.
                # a [glob ...] call built by design_discovery.
                lines.append(f"set ::env({key}) {value}")
            else:
                lines.append(f"set ::env({key}) {_fmt_tcl_value(spec.type, value)}")
        else:
            lines.append(f"export {key} = {_fmt_mk_value(spec.type, value)}")

    if extra_raw:
        lines.append("")
        lines.append("# ---- flow-specific extras (SAIF, macro placement, etc.) ----")
        lines.append(extra_raw)

    return "\n".join(lines) + "\n"


_TRUTHY = {"1", "true", "on", "yes", "enable", "enabled"}
_FALSY = {"0", "false", "off", "no", "disable", "disabled"}


def _coerce_value(raw, type_: str):
    """Coerce a value against its schema-declared type before it's stored
    in params. Exists specifically because read_existing_config() parses a
    config.tcl/config.mk as plain text -- every value that comes back is a
    Python str, including '0' and '1' for booleans. Python's bool('0') is
    True (non-empty string), so without this coercion, re-seeding from an
    existing config that has any DISABLED boolean silently FLIPS it to
    enabled on the next render -- a real, config-corrupting bug, not a
    theoretical one. This runs on every override regardless of source
    (prompt-derived, KB-adjusted, or seeded from an existing file), and is
    a no-op for values that are already the correct Python type.
    """
    if raw is None:
        return None
    if type_ == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            s = raw.strip().lower()
            if s in _TRUTHY:
                return True
            if s in _FALSY:
                return False
            # unrecognized string for a bool slot -- don't silently guess,
            # fall through to Python truthiness only as an absolute last
            # resort (empty string -> False, anything else -> True).
            return bool(s)
        return bool(raw)
    if type_ == "int":
        try:
            return int(float(raw))  # float() first so "1.0"-style strings work
        except (TypeError, ValueError):
            return raw
    if type_ == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    return raw  # str/path/tcl_glob -- already the right shape as text


def build_params(tool: str, schema: ConfigSchema, overrides: dict) -> dict:
    """Start from schema defaults for `tool`, then layer `overrides` on top.
    Overrides may use either the literal schema key (e.g. 'FP_CORE_UTIL') or
    an advisory alias (e.g. 'core_util') -- both resolve to the same slot.
    Every override is coerced against its schema type -- see _coerce_value
    for why that matters, not just tidiness."""
    params = schema.defaults(tool)
    for key, value in overrides.items():
        real_key = schema.resolve_alias(key, tool) or key
        spec = schema.spec(real_key, tool)
        params[real_key] = _coerce_value(value, spec.type) if spec else value
    return params
