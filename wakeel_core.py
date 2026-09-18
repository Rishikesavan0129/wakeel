"""
Drop-in replacement for the old wakeel_core.py.

wakeel_api.py does `import wakeel_core` and calls
`wakeel_core.run_agentic_flow_stream(prompt, websocket)` -- that entrypoint
is preserved here unchanged so the FastAPI gateway needs zero modifications.
All the actual logic now lives in the `wakeel/` package (schema-driven
config generation, fuzzy design discovery, scored KB matching, optional
local-model correction). Gemini and google-generativeai are gone entirely --
grep the whole package, there's no `import google` anywhere anymore.
"""
from wakeel.orchestrator import (  # noqa: F401
    run_agentic_flow_stream,
    DEFAULT_MAX_RETRIES,
    ABSOLUTE_MAX_RETRIES,
    MAX_SWEEP_POINTS,
    ABSOLUTE_MAX_SWEEP_POINTS,
)
