"""
server/main.py
──────────────
lac-server: FastAPI WebSocket server.

Each terminal client connects, sends a handshake with their model config,
then sends completion/nl_command requests — the server routes to their AI
and streams tokens back.

Multiple clients are fully isolated — each session has its own model config.

Run with:
    lac-server
  or directly:
    uvicorn server.main:app --host 0.0.0.0 --port 8765
"""

import asyncio
import json
import logging
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from server.router import route

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lac-server")

app = FastAPI(title="lac-server", version="0.1.0")


# ── Session state per connected client ───────────────────────────────────────

class Session:
    """Holds per-connection config extracted from the handshake."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.provider: str = ""
        self.api_key: str = ""
        self.model: str = ""
        self.base_url: str = ""

    async def send(self, data: dict):
        """Send a JSON message to this client."""
        await self.ws.send_text(json.dumps(data))

    async def send_token(self, token: str):
        await self.send({"type": "token", "value": token})

    async def send_done(self):
        await self.send({"type": "done"})

    async def send_error(self, msg: str):
        await self.send({"type": "error", "message": msg})


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = Session(ws)

    log.info(f"client connected from {ws.client.host}")

    try:
        # ── Step 1: handshake ─────────────────────────────────────────────
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "handshake":
            await session.send_error("first message must be a handshake")
            return

        session.provider = msg.get("provider", "")
        session.api_key  = msg.get("api_key", "")
        session.model    = msg.get("model", "")
        session.base_url = msg.get("base_url", "")

        if not session.provider or not session.model:
            await session.send_error("handshake missing provider or model")
            return

        log.info(f"  handshake ok — provider={session.provider} model={session.model}")
        await session.send({"status": "ok", "type": "ack"})

        # ── Step 2: message loop ──────────────────────────────────────────
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type in ("complete", "nl_command"):
                await handle_completion(session, msg)

            else:
                await session.send_error(f"unknown message type: {msg_type}")

    except WebSocketDisconnect:
        log.info(f"client disconnected from {ws.client.host}")
    except Exception as e:
        log.error(f"session error: {e}")
        try:
            await session.send_error(str(e))
        except Exception:
            pass


async def handle_completion(session: Session, msg: dict):
    """
    Handle a 'complete' or 'nl_command' request.
    Streams tokens back to the client as they arrive from the AI.
    """
    text    = msg.get("text", "")
    history = msg.get("history", [])
    cwd     = msg.get("cwd", "")
    mode    = msg.get("type")  # "complete" or "nl_command"

    if not text:
        await session.send_done()
        return

    log.debug(f"  {mode}: '{text[:40]}...' " if len(text) > 40 else f"  {mode}: '{text}'")

    try:
        async for token in route(
            provider=session.provider,
            text=text,
            history=history,
            cwd=cwd,
            mode=mode,
            api_key=session.api_key,
            model=session.model,
            base_url=session.base_url,
        ):
            await session.send_token(token)

    except Exception as e:
        log.error(f"  router error: {e}")
        await session.send_error(str(e))

    await session.send_done()


# ── Health check endpoint ─────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "lac-server"}


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    """Entry point for `lac-server` CLI command."""
    print("🐆 lac-server starting on ws://0.0.0.0:8765")
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=8765,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run()
