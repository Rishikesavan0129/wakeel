"""
Covers the two real bugs found during the v3 architecture review:

1. A rule adjustment written as int 0/1 for a boolean schema key used to
   fall into the numeric-additive branch instead of being treated as a
   SET -- a no-op when the current value already equalled the "delta".
2. match() had no confidence floor -- a single coincidental keyword hit
   scored the same authority as a clean multi-keyword match.

These use a small synthetic schema + rule set rather than the real
wakeel_knowledge_base.json, so they keep testing the ENGINE's behavior
even if the real KB content changes later.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wakeel.config_generator import ConfigSchema
from wakeel.knowledge_base import KnowledgeBase


def _make_schema(tmp_path):
    schema_doc = {
        "schema": {
            "openlane:TEST_BOOL_FLAG": {
                "key": "TEST_BOOL_FLAG", "tool": "openlane", "type": "bool",
                "default": True, "format": "plain", "category": "test", "description": "",
            },
            "openlane:TEST_NUMERIC": {
                "key": "TEST_NUMERIC", "tool": "openlane", "type": "int",
                "default": 30, "format": "plain", "category": "test", "description": "",
            },
        },
        "advisory_aliases": {},
    }
    path = os.path.join(tmp_path, "schema.json")
    with open(path, "w") as f:
        json.dump(schema_doc, f)
    return ConfigSchema(path)


def _make_kb(tmp_path, schema, rules):
    path = os.path.join(tmp_path, "kb.json")
    with open(path, "w") as f:
        json.dump({"rules": rules}, f)
    return KnowledgeBase(schema, path)


def test_int_zero_against_bool_schema_key_is_treated_as_set(tmp_path):
    """The exact real-world bug: a rule wants TEST_BOOL_FLAG forced off,
    written as int 0. Current value is True. Old code computed
    True + 0 = 1 (no-op, still truthy). New code must see the schema says
    'bool' and SET it to False regardless of the literal's Python type."""
    schema = _make_schema(tmp_path)
    kb = _make_kb(tmp_path, schema, [{
        "id": "T-001",
        "error_keywords": ["mismatch after optimization", "wrapper level cells"],
        "adjustments": {"TEST_BOOL_FLAG": 0},
        "explanation": "test rule",
    }])

    params = {"TEST_BOOL_FLAG": True}
    matches = kb.match("saw a mismatch after optimization in the wrapper level cells", top_n=1)
    assert matches, "expected a match"
    params, _, touched = kb.apply(matches[0], params, "openlane")

    assert params["TEST_BOOL_FLAG"] is False, "int 0 against a bool schema key must SET False, not no-op additively"
    assert "TEST_BOOL_FLAG" in touched


def test_numeric_delta_still_additive_for_real_numeric_keys(tmp_path):
    schema = _make_schema(tmp_path)
    kb = _make_kb(tmp_path, schema, [{
        "id": "T-002",
        "error_keywords": ["congestion detected"],
        "adjustments": {"TEST_NUMERIC": -5},
        "explanation": "reduce utilization",
    }])
    params = {"TEST_NUMERIC": 30}
    matches = kb.match("routing congestion detected in core area", top_n=1)
    params, _, touched = kb.apply(matches[0], params, "openlane")
    assert params["TEST_NUMERIC"] == 25
    assert "TEST_NUMERIC" in touched


def test_confidence_floor_drops_weak_matches(tmp_path):
    schema = _make_schema(tmp_path)
    kb = _make_kb(tmp_path, schema, [{
        "id": "T-003",
        "error_keywords": ["alpha", "beta", "gamma", "delta", "epsilon"],
        "adjustments": {},
        "explanation": "needs several simultaneous symptoms",
    }])
    # only 1 of 5 keywords present -> score 0.2, below MIN_MATCH_SCORE (0.34)
    matches = kb.match("something mentions alpha only", top_n=1)
    assert matches == [], "a single coincidental keyword hit must not surface as a confident match"


def test_confidence_floor_allows_strong_matches(tmp_path):
    schema = _make_schema(tmp_path)
    kb = _make_kb(tmp_path, schema, [{
        "id": "T-004",
        "error_keywords": ["alpha", "beta"],
        "adjustments": {},
        "explanation": "",
    }])
    matches = kb.match("saw both alpha and beta in the log", top_n=1)
    assert len(matches) == 1
    assert matches[0].score == 1.0


def test_exclude_ids_supports_oscillation_guard(tmp_path):
    schema = _make_schema(tmp_path)
    kb = _make_kb(tmp_path, schema, [{
        "id": "T-005",
        "error_keywords": ["alpha", "beta"],
        "adjustments": {},
        "explanation": "",
    }])
    matches = kb.match("alpha beta", top_n=1, exclude_ids={"T-005"})
    assert matches == [], "a rule id in exclude_ids must never be returned again"
