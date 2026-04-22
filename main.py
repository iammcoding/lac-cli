"""
lac/main.py
───────────
Entry point for the `lac` CLI command.

Flow:
  1. First run → launch setup wizard
  2. Connect to lac-server via WebSocket
  3. Launch the interactive shell
"""

import asyncio
import sys
import argparse
from rich.console import Console
from rich import print as rprint

from lac import config, wizard
from lac.ws_client import LacClient
from lac.shell import run_shell

console = Console()


async def _start(offline: bool = False):
    """Main async entry — connect to server then run shell."""

    client = None

    if not offline:
        # try to connect to the lac-server
        server_url = config.get("server", "ws://localhost:8765")
        console.print(f"[dim]connecting to {server_url}...[/dim]", end="\r")

        client = LacClient()
        try:
            await client.connect()
            console.print("[green]✓ connected to lac-server[/green]          ")
        except ConnectionError as e:
            # not fatal — shell works without the server (offline mode)
            console.print(
                f"[yellow]⚠ could not connect to server — running in offline mode[/yellow]\n"
                f"[dim]  {e}[/dim]\n"
                f"[dim]  start the server with: lac-server[/dim]\n"
            )
            client = None

    try:
        await run_shell(client)
    finally:
        if client:
            await client.disconnect()


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
        "--version",
        action="version",
        version="lac-cli 0.1.0",
    )
    args = parser.parse_args()

    # ── First run or forced setup ────────────────────────────────────────────
    if args.setup or not config.config_exists():
        wizard.run()

    # ── Launch shell ─────────────────────────────────────────────────────────
    try:
        asyncio.run(_start(offline=args.offline))
    except KeyboardInterrupt:
        console.print("\n[bold cyan]bye 👋[/bold cyan]")
        sys.exit(0)


if __name__ == "__main__":
    main()
