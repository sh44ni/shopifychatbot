"""
leads.py — SQLite storage for leads, support cases, and chat history.
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
    """Create all tables if they don't exist."""
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS support_cases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id     TEXT UNIQUE NOT NULL,
                session_id  TEXT DEFAULT '',
                name        TEXT NOT NULL,
                email       TEXT DEFAULT '',
                phone       TEXT DEFAULT '',
                subject     TEXT DEFAULT '',
                description TEXT DEFAULT '',
                status      TEXT DEFAULT 'open',
                notes       TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


# ─── Validation ──────────────────────────────────────────────────────────────

def _validate_email(email: str) -> bool:
    if not email:
        return True
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def _sanitize_phone(phone: str) -> str:
    return re.sub(r"[^\d\+\-\s]", "", phone or "").strip()


def _next_case_id() -> str:
    year = datetime.now().year
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM support_cases").fetchone()[0]
    return f"CASE-{year}-{str(count + 1).zfill(4)}"


# ─── Leads CRUD ───────────────────────────────────────────────────────────────

def save_lead(
    session_id: str,
    name: str,
    email: str = "",
    phone: str = "",
    business_name: str = "",
    inquiry_type: str = "general",
    notes: str = "",
) -> dict:
    if not name or not name.strip():
        return {"success": False, "error": "Name is required"}
    if email and not _validate_email(email):
        return {"success": False, "error": "Invalid email address"}
    if not email and not phone:
        return {"success": False, "error": "At least email or phone is required"}

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """INSERT INTO leads
                   (session_id, name, email, phone, business_name, inquiry_type, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    name.strip(),
                    email.strip().lower(),
                    _sanitize_phone(phone),
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Support Cases CRUD ───────────────────────────────────────────────────────

VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}


def save_case(
    name: str,
    email: str = "",
    phone: str = "",
    subject: str = "",
    description: str = "",
    session_id: str = "",
) -> dict:
    """
    Create a support case. Returns {"success": True, "id": int, "case_id": str}
    or {"success": False, "error": str}.
    """
    if not name or not name.strip():
        return {"success": False, "error": "Name is required"}
    if email and not _validate_email(email):
        return {"success": False, "error": "Invalid email address"}
    if not email and not phone:
        return {"success": False, "error": "Email or phone is required"}

    case_id = _next_case_id()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """INSERT INTO support_cases
                   (case_id, session_id, name, email, phone, subject, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    case_id,
                    session_id,
                    name.strip(),
                    email.strip().lower(),
                    _sanitize_phone(phone),
                    subject.strip(),
                    description.strip(),
                ),
            )
            conn.commit()
            return {"success": True, "id": cursor.lastrowid, "case_id": case_id}
    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}


def get_cases(limit: int = 100, status: str = "") -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if status and status in VALID_STATUSES:
            rows = conn.execute(
                "SELECT * FROM support_cases WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM support_cases ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_case(case_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM support_cases WHERE case_id=?", (case_id,)
        ).fetchone()
    return dict(row) if row else None


def update_case_status(case_id: str, new_status: str, notes: str = "") -> bool:
    if new_status not in VALID_STATUSES:
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if notes:
                conn.execute(
                    """UPDATE support_cases
                       SET status=?, notes=?, updated_at=CURRENT_TIMESTAMP
                       WHERE case_id=?""",
                    (new_status, notes, case_id),
                )
            else:
                conn.execute(
                    """UPDATE support_cases
                       SET status=?, updated_at=CURRENT_TIMESTAMP
                       WHERE case_id=?""",
                    (new_status, case_id),
                )
            conn.commit()
            return True
    except sqlite3.Error:
        return False


# ─── Chat History ─────────────────────────────────────────────────────────────

def save_chat_message(session_id: str, role: str, content: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"[Leads] Error saving chat message: {e}")
