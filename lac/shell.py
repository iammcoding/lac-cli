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
from html import escape as _esc
from lac import config
from lac.config import CONFIG_FILE
from typing import Optional
from server.router import clean_command
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
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
    "clear", "exit", "logout", "history",
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
                    display=HTML(f"<cyan>{_esc(cmd)}</cyan>  <gray>← {_esc(phrase)}</gray>"),
                )

        # 2. History — most recent matching commands
        seen = set()
        for cmd in self.history_commands:
            if cmd.lower().startswith(text) and cmd not in seen:
                seen.add(cmd)
                yield Completion(
                    cmd,
                    start_position=-len(document.text_before_cursor),
                    display=HTML(f"<green>{_esc(cmd)}</green>  <gray>↑ history</gray>"),
                )

        # 3. Static command list
        for cmd in STATIC_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(document.text_before_cursor),
                )


def run_command(cmd: str, session_history: list[dict]) -> str:
    """
    Execute a shell command and print its output.
    Handles cd specially since subprocess can't change the parent process's dir.
    Returns the output for session history.
    """
    cmd = cmd.strip()
    if not cmd:
        return ""

    # built-ins
    if cmd == "logout":
        confirm = input("  clear API key and logout? [y/N] ").strip().lower()
        if confirm in ("y", "yes"):
            if CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
            console.print("[bold cyan]logged out — run `lac` again to set up[/bold cyan]")
            raise SystemExit
        return ""

    if cmd == "exit":
        console.print("[bold cyan]bye 👋[/bold cyan]")
        raise SystemExit

    if cmd == "clear":
        os.system("clear")
        session_history.clear()
        return ""

    if cmd.startswith("cd "):
        path = cmd[3:].strip()
        try:
            os.chdir(os.path.expanduser(path))
            return f"Changed to {os.getcwd()}"
        except FileNotFoundError as e:
            console.print(f"[red]cd: {path}: No such directory[/red]")
            return str(e)

    # run everything else and capture output
    try:
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        output = result.stdout + result.stderr
        print(output, end="")
        return output[:2000]  # limit to 2000 chars
    except Exception as e:
        error_msg = f"error: {e}"
        console.print(f"[red]{error_msg}[/red]")
        return error_msg


class AIAutoSuggest(AutoSuggest):
    """
    Ghost text suggestions powered by the AI server.
    Uses a dedicated WS connection so it never conflicts with the main client.
    Debounces requests and falls back to history on failure.
    """

    def __init__(self, server_url: str, history_commands: list[str], debounce_ms: int = 150):
        self._server_url = server_url
        self._history = history_commands
        self._debounce_ms = debounce_ms
        self._task: Optional[asyncio.Task] = None
        self._cache: dict[str, str] = {}
        self._client: Optional[LacClient] = None

    async def connect(self):
        """Open a dedicated WS connection for autocomplete."""
        try:
            self._client = LacClient()
            await self._client.connect()
        except Exception:
            self._client = None

    def get_suggestion(self, buffer, document):
        text = document.text_before_cursor
        if not text.strip():
            return None
        if text in self._cache:
            suffix = self._cache[text]
            return Suggestion(suffix) if suffix else None
        # cancel previous in-flight fetch
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        self._task = asyncio.ensure_future(self._fetch(buffer, text))
        return None

    def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            # reconnect the dedicated client since the stream was interrupted
            asyncio.ensure_future(self._reconnect())

    async def _reconnect(self):
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        await self.connect()

    async def _fetch(self, buffer, text: str):
        await asyncio.sleep(self._debounce_ms / 1000.0)  # convert ms to seconds
        if buffer.document.text_before_cursor != text:
            return
        suffix = ""
        if self._client and self._client.connected:
            try:
                tokens = []
                async for token in self._client.complete(
                    text, history=self._history, cwd=os.getcwd()
                ):
                    tokens.append(token) 
                result = clean_command("".join(tokens))
                # only use result if it completes what the user typed
                if result.lower().startswith(text.lower()):
                    suffix = result[len(text):]
            except Exception:
                pass
        # fallback: history prefix match
        if not suffix:
            for cmd in self._history:
                if cmd.lower().startswith(text.lower()) and cmd != text:
                    suffix = cmd[len(text):]
                    break
        self._cache[text] = suffix
        # update ghost text if user hasn't moved on
        if buffer.document.text_before_cursor == text:
            buffer.suggestion = Suggestion(suffix) if suffix else None
            try:
                get_app().invalidate()
            except Exception:
                pass


async def run_shell(client: Optional[LacClient] = None, debounce_ms: int = 150):
    """
    Main shell loop.

    Args:
        client: connected LacClient instance (or None for offline mode)
        debounce_ms: autocomplete debounce delay in milliseconds
    """
    history = InMemoryHistory()
    history_commands: list[str] = []
    session_history: list[dict] = []  # {cmd: str, output: str}
    completer = LacCompleter(history_commands)
    auto_suggest = AIAutoSuggest(
        config.get("server", "ws://localhost:8765"),
        history_commands,
        debounce_ms=debounce_ms,
    )
    if client and client.connected:
        await auto_suggest.connect()

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
        auto_suggest=auto_suggest,
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
                auto_suggest.cancel()
                console.print("[dim]thinking...[/dim]", end="\r")
                try:
                    cmd = await client.nl_to_command(
                        user_input,
                        history=history_commands,
                        session=session_history[-10:],
                        cwd=os.getcwd(),
                    )
                except Exception as e:
                    console.print(f"[red]error: {e}[/red]")
                    continue
                if cmd:
                    console.print(f"[dim]→ {cmd}[/dim]")
                    confirm = input("  run? [Y/n] ").strip().lower()
                    if confirm in ("", "y", "yes"):
                        output = run_command(cmd, session_history)
                        session_history.append({"cmd": cmd, "output": output})
                        if len(session_history) > 20:
                            session_history.pop(0)
                    continue

            output = run_command(user_input, session_history)
            session_history.append({"cmd": user_input, "output": output})
            if len(session_history) > 20:
                session_history.pop(0)

        except KeyboardInterrupt:
            pass  # ignore Ctrl+C — use 'exit' to quit
        except EOFError:
            break  # Ctrl+D
        except SystemExit:
            break
        except Exception as e:
            console.print(f"[red]error: {e}[/red]")

    if auto_suggest._client:
        await auto_suggest._client.disconnect()


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
