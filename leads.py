"""
leads.py — SQLite lead storage with input validation.
"""

import os
import re
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("LEADS_DB", "leads.db")


# ─── Schema Init ─────────────────────────────────────────────────────────────

def init_db():
    """Create leads and chat_history tables if they don't exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT,
                name          TEXT,
                email         TEXT,
                phone         TEXT,
                business_name TEXT,
                inquiry_type  TEXT,
                notes         TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role       TEXT,
                content    TEXT,
                timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


# ─── Validation ──────────────────────────────────────────────────────────────

def _validate_email(email: str) -> bool:
    if not email:
        return True  # optional field
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def _sanitize_phone(phone: str) -> str:
    """Strip anything that isn't digits, +, -, spaces."""
    return re.sub(r"[^\d\+\-\s]", "", phone or "").strip()


# ─── CRUD ────────────────────────────────────────────────────────────────────

def save_lead(
    session_id: str,
    name: str,
    email: str = "",
    phone: str = "",
    business_name: str = "",
    inquiry_type: str = "general",
    notes: str = "",
) -> dict:
    """
    Validate and insert a lead. Returns {"success": True, "id": int} or
    {"success": False, "error": str}.
    """
    if not name or not name.strip():
        return {"success": False, "error": "Name is required"}

    if email and not _validate_email(email):
        return {"success": False, "error": "Invalid email address"}

    if not email and not phone:
        return {"success": False, "error": "At least email or phone is required"}

    phone_clean = _sanitize_phone(phone)

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """
                INSERT INTO leads (session_id, name, email, phone, business_name, inquiry_type, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    name.strip(),
                    email.strip().lower(),
                    phone_clean,
                    business_name.strip(),
                    inquiry_type.strip().lower(),
                    notes.strip(),
                ),
            )
            conn.commit()
            return {"success": True, "id": cursor.lastrowid}
    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}


def get_leads(limit: int = 100) -> list[dict]:
    """Fetch most recent leads."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_chat_message(session_id: str, role: str, content: str):
    """Persist a chat message to SQLite for restart resilience."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"[Leads] Error saving chat message: {e}")
