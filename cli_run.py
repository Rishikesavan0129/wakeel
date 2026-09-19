"""
Terminal-only client for a real Wakeel run -- no browser needed. Connects
straight to the same WebSocket index.html uses, sends one prompt, and
streams every message live to your terminal. This does NOT replace the GUI
as the product -- it's a fast path for exactly this situation: you want to
see a REAL run happen right now without context-switching into a browser
tab.

Usage:
    python3 cli_run.py "run wakeel_alu at 200 MHz on 130nm"
    python3 cli_run.py "run wakeel_alu on 130nm" --sweep 0.2,0.4,0.6
    python3 cli_run.py "run wakeel_alu on 130nm" --sweep-range 0.2:1.0:0.2
    python3 cli_run.py "run wakeel_alu at 500 MHz" --engine orfs
"""
import argparse
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
    "ppa_summary": "\033[94m",   # blue
    "sweep_summary": "\033[94m",
}
RESET = "\033[0m"


def _build_sweep_arg(args) -> dict | None:
    """Mirrors wakeel/orchestrator.py:build_sweep_clocks_ps's two accepted
    shapes -- kept in sync manually since this is a thin standalone
    client, not a shared module import."""
    if args.sweep:
        freqs = [float(x) for x in args.sweep.split(",") if x.strip()]
        return {"frequencies_ghz": freqs}
    if args.sweep_range:
        start, end, step = (float(x) for x in args.sweep_range.split(":"))
        return {"start_ghz": start, "end_ghz": end, "step_ghz": step}
    return None


async def main(prompt: str, sweep: dict | None, max_retries: int | None, max_sweep_points: int | None,
               engine: str | None = None):
    print(f"Connecting to {WS_URL} ...")
    try:
        async with websockets.connect(WS_URL) as ws:
            payload = {"prompt": prompt}
            if sweep:
                payload["sweep"] = sweep
            if max_retries is not None:
                payload["max_retries"] = max_retries
            if max_sweep_points is not None:
                payload["max_sweep_points"] = max_sweep_points
            if engine:
                payload["engine"] = engine
            await ws.send(json.dumps(payload))
            print(f"Sent: {prompt!r}" + (f"  sweep={sweep}" if sweep else "") + "\n")

            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                msg_type = data.get("type", "log")
                color = COLORS.get(msg_type, "")

                if msg_type == "ppa_summary":
                    print(f"{color}[PPA_SUMMARY]{RESET} "
                          f"{data.get('target_freq_ghz')} GHz target -> "
                          f"achieved={data.get('achieved_freq_ghz')} GHz, "
                          f"area={data.get('area_um2')} um2, power={data.get('power_w')} W, "
                          f"status={data.get('status')}")
                elif msg_type == "sweep_summary":
                    print(f"{color}[SWEEP_SUMMARY]{RESET} {data.get('csv_path')} "
                          f"({len(data.get('rows', []))} rows)")
                else:
                    message = data.get("message", "")
                    print(f"{color}[{msg_type.upper():8}]{RESET} {message}")

                if msg_type == "finished":
                    break
    except ConnectionRefusedError:
        print("\nConnection refused -- is wakeel_api.py actually running?")
        print("In another terminal: source venv/bin/activate && python3 wakeel_api.py")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("prompt")
    parser.add_argument("--sweep", help="Comma-separated GHz list, e.g. 0.2,0.4,0.6")
    parser.add_argument("--sweep-range", help="start:end:step in GHz, e.g. 0.2:1.0:0.2")
    parser.add_argument("--max-retries", type=int, help="Self-heal attempts per sweep point before giving up (default 3, server-capped at 10)")
    parser.add_argument("--max-sweep-points", type=int, help="Sweep point cap (default 50, server-capped at 200)")
    parser.add_argument("--engine", choices=["openlane", "orfs"],
                         help="Explicit engine/tech-node selection (openlane=130nm sky130, orfs=7nm ASAP7) -- "
                              "bypasses prompt-text guessing, same as the UI's engine toggle. Omit to let the "
                              "prompt decide.")
    if len(sys.argv) < 2:
        print('Usage: python3 cli_run.py "run wakeel_alu at 200 MHz on 130nm" [--sweep 0.2,0.4] [--sweep-range 0.2:1.0:0.2]')
        sys.exit(1)
    ns = parser.parse_args()
    asyncio.run(main(ns.prompt, _build_sweep_arg(ns), ns.max_retries, ns.max_sweep_points, ns.engine))
