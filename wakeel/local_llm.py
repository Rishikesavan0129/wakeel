"""
Optional local corrector -- the Gemini replacement.

Design intent: Gemini is fully removed, not just made optional. This module
talks to a *local* model server (Ollama's HTTP API by default, since it's
the easiest way to run an open-weight model like DeepSeek-Coder locally with
zero cloud dependency) only as the last resort after the knowledge base has
already been checked and found no match. If no local model is configured or
reachable, the system degrades to the bounded heuristic fallback in
orchestrator.py instead of failing -- there is no hard dependency on any LLM,
local or remote, anywhere in this package.

Swap backends by replacing the httpx call below with a call to whatever
local inference server you're running (llama.cpp server, vLLM, LM Studio,
etc.) -- the rest of the pipeline only depends on the public suggest_fix()/
parse_prompt() contracts.
"""
from __future__ import annotations
import json
import os

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

OLLAMA_URL = os.getenv("WAKEEL_LOCAL_LLM_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("WAKEEL_LOCAL_LLM_MODEL", "deepseek-coder-v2:16b")
ENABLED = os.getenv("WAKEEL_LOCAL_LLM_ENABLED", "0") == "1"

SYSTEM_PROMPT = (
    "You are a physical-design flow-repair assistant for OpenLane/ORFS. "
    "Given a failing tool log and the current config parameters, respond "
    "with ONLY a raw JSON object of the form "
    '{"adjustments": {"PARAM_NAME": <new_value_or_delta>, ...}, '
    '"explanation": "<one sentence>"}. '
    "Only use real OpenLane/ORFS config variable names. No prose outside the JSON."
)


class LocalCorrectorUnavailable(Exception):
    pass


async def suggest_fix(error_log: str, current_params: dict, engine: str) -> tuple[dict, str]:
    """Returns (adjustments_dict, explanation). Raises
    LocalCorrectorUnavailable if disabled, unreachable, or the response
    can't be parsed -- callers must have a non-LLM fallback path ready."""
    if not ENABLED:
        raise LocalCorrectorUnavailable("Local LLM corrector disabled (set WAKEEL_LOCAL_LLM_ENABLED=1)")
    if not _HAS_HTTPX:
        raise LocalCorrectorUnavailable("httpx not installed; run `pip install httpx` to enable this backend")

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Engine: {engine}\n"
        f"Current params: {json.dumps(current_params)}\n"
        f"Log tail:\n{error_log[-3000:]}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            })
            resp.raise_for_status()
            text = resp.json().get("response", "")
    except Exception as e:
        raise LocalCorrectorUnavailable(f"Local model unreachable: {e}") from e

    try:
        cleaned = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        return parsed.get("adjustments", {}), parsed.get("explanation", "Local model heuristic fix.")
    except json.JSONDecodeError as e:
        raise LocalCorrectorUnavailable(f"Local model returned non-JSON: {e}") from e


async def parse_prompt(prompt: str) -> dict | None:
    """Optional: use the local model to extract structured run parameters
    from a natural-language prompt, instead of (or before) the regex
    fallback in orchestrator.offline_fallback_parser(). Returns None on any
    failure so the caller always has the regex parser as ground truth."""
    if not ENABLED or not _HAS_HTTPX:
        return None

    sys_prompt = (
        "Extract a JSON object with keys: design_query (string, the design "
        "name as mentioned, possibly approximate), clock_period_ps (array of "
        "ints), engine ('orfs' for 7nm/asap7 or 'openlane' for 130nm/sky130). "
        "Respond with ONLY the JSON object."
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": f"{sys_prompt}\n\nPrompt: {prompt}",
                "stream": False,
                "format": "json",
            })
            resp.raise_for_status()
            text = resp.json().get("response", "")
        cleaned = text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return None
