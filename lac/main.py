"""
lac/main.py
───────────
Entry point for the `lac` CLI command.

Flow:
  1. First run → launch setup wizard
  2. Auto-start lac-server in background if not already running
  3. Connect to lac-server via WebSocket
  4. Launch the interactive shell
"""

import asyncio
import subprocess
import sys
import time
import argparse
from rich.console import Console
from rich import print as rprint

from lac import config, wizard
from lac.ws_client import LacClient
from lac.shell import run_shell

console = Console()

_server_process = None


def _port_open(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _ensure_server():
    """Start lac-server in background if not already running.
    Returns: 'already_running' | 'started' | 'failed'
    """
    global _server_process
    host, port = "127.0.0.1", 8765

    if _port_open(host, port):
        return "already_running"

    try:
        _server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.main:app",
             "--host", "0.0.0.0", "--port", str(port), "--log-level", "error"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return "failed"

    # wait up to 5s for the port to open
    for _ in range(10):
        time.sleep(0.5)
        if _server_process.poll() is not None:
            return "failed"  # process exited early
        if _port_open(host, port):
            return "started"

    # timed out — kill it and fall back to offline
    _server_process.terminate()
    return "failed"


def _stop_server():
    if _server_process and _server_process.poll() is None:
        _server_process.terminate()


async def _start(offline: bool = False, debounce: int = 150):
    """Main async entry — connect to server then run shell."""

    client = None

    if not offline:
        status = _ensure_server()
        if status == "started":
            console.print("[dim]started lac-server in background[/dim]")
        elif status == "failed":
            console.print("[yellow]⚠ could not start lac-server — running in offline mode[/yellow]")

        if status != "failed":
            server_url = config.get("server", "ws://localhost:8765")
            console.print(f"[dim]connecting to {server_url}...[/dim]", end="\r")
            client = LacClient()
            try:
                await client.connect()
                console.print("[green]✓ connected to lac-server[/green]          ")
            except ConnectionError as e:
                console.print(
                    f"[yellow]⚠ could not connect to server — running in offline mode[/yellow]\n"
                    f"[dim]  {e}[/dim]\n"
                )
                client = None

    try:
        await run_shell(client, debounce_ms=debounce)
    finally:
        if client:
            await client.disconnect()
        _stop_server()


def main():
    """
    CLI entry point registered in pyproject.toml as `lac`.
    """
    parser = argparse.ArgumentParser(
        prog="lac",
        description="lac-cli — AI-powered terminal shell",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="re-run the setup wizard",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run without connecting to lac-server",
    )
    parser.add_argument(
        "--debounce",
        type=int,
        default=150,
        metavar="MS",
        help="autocomplete debounce delay in milliseconds (default: 150)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="lac-cli 0.2.0",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("mind", help="launch LacMind multi-model debate UI")
    args = parser.parse_args()

    # ── LacMind ───────────────────────────────────────────────────────────────
    if args.command == "mind":
        from lac.mind.main import launch
        launch()
        return

    # ── First run or forced setup ────────────────────────────────────────────
    if args.setup or not config.config_exists():
        wizard.run()

    # ── Launch shell ─────────────────────────────────────────────────────────
    try:
        asyncio.run(_start(offline=args.offline, debounce=args.debounce))
    except KeyboardInterrupt:
        console.print("\n[bold cyan]bye 👋[/bold cyan]")
        sys.exit(0)


if __name__ == "__main__":
    main()
