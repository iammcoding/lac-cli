"""
lac/mind/server.py
──────────────────
FastAPI server for LacMind.
Serves UI pages + WebSocket debate endpoint.
"""

import asyncio
import json
import logging
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from lac.mind import models as model_registry
from lac.mind.debate import run_debate
from lac.mind.db import save_debate, get_debates

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
log = logging.getLogger("lacmind.server")

UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(title="lacmind", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


def _html(name: str):
    path = UI_DIR / name
    return HTMLResponse(path.read_text())


@app.get("/")
async def index():
    return _html("index.html")


@app.get("/chat/{chat_id}")
async def chat(chat_id: str):
    return _html("index.html")


@app.get("/setup")
async def setup():
    return _html("setup.html")


@app.get("/settings")
async def settings():
    return _html("settings.html")


@app.get("/history")
async def history():
    return _html("history.html")


@app.get("/lacicon.png")
async def icon():
    icon_path = Path(__file__).parent.parent.parent / "lacicon.png"
    return FileResponse(str(icon_path))


# ── Models API ────────────────────────────────────────────────────────────────

@app.get("/api/models")
async def get_models():
    return model_registry.load_models()


@app.post("/api/models")
async def add_model(data: dict):
    try:
        m = model_registry.add_model(
            name=data["name"],
            provider=data["provider"],
            model=data["model"],
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
        )
        return {"ok": True, "model": m}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.delete("/api/models/{name}")
async def delete_model(name: str):
    model_registry.remove_model(name)
    return {"ok": True}


@app.post("/api/logout")
async def logout():
    """Delete all models configuration"""
    try:
        model_registry.clear_all_models()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── History API ───────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history():
    return await get_debates()


@app.get("/api/chat/{chat_id}")
async def get_chat(chat_id: str):
    from lac.mind.db import get_debate_by_id
    debate = await get_debate_by_id(chat_id)
    if debate:
        return {"ok": True, "debate": debate}
    return {"ok": False, "error": "Chat not found"}


# ── Debate WebSocket ──────────────────────────────────────────────────────────

@app.websocket("/ws/debate")
async def debate_ws(ws: WebSocket):
    await ws.accept()
    log.info("WebSocket client connected")
    
    stop_event = asyncio.Event()

    async def broadcast(data: dict):
        try:
            log.debug(f"Broadcasting: {data.get('type')}")
            await ws.send_text(json.dumps(data))
        except Exception as e:
            log.error(f"Broadcast error: {e}")

    async def listen_for_stop():
        """Listen for stop signal from client"""
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                if msg.get('type') == 'stop':
                    log.info("Stop signal received from client")
                    stop_event.set()
                    break
        except Exception:
            pass

    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)
        log.info(f"Received debate request: {msg.get('prompt', '')[:50]}...")

        prompt = msg.get("prompt", "").strip()
        duration = int(msg.get("duration", 120))
        selected = msg.get("models", [])  # list of model names
        chat_id = msg.get("chat_id", "")
        conversation_history = msg.get("history", [])  # previous Q&A pairs

        if not prompt:
            await broadcast({"type": "error", "message": "prompt is required"})
            return

        all_models = model_registry.load_models()
        debate_models = [m for m in all_models if m["name"] in selected] if selected else all_models
        log.info(f"Debate models: {[m['name'] for m in debate_models]}")

        if len(debate_models) < 2:
            await broadcast({"type": "error", "message": "need at least 2 models to debate"})
            return

        await broadcast({"type": "debate_start", "prompt": prompt, "duration": duration, "models": [m["name"] for m in debate_models]})

        # Start listening for stop signal
        stop_task = asyncio.create_task(listen_for_stop())

        summary, thread = await run_debate(prompt, debate_models, duration, broadcast, stop_event, conversation_history)
        log.info("Debate completed, saving to DB")
        
        # Cancel stop listener
        stop_task.cancel()

        # Extract chat_id from the first message if available
        if not chat_id:
            import time
            chat_id = str(int(time.time() * 1000))

        await save_debate(
            chat_id=chat_id,
            prompt=prompt,
            consensus=summary,
            transcript=thread,
            models=[m["name"] for m in debate_models],
        )

    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
    except Exception as e:
        log.error(f"Debate error: {e}", exc_info=True)
        await broadcast({"type": "error", "message": str(e)})
