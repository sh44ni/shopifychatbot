"""
chat_history.py — Per-session conversation history (in-memory + optional SQLite persistence).
"""

import time
from threading import Lock
from leads import save_chat_message

MAX_MESSAGES = 10          # keep last N messages per session
SESSION_TTL  = 30 * 60    # 30 minutes inactivity before pruning

_sessions: dict = {}       # { session_id: { "messages": [...], "last_active": float } }
_lock = Lock()


def _prune_stale_sessions():
    """Remove sessions inactive for SESSION_TTL seconds."""
    now = time.time()
    stale = [sid for sid, s in _sessions.items() if now - s["last_active"] > SESSION_TTL]
    for sid in stale:
        del _sessions[sid]
    if stale:
        print(f"[History] Pruned {len(stale)} stale session(s)")


def add_message(session_id: str, role: str, content: str):
    """
    Append a message to the session history.
    Trims to the last MAX_MESSAGES entries.
    Persists to SQLite for restart resilience.
    """
    with _lock:
        _prune_stale_sessions()

        if session_id not in _sessions:
            _sessions[session_id] = {"messages": [], "last_active": time.time()}

        session = _sessions[session_id]
        session["messages"].append({"role": role, "content": content})
        session["last_active"] = time.time()

        # Trim to last MAX_MESSAGES
        if len(session["messages"]) > MAX_MESSAGES:
            session["messages"] = session["messages"][-MAX_MESSAGES:]

    # Persist asynchronously (best-effort)
    try:
        save_chat_message(session_id, role, content)
    except Exception as e:
        print(f"[History] Failed to persist message: {e}")


def get_history(session_id: str) -> list[dict]:
    """Return the message list for a session (empty list if not found)."""
    with _lock:
        session = _sessions.get(session_id)
        if session:
            session["last_active"] = time.time()
            return list(session["messages"])
    return []


def clear_session(session_id: str):
    """Clear a specific session (e.g. on explicit reset)."""
    with _lock:
        _sessions.pop(session_id, None)
