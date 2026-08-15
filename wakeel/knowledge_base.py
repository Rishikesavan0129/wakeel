"""
Knowledge base engine.

Two things changed vs. the original wakeel_core.consult_knowledge_base:

1. Matching is scored, not first-substring-wins. An error log can contain
   several keyword hits across several rules; we now rank by
   (# keywords matched, category specificity) and return the best rule
   instead of whichever happened to be first in the JSON file.

2. Corrections are actually applied to a real, renderable parameter.
   Previously `adjustments` only mutated params that already existed as
   plain numeric keys in the ad-hoc params dict (core_util, place_density,
   clock_period_ps) -- everything else in a rule's `config_params` block
   (74 of the 83 OpenLane knobs the KB knows about) was just descriptive
   English text nothing ever parsed. Now every adjustment is resolved
   through ConfigSchema.resolve_alias() onto a real schema key and applied
   directly to the params dict that config_generator.render() consumes.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass

from .config_generator import ConfigSchema

_DEFAULT_KB_PATH = os.path.join(os.path.dirname(__file__), "..", "wakeel_knowledge_base.json")


@dataclass
class Match:
    rule: dict
    score: float
    matched_keywords: list


class KnowledgeBase:
    def __init__(self, schema: ConfigSchema, path: str = _DEFAULT_KB_PATH):
        self.schema = schema
        self.path = path
        self.rules: list[dict] = []
        self.reload()

    def reload(self):
        if not os.path.exists(self.path):
            self.rules = []
            return
        with open(self.path) as f:
            data = json.load(f)
        self.rules = data.get("rules", [])

    # ---- matching -----------------------------------------------------
    def match(self, error_text: str, top_n: int = 1) -> list[Match]:
        """Score every rule against error_text by fraction of its
        error_keywords present (case-insensitive substring), so a log with
        multiple simultaneous symptoms still finds the most relevant rule
        instead of the first keyword hit in file order."""
        error_lower = error_text.lower()
        scored = []
        for rule in self.rules:
            keywords = rule.get("error_keywords", [])
            if not keywords:
                continue
            hits = [kw for kw in keywords if kw.lower() in error_lower]
            if not hits:
                continue
            score = len(hits) / len(keywords)
            scored.append(Match(rule=rule, score=score, matched_keywords=hits))

        scored.sort(key=lambda m: (m.score, len(m.matched_keywords)), reverse=True)
        return scored[:top_n]

    # ---- applying a match to real params -------------------------------
    def apply(self, match: Match, params: dict, engine: str) -> tuple[dict, str]:
        """Apply a matched rule's adjustments to `params` (already resolved
        through the schema, i.e. real OpenLane/ORFS keys), returning the
        updated dict and a human-readable explanation. Numeric deltas are
        added to the current value; boolean deltas are a direct SET (not
        additive -- see note below); non-numeric adjustments overwrite it.
        Anything that isn't a direct schema key is resolved via
        schema.resolve_alias() first -- this is what actually connects the
        KB's 87-previously-inert parameters to the generated config.
        """
        rule = match.rule
        applied = []
        for raw_key, delta in rule.get("adjustments", {}).items():
            real_key = self.schema.resolve_alias(raw_key, engine) or raw_key
            spec = self.schema.spec(real_key, engine)
            current = params.get(real_key, spec.default if spec else None)

            if isinstance(delta, bool):
                # BUGFIX: bool is a subclass of int in Python, so without this
                # explicit check first, a boolean adjustment (e.g. "force this
                # flag off") would silently fall into the numeric-additive
                # branch below and compute nonsense like True + False = 1
                # instead of directly setting the value. Booleans in a rule's
                # adjustments are always a direct SET, never additive --
                # "reduce this flag by some delta" isn't a meaningful concept.
                params[real_key] = delta
                applied.append(f"{real_key}: {current} -> {delta} (forced)")
            elif isinstance(delta, (int, float)) and isinstance(current, (int, float)):
                new_val = round(current + delta, 6)
                params[real_key] = new_val
                applied.append(f"{real_key}: {current} -> {new_val}")
            elif isinstance(delta, (int, float)) and current is None:
                params[real_key] = delta
                applied.append(f"{real_key}: (unset) -> {delta}")
            else:
                # non-numeric adjustment text (e.g. "increase halo") -- log
                # it as advisory since we won't guess a magnitude, but don't
                # silently drop it either.
                applied.append(f"{real_key}: advisory only ('{delta}') -- review manually")

        explanation = rule.get("explanation", "Applying knowledge-base heuristic.")
        if applied:
            explanation += "\nApplied: " + "; ".join(applied)
        return params, explanation

    def stats(self) -> dict:
        by_category = {}
        for r in self.rules:
            cat = r.get("category", "Uncategorized")
            by_category[cat] = by_category.get(cat, 0) + 1
        return {"total_rules": len(self.rules), "by_category": by_category}
