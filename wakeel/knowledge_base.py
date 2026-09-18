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
    # BUGFIX (v3): a rule that only shares 1 of e.g. 12 keywords with the
    # error log used to be applied with exactly as much authority as a
    # clean 5/5 hit -- match() had no floor, so a coincidental single-word
    # overlap could get treated as a confident diagnosis. Below this score,
    # match() now drops the candidate entirely so the caller falls through
    # to the local-model / bounded-fallback path instead of trusting a weak
    # guess. Kept as a class attribute (not a magic number inline) so a
    # caller or a test can override it deliberately.
    MIN_MATCH_SCORE = 0.34

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
    def match(self, error_text: str, top_n: int = 1, exclude_ids: set | None = None) -> list[Match]:
        """Score every rule against error_text by fraction of its
        error_keywords present (case-insensitive substring), so a log with
        multiple simultaneous symptoms still finds the most relevant rule
        instead of the first keyword hit in file order.

        `exclude_ids` skips rules already applied for this sweep point --
        used by the orchestrator's oscillation guard so a rule that already
        fired once and didn't fix the failure doesn't get reapplied
        (a no-op re-application, or worse, two rules undoing each other in
        a loop) on a later attempt.

        Matches scoring below MIN_MATCH_SCORE are dropped, not just ranked
        low -- see the class docstring on MIN_MATCH_SCORE.
        """
        error_lower = error_text.lower()
        exclude_ids = exclude_ids or set()
        scored = []
        for rule in self.rules:
            if rule.get("id") in exclude_ids:
                continue
            keywords = rule.get("error_keywords", [])
            if not keywords:
                continue
            hits = [kw for kw in keywords if kw.lower() in error_lower]
            if not hits:
                continue
            score = len(hits) / len(keywords)
            if score < self.MIN_MATCH_SCORE:
                continue
            scored.append(Match(rule=rule, score=score, matched_keywords=hits))

        scored.sort(key=lambda m: (m.score, len(m.matched_keywords)), reverse=True)
        return scored[:top_n]

    # ---- applying a match to real params -------------------------------
    def apply(self, match: Match, params: dict, engine: str) -> tuple[dict, str, set]:
        """Apply a matched rule's adjustments to `params` (already resolved
        through the schema, i.e. real OpenLane/ORFS keys), returning the
        updated dict, a human-readable explanation, and the set of real
        keys touched (so the caller can arbitrate ownership against
        physical_profile -- see orchestrator.py). Numeric deltas are added
        to the current value; boolean deltas are a direct SET (not
        additive -- see note below); non-numeric adjustments overwrite it.
        Anything that isn't a direct schema key is resolved via
        schema.resolve_alias() first -- this is what actually connects the
        KB's 87-previously-inert parameters to the generated config.
        """
        rule = match.rule
        applied = []
        touched_keys = set()
        for raw_key, delta in rule.get("adjustments", {}).items():
            real_key = self.schema.resolve_alias(raw_key, engine) or raw_key
            spec = self.schema.spec(real_key, engine)
            current = params.get(real_key, spec.default if spec else None)
            touched_keys.add(real_key)

            # BUGFIX (v3): the previous check was `isinstance(delta, bool)`,
            # which only caught a rule whose adjustments JSON literally used
            # `true`/`false`. Several real rules in the KB encode the same
            # boolean intent as `0`/`1` (a completely reasonable thing for a
            # human editing JSON to write) -- those silently skipped this
            # branch and fell into the numeric-additive one below, where
            # e.g. "turn this flag off" (delta=0) against a current value of
            # True computed `True + 0 = 1`, a no-op that logged as a
            # success. The authoritative signal for "is this a boolean SET"
            # is the schema's own declared type for the key, not the JSON
            # literal's Python type -- so resolve the schema spec first and
            # branch on THAT.
            if spec is not None and spec.type == "bool":
                new_val = bool(delta)
                params[real_key] = new_val
                applied.append(f"{real_key}: {current} -> {new_val} (forced)")
            elif isinstance(delta, bool):
                # No schema spec to confirm against (shouldn't normally
                # happen once resolve_alias works), but the literal is
                # still unambiguously a SET, not a delta.
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
                touched_keys.discard(real_key)  # nothing actually changed

        explanation = rule.get("explanation", "Applying knowledge-base heuristic.")
        if applied:
            explanation += "\nApplied: " + "; ".join(applied)
        return params, explanation, touched_keys

    def stats(self) -> dict:
        by_category = {}
        for r in self.rules:
            cat = r.get("category", "Uncategorized")
            by_category[cat] = by_category.get(cat, 0) + 1
        return {"total_rules": len(self.rules), "by_category": by_category}
