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

        existing_config = None
        candidate = os.path.join(design_dir, "config.tcl" if engine == "openlane" else "config.mk")
        if os.path.exists(candidate):
            existing_config = candidate

        top_module = self.discover_top_module(v_files, name) if v_files else None

        return DesignInfo(
            name=name, engine=engine, root=root, design_dir=design_dir, src_dir=src_dir,
            v_files=v_files, saif_file=saif_file, top_module=top_module,
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
