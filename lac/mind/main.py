"""
lac/mind/main.py
────────────────
Entry point for `lac mind`.
Finds a free port starting at 8766, starts the server, opens browser.
"""

import socket
import subprocess
import sys
import time
import webbrowser


def _find_free_port(start: int = 8766, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port found in range")


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch():
    from lac.mind.models import load_models

    port = _find_free_port()
    base_url = f"http://localhost:{port}"

    models = load_models()
    start_path = "/" if models else "/setup"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "lac.mind.server:app",
            "--host", "0.0.0.0",
            "--port", str(port),
            "--log-level", "info",
        ],
    )

    # wait for server to be ready
    for _ in range(20):
        time.sleep(0.3)
        if proc.poll() is not None:
            print("lacmind: server failed to start")
            sys.exit(1)
        if _port_open(port):
            break
    else:
        proc.terminate()
        print("lacmind: server timed out")
        sys.exit(1)

    print(f"lacmind running at {base_url}")
    webbrowser.open(f"{base_url}{start_path}")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\nlacmind stopped")
