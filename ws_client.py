"""
lac/ws_client.py
────────────────
WebSocket client that connects to the lac-server.

Responsibilities:
  - Open and maintain a persistent WS connection
  - Send the user's current typed text + shell history
  - Receive streamed token-by-token AI completions
  - Provide a clean async interface for the shell to call
"""

import asyncio
import json
import websockets
from typing import AsyncIterator, Optional
from lac import config


class LacClient:
    """
    Wraps the WebSocket connection to lac-server.

    Usage:
        client = LacClient()
        await client.connect()
        async for token in client.complete("git pu", history=[...]):
            print(token, end="", flush=True)
        await client.disconnect()
    """

    def __init__(self):
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.server_url: str = config.get("server", "ws://localhost:8765")
        self._connected: bool = False

    async def connect(self):
        """
        Open WS connection to lac-server and send the handshake
        with user's model config so the server knows how to route.
        """
        try:
            self.ws = await websockets.connect(
                self.server_url,
                ping_interval=20,    # keep-alive every 20s
                ping_timeout=10,
            )
            self._connected = True

            # send handshake — server uses this to init the AI client
            handshake = {
                "type": "handshake",
                "provider": config.get("provider"),
                "api_key": config.get("api_key"),
                "model": config.get("model"),
                "base_url": config.get("base_url"),
            }
            await self.ws.send(json.dumps(handshake))

            # wait for server ack
            ack = json.loads(await self.ws.recv())
            if ack.get("status") != "ok":
                raise ConnectionError(f"Server rejected handshake: {ack}")

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Could not connect to lac-server at {self.server_url}: {e}")

    async def disconnect(self):
        """Close the WS connection cleanly."""
        if self.ws:
            await self.ws.close()
            self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self.ws is not None

    async def complete(
        self,
        text: str,
        history: list[str],
        cwd: str = "",
    ) -> AsyncIterator[str]:
        """
        Send a completion request and yield tokens as they stream back.

        Args:
            text:    current text the user has typed so far
            history: recent command history (most recent first)
            cwd:     current working directory for context

        Yields:
            str tokens from the AI, one by one
        """
        if not self.connected:
            return

        # build the request payload
        payload = {
            "type": "complete",
            "text": text,
            "history": history[:20],  # limit history to last 20 commands
            "cwd": cwd,
        }
        await self.ws.send(json.dumps(payload))

        # stream tokens until we get the "done" signal
        async for message in self.ws:
            data = json.loads(message)

            if data["type"] == "token":
                yield data["value"]

            elif data["type"] == "done":
                break  # completion finished

            elif data["type"] == "error":
                # server hit an error (e.g. bad api key) — stop silently
                break

    async def nl_to_command(
        self,
        natural_text: str,
        history: list[str],
        cwd: str = "",
    ) -> str:
        """
        Ask the server to convert natural language → shell command.
        Waits for the full response (not streamed).

        Args:
            natural_text: e.g. "list all python files recursively"
            history:      recent commands for context
            cwd:          current directory

        Returns:
            The shell command string, e.g. "find . -name '*.py'"
        """
        if not self.connected:
            return ""

        payload = {
            "type": "nl_command",
            "text": natural_text,
            "history": history[:10],
            "cwd": cwd,
        }
        await self.ws.send(json.dumps(payload))

        result = ""
        async for message in self.ws:
            data = json.loads(message)
            if data["type"] == "token":
                result += data["value"]
            elif data["type"] == "done":
                break
            elif data["type"] == "error":
                break

        return result.strip()
