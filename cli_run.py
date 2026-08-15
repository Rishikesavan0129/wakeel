"""
Terminal-only client for a real Wakeel run -- no browser needed. Connects
straight to the same WebSocket index.html uses, sends one prompt, and
streams every message live to your terminal. This does NOT replace the GUI
as the product -- it's a fast path for exactly this situation: you want to
see a REAL run happen right now without context-switching into a browser
tab.

Usage:
    python3 cli_run.py "run wakeel_alu at 200 MHz on 130nm"
"""
import asyncio
import json
import sys

import websockets

WS_URL = "ws://127.0.0.1:8000/ws/run_eda"

COLORS = {
    "log": "\033[90m",       # gray
    "phase": "\033[96m",     # cyan
    "success": "\033[92m",   # green
    "warning": "\033[93m",   # yellow
    "error": "\033[91m",     # red
    "copilot": "\033[95m",   # magenta
    "final": "\033[92m",
}
RESET = "\033[0m"


async def main(prompt: str):
    print(f"Connecting to {WS_URL} ...")
    try:
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({"prompt": prompt}))
            print(f"Sent: {prompt!r}\n")

            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                msg_type = data.get("type", "log")
                message = data.get("message", "")
                color = COLORS.get(msg_type, "")
                print(f"{color}[{msg_type.upper():8}]{RESET} {message}")

                if msg_type == "finished":
                    break
    except ConnectionRefusedError:
        print("\nConnection refused -- is wakeel_api.py actually running?")
        print("In another terminal: source venv/bin/activate && python3 wakeel_api.py")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python3 cli_run.py "run wakeel_alu at 200 MHz on 130nm"')
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
