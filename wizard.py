"""
lac/wizard.py
─────────────
First-run interactive setup wizard.
Runs when no ~/.lac/config.json is found.

Walks the user through:
  1. Picking a provider (claude / openai / ollama / custom)
  2. Entering their API key
  3. Confirming or changing the model
  4. Setting the lac-server address (defaults to localhost)
"""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import print as rprint
from lac import config

console = Console()

PROVIDERS = ["claude", "openai", "ollama", "custom"]

LOGO = """
  ██╗      █████╗  ██████╗
  ██║     ██╔══██╗██╔════╝
  ██║     ███████║██║
  ██║     ██╔══██║██║
  ███████╗██║  ██║╚██████╗
  ╚══════╝╚═╝  ╚═╝ ╚═════╝  CLI
"""


def run():
    """
    Launch the interactive first-run wizard.
    Saves config when complete.
    """
    console.clear()

    # ── Welcome banner ──────────────────────────────────────────────────────
    console.print(LOGO, style="bold cyan")
    console.print(
        Panel(
            "[bold cyan]Welcome to lac-cli![/bold cyan]\n"
            "AI-powered terminal autocomplete — [dim]let's get you set up[/dim]",
            border_style="cyan",
        )
    )

    # ── Step 1: Pick a provider ──────────────────────────────────────────────
    console.print("\n[bold]Step 1:[/bold] Choose your AI provider\n")
    for i, p in enumerate(PROVIDERS, 1):
        console.print(f"  [cyan]{i}[/cyan]. {p}")

    provider_choice = Prompt.ask(
        "\n  Enter number",
        choices=["1", "2", "3", "4"],
        default="1",
    )
    provider = PROVIDERS[int(provider_choice) - 1]

    # ── Step 2: API key ──────────────────────────────────────────────────────
    defaults = config.provider_defaults(provider)
    api_key = ""

    if provider == "ollama":
        console.print("\n[dim]Ollama runs locally — no API key needed.[/dim]")
    else:
        console.print(f"\n[bold]Step 2:[/bold] Enter your {provider} API key")
        api_key = Prompt.ask("  API key", password=True)

    # ── Step 3: Model ────────────────────────────────────────────────────────
    default_model = defaults.get("model", "")
    console.print(f"\n[bold]Step 3:[/bold] Model to use")
    model = Prompt.ask("  Model name", default=default_model)

    # ── Step 4: Base URL (custom / ollama) ───────────────────────────────────
    default_url = defaults.get("base_url", "")
    if provider in ("ollama", "custom"):
        console.print(f"\n[bold]Step 4:[/bold] Base URL")
        base_url = Prompt.ask("  Base URL", default=default_url)
    else:
        base_url = default_url

    # ── Step 5: Server address ───────────────────────────────────────────────
    console.print("\n[bold]Step 5:[/bold] lac-server WebSocket address")
    console.print("  [dim](run `lac-server` to start the server locally)[/dim]")
    server = Prompt.ask("  Server URL", default="ws://localhost:8765")

    # ── Save ─────────────────────────────────────────────────────────────────
    cfg = {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "server": server,
    }
    config.save_config(cfg)

    console.print(
        "\n[bold green]✓ Config saved to ~/.lac/config.json[/bold green]"
    )
    console.print("[dim]You can edit it anytime or run `lac --setup` again.[/dim]\n")

    input("  Press Enter to launch the shell...")
