"""
Design discovery: turns a loosely-specified name from a prompt ("run hafiz
project") into a concrete design directory, its source files, and any
existing config it already has -- searched across OpenLane, ORFS, and any
extra roots you register, instead of requiring an exact folder-name match.
"""
from __future__ import annotations
import difflib
import glob
import os
import re
import shutil
from dataclasses import dataclass, field


@dataclass
class DesignInfo:
    name: str                  # matched folder name
    engine: str                 # 'openlane' | 'orfs'
    root: str                   # engine's design root that contains it
    design_dir: str             # full path to the design folder
    src_dir: str                # full path to its src/ folder
    v_files: list = field(default_factory=list)
    saif_file: str | None = None
    vcd_file: str | None = None
    top_module: str | None = None
    existing_config_path: str | None = None  # config.tcl or config.mk, if present
    match_score: float = 1.0    # 1.0 = exact match, lower = fuzzy


class DesignSearch:
    def __init__(self, openlane_path: str, orfs_path: str, extra_roots: list[str] | None = None):
        self.openlane_path = openlane_path
        self.orfs_path = orfs_path
        # extra_roots: any additional folders to search (e.g. a personal
        # projects directory outside the two standard tool trees). Each
        # entry is treated as an ORFS-style OR OpenLane-style root
        # depending on whether it contains a config.tcl or config.mk in
        # its subfolders -- auto-detected per-candidate below.
        self.extra_roots = extra_roots or []

    def _openlane_designs_root(self) -> str:
        return os.path.join(self.openlane_path, "designs")

    def _orfs_designs_root(self) -> str:
        return os.path.join(self.orfs_path, "flow", "designs", "asap7")

    # Public accessors for the two canonical roots -- used by
    # orchestrator.py's auto-stage path (see stage_design() below) so it
    # doesn't reach into "private"-by-convention methods from outside the
    # class.
    def openlane_designs_root(self) -> str:
        return self._openlane_designs_root()

    def orfs_designs_root(self) -> str:
        return self._orfs_designs_root()

    def _candidate_roots(self) -> list[tuple[str, str]]:
        roots = [
            ("openlane", self._openlane_designs_root()),
            ("orfs", self._orfs_designs_root()),
        ]
        for extra in self.extra_roots:
            has_mk = glob.glob(os.path.join(extra, "*", "config.mk"))
            engine = "orfs" if has_mk else "openlane"
            roots.append((engine, extra))
        return roots

    def list_all_designs(self) -> list[tuple[str, str, str]]:
        """(engine, root, folder_name) for every design folder found."""
        found = []
        for engine, root in self._candidate_roots():
            if not os.path.isdir(root):
                continue
            for entry in sorted(os.listdir(root)):
                full = os.path.join(root, entry)
                if os.path.isdir(full):
                    found.append((engine, root, entry))
        return found

    def find(self, query: str, prefer_engine: str | None = None) -> DesignInfo | None:
        """Fuzzy-match `query` (a design name pulled out of a prompt, which
        may be misspelled, partial, or use different casing/underscores)
        against every known design folder, across every registered root."""
        all_designs = self.list_all_designs()
        if not all_designs:
            return None

        query_norm = self._norm(query)

        exact = [d for d in all_designs if self._norm(d[2]) == query_norm]
        if exact:
            engine, root, name = self._pick(exact, prefer_engine)
            return self._build(engine, root, name, score=1.0)

        substr = [d for d in all_designs
                  if query_norm in self._norm(d[2]) or self._norm(d[2]) in query_norm]
        if substr:
            # BUGFIX: multiple folders can legitimately satisfy "substring
            # of each other" for the same query (e.g. 'hafiz soc' matches
            # both 'HAFIZ' and 'hafiz_soc_top'). Previously this just took
            # whichever came first in directory-listing order -- which,
            # because uppercase sorts before lowercase, silently biased
            # toward all-caps folder names regardless of actual fit. Now
            # ranked by SequenceMatcher closeness, same scoring the fuzzy
            # tier below already uses, so the more specific/closer name
            # wins instead of whichever happened to sort first.
            def _closeness(d):
                name_norm = self._norm(d[2])
                ratio = difflib.SequenceMatcher(None, query_norm, name_norm).ratio()
                engine_bonus = 0.001 if (prefer_engine and d[0] == prefer_engine) else 0.0
                return ratio + engine_bonus

            substr.sort(key=_closeness, reverse=True)
            engine, root, name = substr[0]
            score = difflib.SequenceMatcher(None, query_norm, self._norm(name)).ratio()
            return self._build(engine, root, name, score=max(score, 0.85))

        names = [d[2] for d in all_designs]
        close = difflib.get_close_matches(query, names, n=3, cutoff=0.5)
        if close:
            best_name = close[0]
            score = difflib.SequenceMatcher(None, query_norm, self._norm(best_name)).ratio()
            candidates = [d for d in all_designs if d[2] == best_name]
            engine, root, name = self._pick(candidates, prefer_engine)
            return self._build(engine, root, name, score=score)

        return None

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    @staticmethod
    def _pick(candidates: list[tuple[str, str, str]], prefer_engine: str | None):
        if prefer_engine:
            for c in candidates:
                if c[0] == prefer_engine:
                    return c
        return candidates[0]

    def _build(self, engine: str, root: str, name: str, score: float) -> DesignInfo:
        design_dir = os.path.join(root, name)
        src_dir = os.path.join(design_dir, "src")
        v_files = sorted(
            glob.glob(os.path.join(src_dir, "*.v")) + glob.glob(os.path.join(src_dir, "*.sv"))
        )
        saif_matches = glob.glob(os.path.join(design_dir, "**", "*.saif"), recursive=True)
        saif_file = saif_matches[0] if saif_matches else None
        # v3: same discovery pattern for VCD activity dumps -- SAIF is
        # preferred when both exist (smaller, purpose-built for power
        # analysis; see build_power_analysis_tcl's docstring), but a VCD is
        # a perfectly valid activity source and shouldn't be ignored just
        # because Wakeel only used to look for SAIF.
        vcd_matches = glob.glob(os.path.join(design_dir, "**", "*.vcd"), recursive=True)
        vcd_file = vcd_matches[0] if vcd_matches else None

        existing_config = None
        candidate = os.path.join(design_dir, "config.tcl" if engine == "openlane" else "config.mk")
        if os.path.exists(candidate):
            existing_config = candidate

        top_module = self.discover_top_module(v_files, name) if v_files else None

        return DesignInfo(
            name=name, engine=engine, root=root, design_dir=design_dir, src_dir=src_dir,
            v_files=v_files, saif_file=saif_file, vcd_file=vcd_file, top_module=top_module,
            existing_config_path=existing_config, match_score=score,
        )

    @staticmethod
    def discover_top_module(v_files: list[str], design_folder: str) -> str:
        for f_path in v_files:
            try:
                with open(f_path) as f:
                    content = f.read()
                for match in re.finditer(r"module\s+([a-zA-Z0-9_]+)", content):
                    found = match.group(1)
                    if found.endswith("_top") or found == design_folder:
                        return found
            except OSError:
                continue
        return f"{design_folder}_top"

    @staticmethod
    def read_existing_config(path: str, engine: str) -> dict:
        """Parse an existing config.tcl/config.mk into a flat {KEY: value}
        dict of strings, so a re-run can start from what's already there
        instead of the bare schema defaults. Best-effort text parse, not a
        full Tcl/Make interpreter -- good enough for the flat KEY=value
        style both OpenLane and ORFS configs are written in."""
        params = {}
        if not path or not os.path.exists(path):
            return params
        with open(path) as f:
            text = f.read()

        if engine == "openlane":
            for m in re.finditer(r'set\s+::env\((\w+)\)\s+(.+)', text):
                key, val = m.group(1), m.group(2).strip()
                params[key] = val.strip('"')
        else:
            for m in re.finditer(r'export\s+(\w+)\s*=\s*(.+)', text):
                key, val = m.group(1), m.group(2).strip()
                params[key] = val

        return params


# ==========================================================================
# Loose-RTL auto-discovery + staging (v3)
# ==========================================================================
# Real incident this addresses: a design can exist as source files under a
# personal project folder -- never organized into either engine's proper
# design-folder layout at all -- and DesignSearch.find() above only ever
# looks inside the two canonical tool roots plus explicitly registered
# extra_roots (each of which is still expected to look like a real design
# folder, with a src/ dir and optionally an existing config). This is a
# SEPARATE, narrower search: scanning a short, user-specified list of
# project folders for a bare .v/.sv file matching a query by name, with no
# expectation of any design-folder structure around it at all.
#
# Deliberately NOT a whole-filesystem crawl (not even just $HOME) -- an
# unbounded search is slow, and on a real WSL/Linux box will walk into
# unrelated tool caches, node_modules trees, and (worse) /mnt/c, none of
# which should be silently scanned just because a design name didn't
# resolve. The caller passes an explicit list (WAKEEL_RTL_SEARCH_ROOTS in
# orchestrator.py) -- the user's own choice of "these are my project
# folders", not a guess Wakeel makes on its own.

_RTL_SCAN_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                        ".ciel", "runs", "results", "tmp", ".tox"}
_RTL_SCAN_FILE_CAP = 20000  # safety cap even within an explicit root list


def find_loose_rtl(query: str, search_roots: list[str]) -> str | None:
    """Best-effort search for a standalone .v/.sv file whose filename
    (minus extension) matches `query`, across `search_roots` only -- see
    the module-level note above for why this is intentionally bounded.
    Returns the single best-matching file's absolute path, or None if
    nothing in the given roots matches closely enough.
    """
    query_norm = DesignSearch._norm(query)
    if not query_norm:
        return None

    candidates: list[tuple[float, str]] = []
    scanned = 0
    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _RTL_SCAN_SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                if not (fname.endswith(".v") or fname.endswith(".sv")):
                    continue
                scanned += 1
                if scanned > _RTL_SCAN_FILE_CAP:
                    return _best_rtl_candidate(candidates)
                stem_norm = DesignSearch._norm(os.path.splitext(fname)[0])
                if not stem_norm:
                    continue
                if stem_norm == query_norm or query_norm in stem_norm or stem_norm in query_norm:
                    ratio = difflib.SequenceMatcher(None, query_norm, stem_norm).ratio()
                    candidates.append((ratio, os.path.join(dirpath, fname)))

    return _best_rtl_candidate(candidates)


def _best_rtl_candidate(candidates: list[tuple[float, str]]) -> str | None:
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def stage_design(engine_root: str, name: str, rtl_path: str) -> str:
    """Copies a loose RTL file found via find_loose_rtl() into a proper
    <engine_root>/<name>/src/ folder, so the NEXT DesignSearch.find() call
    picks it up exactly like any other design folder -- no existing config
    is written here, so the normal schema-driven config generation runs
    fresh for it, same as any brand-new design.

    Copies the file (never references the original in place) -- so a run
    can never mutate or depend on something living outside Wakeel's own
    working tree. Refuses outright if a folder already exists for `name`
    under this engine root, rather than merging into it, since silently
    writing into a folder that might already hold something unrelated is
    exactly the kind of surprise this project has been trying to remove.

    Returns the design_dir it created.
    """
    design_dir = os.path.join(engine_root, name)
    if os.path.exists(design_dir):
        raise FileExistsError(
            f"'{design_dir}' already exists -- refusing to auto-stage into it. "
            f"(If this is stale, remove it manually first; Wakeel won't do that for you.)"
        )
    src_dir = os.path.join(design_dir, "src")
    os.makedirs(src_dir, exist_ok=False)
    dest = os.path.join(src_dir, os.path.basename(rtl_path))
    shutil.copy2(rtl_path, dest)
    return design_dir
