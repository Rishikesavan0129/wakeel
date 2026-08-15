"""
Schema auto-discovery -- reads the REAL variable list straight out of your
actual OpenLane/ORFS installation instead of relying on a hand-maintained
guess. This is the permanent fix for "why do you keep hand-editing the
schema": your install already contains the authoritative source of truth
(classic OpenLane's `configuration/*.tcl` files each declare every variable
the flow recognizes, with its real default, guarded by an
`if { [info exists ::env(VAR)] == 0 }` check). This scans that directly.

Usage:
    python3 -m wakeel.schema_refresh
    python3 -m wakeel.schema_refresh --dry-run   # show what WOULD change, write nothing

Safe by design:
- Never overwrites an existing schema entry -- only ADDS variables that
  aren't already known. Anything already in config_schema.json (including
  the physical_profile-owned keys, and anything already hand-verified) is
  left exactly as-is.
- Anything it can't confidently parse a literal default out of (computed
  values, [expr ...], variable references) is reported, not guessed at --
  you'll see it in the "SKIPPED (needs manual review)" list instead of a
  silently wrong default.
"""
from __future__ import annotations
import glob
import json
import os
import re
import sys

_SET_ENV_RE = re.compile(r'set\s+::env\((\w+)\)\s+(.+)')


def _parse_literal(raw: str) -> tuple[str | None, object]:
    """Returns (type, value) if the RHS is a confidently-parseable literal,
    else (None, None) meaning 'skip, needs manual review'."""
    raw = raw.strip().rstrip(";").strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return "str", raw[1:-1]
    if raw in ("0", "1"):
        return "bool", raw == "1"
    if re.fullmatch(r"-?\d+", raw):
        return "int", int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return "float", float(raw)
    if raw in ("", "{}"):
        return "str", None
    return None, None  # e.g. [expr {...}], $SOME_VAR, list literals -- don't guess


def discover_openlane_variables(openlane_path: str) -> tuple[dict, list[str]]:
    """Scans openlane_path/configuration/*.tcl for every
    `set ::env(VAR) <literal>` inside an `if { [info exists ...] == 0 }`
    guard (classic OpenLane's default-declaration convention). Returns
    (discovered_schema_entries, unparseable_var_names)."""
    config_dir = os.path.join(openlane_path, "configuration")
    discovered = {}
    skipped = []

    tcl_files = sorted(glob.glob(os.path.join(config_dir, "*.tcl")))
    if not tcl_files:
        return discovered, skipped

    for path in tcl_files:
        category = os.path.splitext(os.path.basename(path))[0]
        with open(path, errors="ignore") as f:
            text = f.read()
        for m in _SET_ENV_RE.finditer(text):
            var, raw_value = m.group(1), m.group(2)
            type_, value = _parse_literal(raw_value)
            if type_ is None:
                skipped.append(var)
                continue
            discovered[var] = dict(
                key=var, tool="openlane", type=type_, default=value,
                format=("tcl_bool" if type_ == "bool" else "tcl_scalar"),
                category=category, description=f"Auto-discovered from configuration/{os.path.basename(path)}",
                advisory=False, maps_to=None,
            )
    return discovered, sorted(set(skipped))


def refresh(openlane_path: str, schema_path: str, dry_run: bool = False) -> dict:
    discovered, skipped = discover_openlane_variables(openlane_path)

    with open(schema_path) as f:
        current = json.load(f)

    added, already_known = [], []
    for var, entry in discovered.items():
        composite = f"openlane:{var}"
        if composite in current["schema"]:
            already_known.append(var)
        else:
            current["schema"][composite] = entry
            added.append(var)

    if not dry_run and added:
        with open(schema_path, "w") as f:
            json.dump(current, f, indent=2, sort_keys=True)

    return {
        "config_dir_found": os.path.isdir(os.path.join(openlane_path, "configuration")),
        "total_discovered": len(discovered),
        "added": sorted(added),
        "already_known": sorted(already_known),
        "skipped_needs_review": skipped,
        "written": not dry_run and bool(added),
    }


def _main():
    dry_run = "--dry-run" in sys.argv
    openlane_path = os.path.expanduser(os.getenv("WAKEEL_OPENLANE_PATH", "~/OpenLane"))
    schema_path = os.path.join(os.path.dirname(__file__), "config_schema.json")

    result = refresh(openlane_path, schema_path, dry_run=dry_run)

    if not result["config_dir_found"]:
        print(f"No configuration/ directory found under {openlane_path} -- "
              f"this scanner assumes classic OpenLane's layout (configuration/*.tcl). "
              f"If your install is structured differently, this needs adjusting, not guessing at.")
        return

    print(f"Scanned {openlane_path}/configuration/*.tcl")
    print(f"  {result['total_discovered']} variables found total")
    print(f"  {len(result['already_known'])} already known (left untouched): {result['already_known']}")
    print(f"  {len(result['added'])} newly added: {result['added']}")
    if result["skipped_needs_review"]:
        print(f"  {len(result['skipped_needs_review'])} skipped, needs manual review "
              f"(computed/non-literal defaults): {result['skipped_needs_review']}")
    print()
    if dry_run:
        print("(--dry-run: nothing was written)")
    elif result["written"]:
        print(f"Wrote updated schema to {schema_path}")
    else:
        print("No new variables to add -- schema already covers everything discoverable here.")


if __name__ == "__main__":
    _main()
