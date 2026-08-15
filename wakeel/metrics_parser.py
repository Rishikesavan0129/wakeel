"""
Parses real PPA numbers out of tool output instead of writing "N/A"
placeholders. Two code paths:

- OpenLane: reads the final metrics CSV a completed run writes.
- ORFS synth-only + power-estimate mode: reads yosys's synthesis stats log
  for area, and an OpenROAD `report_power` run for power.

Every regex here is marked with the format it assumes. Tool output format
drifts between versions -- if parsing comes back empty, functions return
None per-field rather than raising, so a run's success/fail status is never
gated on whether a report format matched.
"""
from __future__ import annotations
import glob
import os
import re


# ---- OpenLane (full flow) --------------------------------------------------

def parse_openlane_metrics(design_dir: str) -> dict:
    """OpenLane writes a `metrics.csv` (or `final_summary_report.csv`,
    depending on version) into the most recent runs/<tag>/reports/ dir.
    Assumes column names from the OpenLane 2.x metrics schema
    (design__instance__area, power__total, clock__period). If your OpenLane
    version uses different column names, this returns {} and the run still
    completes -- just without populated PPA numbers -- rather than failing.
    """
    result = {"freq_ghz": None, "area_um2": None, "power_w": None}
    runs_dir = os.path.join(design_dir, "runs")
    if not os.path.isdir(runs_dir):
        return result

    run_dirs = sorted(glob.glob(os.path.join(runs_dir, "*")), key=os.path.getmtime, reverse=True)
    if not run_dirs:
        return result
    latest_run = run_dirs[0]

    candidates = (
        glob.glob(os.path.join(latest_run, "reports", "metrics.csv"))
        + glob.glob(os.path.join(latest_run, "reports", "final_summary_report.csv"))
        + glob.glob(os.path.join(latest_run, "reports", "*.metrics.csv"))
    )
    if not candidates:
        return result

    try:
        with open(candidates[0]) as f:
            lines = [l.strip() for l in f if l.strip()]
        if len(lines) < 2:
            return result
        headers = lines[0].split(",")
        values = lines[-1].split(",")
        row = dict(zip(headers, values))

        for key in ("design__instance__area", "area_um^2", "DIE_AREA"):
            if key in row:
                result["area_um2"] = _to_float(row[key])
                break
        for key in ("power__total", "power_total_w", "Power"):
            if key in row:
                result["power_w"] = _to_float(row[key])
                break
        for key in ("clock__period", "CLOCK_PERIOD"):
            if key in row and _to_float(row[key]):
                result["freq_ghz"] = round(1000.0 / _to_float(row[key]), 3)
                break
    except (OSError, IndexError, ValueError):
        pass

    return result


# ---- ORFS synth-only + power-estimate mode --------------------------------

_YOSYS_AREA_RE = re.compile(r"Chip area for.*?:\s*([\d.]+)", re.IGNORECASE)
_OPENROAD_TOTAL_POWER_RE = re.compile(
    r"^Total\s+[\d.eE+\-]+\s+[\d.eE+\-]+\s+[\d.eE+\-]+\s+([\d.eE+\-]+)",
    re.MULTILINE,
)


def parse_yosys_area(synth_log_text: str) -> float | None:
    """Yosys's `stat` command (run automatically at the end of synthesis)
    prints a line like `Chip area for module '\\top': 1234.56`. Assumes
    default yosys stat output formatting."""
    m = _YOSYS_AREA_RE.search(synth_log_text)
    return _to_float(m.group(1)) if m else None


def parse_openroad_power(power_report_text: str) -> float | None:
    """OpenSTA/OpenROAD's `report_power` prints a table ending in a `Total`
    row where the 4th numeric column is total power in Watts. Assumes the
    standard OpenSTA report_power column layout (Internal, Switching,
    Leakage, Total)."""
    m = _OPENROAD_TOTAL_POWER_RE.search(power_report_text)
    return _to_float(m.group(1)) if m else None


def find_latest_orfs_log(orfs_path: str, top_module: str, stage: str) -> str | None:
    """ORFS writes per-stage logs to flow/logs/asap7/<design>/<stage>.log."""
    candidate = os.path.join(orfs_path, "flow", "logs", "asap7", top_module, f"{stage}.log")
    return candidate if os.path.exists(candidate) else None


def _to_float(s) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None
