from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import wakeel_core
import asyncio
import json
import os

app = FastAPI()

# CORS origin is now configurable instead of a hardcoded wildcard. Set
# WAKEEL_ALLOWED_ORIGIN to your dashboard's actual origin in any deployment
# that isn't strictly localhost-to-localhost. Defaults to localhost-only.
_allowed_origin = os.getenv("WAKEEL_ALLOWED_ORIGIN", "http://127.0.0.1:5500")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_allowed_origin] if _allowed_origin != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.websocket("/ws/run_eda")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket tunnel for the Wakeel EDA flow orchestrator.
    No cloud API involved anywhere downstream of this handler -- everything
    in wakeel_core / wakeel.* runs locally.
    """
    await websocket.accept()
    run_task = None

    try:
        raw_data = await websocket.receive_text()
        payload = json.loads(raw_data)
        prompt = payload.get("prompt", "")
        # v3: optional structured sweep config -- {"frequencies_ghz": [...]}
        # or {"start_ghz", "end_ghz", "step_ghz"}. When present this
        # overrides whatever GHz/MHz numbers the prompt text happens to
        # mention, so the sweep the UI's controls describe is exactly the
        # sweep that runs. Validated inside orchestrator.build_sweep_clocks_ps;
        # a malformed sweep object is reported back over the socket as an
        # ordinary error, not a crash.
        sweep = payload.get("sweep")

        # v3: explicit engine selection from the UI's toggle, bypassing
        # prompt-text guessing entirely -- fixes a real incident where a
        # prompt correctly said "7nm" but still ran on OpenLane/sky130
        # because the requested design only existed under the OpenLane
        # design root (see orchestrator.run_agentic_flow_stream's
        # engine_override docstring for the full story). Only "openlane"
        # and "orfs" are meaningful; anything else is ignored rather than
        # erroring, so a stray/garbled value falls back to prompt-parsing
        # instead of failing the whole run.
        engine_override = payload.get("engine")
        if engine_override not in ("openlane", "orfs"):
            engine_override = None

        # v3: caller-adjustable retry budget / sweep-point cap. Both are
        # clamped server-side (see wakeel.orchestrator.ABSOLUTE_MAX_RETRIES /
        # ABSOLUTE_MAX_SWEEP_POINTS) regardless of what's requested here --
        # this endpoint only decides the requested value, never the ceiling.
        try:
            max_retries = int(payload.get("max_retries", wakeel_core.DEFAULT_MAX_RETRIES))
        except (TypeError, ValueError):
            max_retries = wakeel_core.DEFAULT_MAX_RETRIES
        max_retries = max(1, min(max_retries, wakeel_core.ABSOLUTE_MAX_RETRIES))

        try:
            max_sweep_points = int(payload.get("max_sweep_points", wakeel_core.MAX_SWEEP_POINTS))
        except (TypeError, ValueError):
            max_sweep_points = wakeel_core.MAX_SWEEP_POINTS
        max_sweep_points = max(1, min(max_sweep_points, wakeel_core.ABSOLUTE_MAX_SWEEP_POINTS))

        if not prompt:
            await websocket.send_text(json.dumps({"type": "error", "message": "No prompt received."}))
            return

        run_task = asyncio.create_task(wakeel_core.run_agentic_flow_stream(
            prompt, websocket, sweep_override=sweep,
            max_retries=max_retries, max_sweep_points=max_sweep_points,
            engine_override=engine_override))

        # v3: concurrently listen for a {"type": "stop"} message from the
        # client WHILE the run is in flight -- this is what makes the UI's
        # Stop button actually kill the live subprocess, rather than just
        # closing the tab and leaving OpenLane/ORFS running headless.
        # A plain `await run_task` here would block this coroutine from
        # ever reading another incoming message until the run finished on
        # its own, so instead we race a fresh receive_text() against the
        # run itself on every loop iteration.
        while not run_task.done():
            listen_task = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait(
                {run_task, listen_task}, return_when=asyncio.FIRST_COMPLETED)
            if listen_task in done:
                try:
                    raw = listen_task.result()
                except WebSocketDisconnect:
                    print("[GATEWAY] Client disconnected mid-run -- cancelling the live subprocess.")
                    if not run_task.done():
                        run_task.cancel()
                    break
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    msg = {}
                if msg.get("type") == "stop" and not run_task.done():
                    await websocket.send_text(json.dumps(
                        {"type": "warning", "message": "[STOP REQUESTED] Killing the live subprocess..."}))
                    run_task.cancel()
            else:
                listen_task.cancel()

        try:
            await run_task
        except asyncio.CancelledError:
            await websocket.send_text(json.dumps(
                {"type": "cancelled", "message": "Run stopped by user."}))

    except WebSocketDisconnect:
        print("[GATEWAY] Client disconnected. Terminal stream terminated.")
        if run_task and not run_task.done():
            run_task.cancel()

    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": f"Gateway Fault: {str(e)}"}))
        except Exception:
            pass

    finally:
        # orchestrator.run_agentic_flow_stream already sends "finished" and
        # closes the socket in its own finally block; this is a backstop in
        # case that path was never reached (e.g. prompt was empty, or the
        # run was cancelled before it got that far).
        try:
            await websocket.send_text(json.dumps({"type": "finished"}))
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
