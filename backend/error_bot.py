#!/usr/bin/env python3
"""
Error Bot — automated error monitor + self-healing for stdlib backends.

What it does:
- Logs every unhandled exception to SQLite (error_logs) + error_bot.log file
- Tries automatic fixes for KNOWN error patterns (missing table, locked DB,
  missing DB file, etc.)
- Exposes recent errors for the /api/errors admin endpoint
- Never crashes the app: all bot internals are wrapped in try/except

What it is NOT:
- Not a true LLM AI. It cannot write new code for unknown bugs.
  Unknown errors are logged with full traceback + error_id so a human
  (or a future LLM hook) can fix them fast.

Stdlib only: sqlite3, traceback, datetime, threading, os.
"""

import os
import sqlite3
import threading
import traceback
from datetime import datetime, timezone

_lock = threading.Lock()
_db_path = None
_log_file = None
_start_time = datetime.now(timezone.utc)
_total_errors = 0
_auto_fixed = 0


def init_error_bot(db_path, log_file=None):
    """Call once at startup. Creates error_logs table if missing."""
    global _db_path, _log_file
    _db_path = db_path
    _log_file = log_file or os.path.join(os.path.dirname(db_path), "error_bot.log")
    try:
        conn = sqlite3.connect(_db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                path TEXT DEFAULT '',
                method TEXT DEFAULT '',
                traceback TEXT DEFAULT '',
                auto_fixed INTEGER DEFAULT 0,
                fix_action TEXT DEFAULT ''
            )"""
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # bot must never break startup


def _write_log_file(line):
    try:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_error(error_type, message, tb_str="", path="", method="",
              auto_fixed=False, fix_action=""):
    """Persist one error. Returns error_id (int) or 0 on failure."""
    global _total_errors, _auto_fixed
    now = datetime.now(timezone.utc).isoformat()
    eid = 0
    try:
        with _lock:
            _total_errors += 1
            if auto_fixed:
                _auto_fixed += 1
            conn = sqlite3.connect(_db_path)
            cur = conn.execute(
                "INSERT INTO error_logs "
                "(occurred_at, error_type, message, path, method, traceback, auto_fixed, fix_action)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (now, error_type[:200], message[:2000], path[:500],
                 method[:20], tb_str[:8000], 1 if auto_fixed else 0, fix_action[:500]),
            )
            eid = cur.lastrowid
            conn.commit()
            conn.close()
    except Exception:
        pass
    _write_log_file(
        f"[{now}] id={eid} {error_type}: {message} "
        f"path={path} fixed={auto_fixed} action={fix_action}"
    )
    return eid


def try_auto_fix(exc, reinit_db=None):
    """Attempt a fix for known error patterns.

    reinit_db: optional callable that rebuilds the schema (passed by app.py).
    Returns (fixed: bool, action: str).
    """
    name = type(exc).__name__
    msg = str(exc)

    # 1. Missing table -> rebuild schema
    if "no such table" in msg and reinit_db:
        try:
            reinit_db()
            return True, "rebuilt missing tables via schema re-init"
        except Exception as e2:
            return False, f"reinit failed: {e2}"

    # 2. DB file issues -> rebuild
    if isinstance(exc, sqlite3.OperationalError) and (
        "unable to open database file" in msg or "no such file" in msg
    ) and reinit_db:
        try:
            reinit_db()
            return True, "recreated database file via schema re-init"
        except Exception as e2:
            return False, f"db recreate failed: {e2}"

    # 3. Database locked -> advise retry (can't fully fix inline, but log it)
    if "database is locked" in msg:
        return False, "db locked — caller should retry shortly"

    # 4. Disk full / no space
    if "disk" in msg.lower() and "full" in msg.lower():
        return False, "disk full — needs human intervention"

    return False, ""


def handle_exception(exc, path="", method="", reinit_db=None):
    """One-call handler for except blocks.

    Logs the error, tries auto-fix, returns (error_id, was_fixed, fix_action).
    """
    tb_str = traceback.format_exc()
    fixed, action = try_auto_fix(exc, reinit_db=reinit_db)
    eid = log_error(
        type(exc).__name__, str(exc), tb_str,
        path=path, method=method, auto_fixed=fixed, fix_action=action,
    )
    return eid, fixed, action


def get_recent_errors(limit=20):
    """Return recent errors for the admin endpoint. Never raises."""
    try:
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, occurred_at, error_type, message, path, method,"
            " auto_fixed, fix_action FROM error_logs"
            " ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def health_status():
    """For /api/health. Never raises."""
    uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()
    return {
        "ok": True,
        "uptime_seconds": int(uptime),
        "total_errors": _total_errors,
        "auto_fixed": _auto_fixed,
        "bot": "error-bot/1.0 (rule-based self-healing; unknown bugs logged for human fix)",
    }
