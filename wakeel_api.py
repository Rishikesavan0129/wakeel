from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import wakeel_core
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

    try:
        raw_data = await websocket.receive_text()
        payload = json.loads(raw_data)
        prompt = payload.get("prompt", "")

        if not prompt:
            await websocket.send_text(json.dumps({"type": "error", "message": "No prompt received."}))
            return

        try:
            await wakeel_core.run_agentic_flow_stream(prompt, websocket)
        except Exception as core_error:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Core System Fault: {str(core_error)}"
            }))

    except WebSocketDisconnect:
        print("[GATEWAY] Client disconnected. Terminal stream terminated.")

    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": f"Gateway Fault: {str(e)}"}))
        except Exception:
            pass

    finally:
        # orchestrator.run_agentic_flow_stream already sends "finished" and
        # closes the socket in its own finally block; this is a backstop in
        # case that path was never reached (e.g. prompt was empty).
        try:
            await websocket.send_text(json.dumps({"type": "finished"}))
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
