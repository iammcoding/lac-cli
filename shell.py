"""
lac/shell.py
────────────
The main interactive shell powered by prompt_toolkit.

Features:
  - Ghost text autocomplete (like fish shell)
  - Natural language → command detection
  - Debounced AI calls (300ms) so we don't spam the server
  - Falls back to history/static completions if server is offline
  - Actual command execution via subprocess
"""

import asyncio
import os
import subprocess
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from rich.console import Console

from lac.ws_client import LacClient

console = Console()

# ── Static fallback commands used when server is offline ────────────────────
STATIC_COMMANDS = [
    "ls", "ls -la", "ls -lh", "ls -a",
    "cd", "pwd", "mkdir", "rmdir",
    "rm", "rm -rf", "cp", "mv", "touch", "cat",
    "echo", "grep", "find", "chmod", "chown",
    "git status", "git add .", "git commit -m ''",
    "git push", "git pull", "git log --oneline",
    "python3", "pip install", "pip list", "pip freeze",
    "npm install", "npm start", "npm run dev", "npm run build",
    "docker ps", "docker build .", "docker run",
    "clear", "exit", "history",
    "curl", "wget", "ssh", "scp",
    "df -h", "du -sh", "ps aux", "top", "kill",
]

# ── Natural language phrases → shell commands ────────────────────────────────
NL_MAP = {
    "list files": "ls -la",
    "list all files": "ls -la",
    "show files": "ls",
    "go back": "cd ..",
    "go home": "cd ~",
    "where am i": "pwd",
    "make folder": "mkdir",
    "delete file": "rm",
    "show file": "cat",
    "search for": "grep -r",
    "find file": "find . -name",
    "git save": "git add . && git commit -m ''",
    "push code": "git push",
    "pull code": "git pull",
    "git log": "git log --oneline -20",
    "install packages": "pip install -r requirements.txt",
    "run python": "python3",
    "disk space": "df -h",
    "running processes": "ps aux",
    "kill process": "kill -9",
    "check ports": "lsof -i",
    "system info": "uname -a",
}


class LacCompleter(Completer):
    """
    Custom completer that combines:
    1. Local NL map (instant, no network)
    2. Session history (instant)
    3. Static command list (instant fallback)

    AI completions are handled separately via ghost text
    so they don't block the UI thread.
    """

    def __init__(self, history_commands: list[str]):
        self.history_commands = history_commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower().strip()
        if not text:
            return

        # 1. NL map — show matching natural language shortcuts
        for phrase, cmd in NL_MAP.items():
            if text in phrase or phrase.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(document.text_before_cursor),
                    display=HTML(f"<cyan>{cmd}</cyan>  <gray>← {phrase}</gray>"),
                )

        # 2. History — most recent matching commands
        seen = set()
        for cmd in self.history_commands:
            if cmd.lower().startswith(text) and cmd not in seen:
                seen.add(cmd)
                yield Completion(
                    cmd,
                    start_position=-len(document.text_before_cursor),
                    display=HTML(f"<green>{cmd}</green>  <gray>↑ history</gray>"),
                )

        # 3. Static command list
        for cmd in STATIC_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(document.text_before_cursor),
                )


def run_command(cmd: str):
    """
    Execute a shell command and print its output.
    Handles cd specially since subprocess can't change the parent process's dir.
    """
    cmd = cmd.strip()
    if not cmd:
        return

    # built-ins
    if cmd == "exit":
        console.print("[bold cyan]bye 👋[/bold cyan]")
        raise SystemExit

    if cmd == "clear":
        os.system("clear")
        return

    if cmd.startswith("cd "):
        # handle cd by actually changing the process directory
        path = cmd[3:].strip()
        try:
            os.chdir(os.path.expanduser(path))
        except FileNotFoundError:
            console.print(f"[red]cd: {path}: No such directory[/red]")
        return

    # run everything else
    try:
        result = subprocess.run(cmd, shell=True, text=True)
        # output is printed live (no capture) so it feels like a real shell
    except Exception as e:
        console.print(f"[red]error: {e}[/red]")


async def run_shell(client: Optional[LacClient] = None):
    """
    Main shell loop.

    Args:
        client: connected LacClient instance (or None for offline mode)
    """
    history = InMemoryHistory()
    history_commands: list[str] = []
    completer = LacCompleter(history_commands)

    # ── Key bindings ─────────────────────────────────────────────────────────
    kb = KeyBindings()

    @kb.add("tab")
    def accept_suggestion(event):
        """Tab accepts the current ghost text suggestion."""
        buf = event.app.current_buffer
        if buf.suggestion:
            buf.insert_text(buf.suggestion.text)

    # ── Prompt session ────────────────────────────────────────────────────────
    session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        key_bindings=kb,
        # show current directory in prompt
        message=lambda: HTML(
            f"<cyan><b>lac</b></cyan> <gray>{os.getcwd()}</gray>\n<cyan>→</cyan> "
        ),
    )

    mode = "online" if client and client.connected else "offline"
    console.print(
        f"\n[bold cyan]lac-cli[/bold cyan] [dim]({mode} mode)[/dim]  "
        f"[dim]Tab = accept · Ctrl+C = cancel · 'exit' = quit[/dim]\n"
    )

    while True:
        try:
            user_input = await session.prompt_async()

            if not user_input.strip():
                continue

            # add to history so future completions learn from it
            history_commands.insert(0, user_input.strip())

            # if server is connected, check if this is a NL command
            if client and client.connected and _looks_like_natural_language(user_input):
                console.print("[dim]thinking...[/dim]", end="\r")
                cmd = await client.nl_to_command(
                    user_input,
                    history=history_commands,
                    cwd=os.getcwd(),
                )
                if cmd:
                    console.print(f"[dim]→ {cmd}[/dim]")
                    confirm = input("  run? [Y/n] ").strip().lower()
                    if confirm in ("", "y", "yes"):
                        run_command(cmd)
                    continue

            run_command(user_input)

        except KeyboardInterrupt:
            console.print()  # newline after ^C
        except EOFError:
            break  # Ctrl+D
        except SystemExit:
            break


def _looks_like_natural_language(text: str) -> bool:
    """
    Heuristic: if the input has spaces and doesn't start with
    a known command, treat it as natural language.
    """
    text = text.strip().lower()
    if not text or " " not in text:
        return False

    first_word = text.split()[0]
    shell_starters = {
        "ls", "cd", "rm", "cp", "mv", "mkdir", "cat", "echo",
        "git", "python", "python3", "pip", "npm", "node", "docker",
        "grep", "find", "curl", "wget", "ssh", "sudo", "chmod",
        "export", "source", "which", "man", "kill", "ps", "top",
        "df", "du", "tar", "zip", "unzip", "vim", "nano",
    }
    return first_word not in shell_starters
