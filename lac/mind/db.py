"""
lac/mind/db.py
──────────────
SQLite storage for debate history.
Auto-installs aiosqlite if missing.
"""

import subprocess
import sys
from pathlib import Path

DB_PATH = Path.home() / ".lac" / "mind.db"


def _ensure_aiosqlite():
    try:
        import aiosqlite
    except ImportError:
        import subprocess
        import sys
        print("installing aiosqlite...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiosqlite", "-q", "--break-system-packages"])


async def get_db():
    _ensure_aiosqlite()
    import aiosqlite
    import os
    
    # Ensure directory exists with proper permissions
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Create DB with proper permissions if it doesn't exist
    if not DB_PATH.exists():
        DB_PATH.touch()
        try:
            os.chmod(DB_PATH, 0o666)
        except (PermissionError, OSError):
            pass
    
    db = await aiosqlite.connect(str(DB_PATH))
    await db.execute("""
        CREATE TABLE IF NOT EXISTS debates (
            chat_id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            consensus TEXT,
            transcript TEXT,
            models TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.commit()
    return db


async def save_debate(chat_id: str, prompt: str, consensus: str, transcript: list, models: list):
    import json
    db = await get_db()
    
    # Check if chat exists
    async with db.execute("SELECT prompt, consensus, transcript FROM debates WHERE chat_id = ?", (chat_id,)) as cursor:
        existing = await cursor.fetchone()
    
    if existing:
        # Append to existing chat
        old_prompt = existing[0]
        old_consensus = existing[1]
        old_transcript = json.loads(existing[2] or "[]")
        
        # Build conversation history
        new_prompt = f"{old_prompt}\n\n---\n\n{prompt}"
        new_consensus = f"{old_consensus}\n\n---\n\n{consensus}"
        new_transcript = old_transcript + transcript
        
        await db.execute(
            "UPDATE debates SET prompt = ?, consensus = ?, transcript = ? WHERE chat_id = ?",
            (new_prompt, new_consensus, json.dumps(new_transcript), chat_id)
        )
    else:
        # Create new chat
        await db.execute(
            "INSERT INTO debates (chat_id, prompt, consensus, transcript, models) VALUES (?, ?, ?, ?, ?)",
            (chat_id, prompt, consensus, json.dumps(transcript), json.dumps(models))
        )
    
    await db.commit()
    await db.close()


async def get_debates(limit: int = 50) -> list:
    import json
    db = await get_db()
    async with db.execute(
        "SELECT chat_id, prompt, consensus, transcript, models, created_at FROM debates ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
    await db.close()
    return [
        {
            "id": r[0], "prompt": r[1], "consensus": r[2],
            "transcript": json.loads(r[3] or "[]"),
            "models": json.loads(r[4] or "[]"),
            "created_at": r[5]
        }
        for r in rows
    ]


async def get_debate_by_id(chat_id: str):
    import json
    db = await get_db()
    async with db.execute(
        "SELECT chat_id, prompt, consensus, transcript, models, created_at FROM debates WHERE chat_id = ?",
        (chat_id,)
    ) as cursor:
        row = await cursor.fetchone()
    await db.close()
    if row:
        return {
            "id": row[0], "prompt": row[1], "consensus": row[2],
            "transcript": json.loads(row[3] or "[]"),
            "models": json.loads(row[4] or "[]"),
            "created_at": row[5]
        }
    return None
