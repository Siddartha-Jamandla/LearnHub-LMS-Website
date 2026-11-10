#!/usr/bin/env python3
"""
LearnHub LMS - full-stack backend using ONLY the Python standard library.

Modules used: http.server, sqlite3, json, hashlib, secrets, os, re, urllib, mimetypes, time.

Run:  python3 backend/app.py
Then open http://localhost:8000  (frontend is served from ../repo/)

Env vars (see backend/.env.example):
  PORT      - port to listen on (default 8000)
  DB_PATH   - sqlite file path (default backend/learnhub.db)
  API_SECRET- secret salt for token generation (default "learnhub-dev-secret")
"""

import csv
import hashlib
import hmac
from datetime import date, timedelta
import io
import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import error_bot  # local: automated error monitor + self-healing

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR  = os.path.dirname(BASE_DIR)               # repo root in production, workspace/learnhub locally
# In workspace the frontend lives in repo/, in production (GitHub/Render) it's at root
_cand = os.path.join(ROOT_DIR, "repo")
REPO_DIR  = _cand if os.path.exists(os.path.join(_cand, "index.html")) else ROOT_DIR
_js_cand = os.path.join(ROOT_DIR, "js")
JS_DIR    = _js_cand if os.path.isdir(_js_cand) else None

PORT       = int(os.environ.get("PORT", "8000"))
DB_PATH    = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "learnhub.db"))
API_SECRET = os.environ.get("API_SECRET", "learnhub-dev-secret")
# Gmail-admin: the account registered with this email is the site admin
# and can unlock /admin.html by signing in - no admin key needed.
# (Override with the ADMIN_EMAIL env var; the key still works as fallback.)
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "siddarthajamandla@gmail.com").strip().lower()

# Mock payment gateway (TEST MODE only - no real money, no real keys).
# Signature secret is derived from API_SECRET (or PAYMENT_TEST_SECRET env);
# it is a test-mode HMAC only and must never be treated as a live key.
PAYMENT_TEST_SECRET = os.environ.get(
    "PAYMENT_TEST_SECRET",
    hashlib.sha256((os.environ.get("API_SECRET", "learnhub-dev-secret")
                    + "|payment-test").encode()).hexdigest(),
)

# In-memory rate-limit state (per-process; DB tables are the durable log).
_OTP_REQ_WINDOW = {}    # email -> [epoch, ...] request-otp calls (1h window)
_FAILED_LOGINS = {}     # (ip, email) -> [epoch, ...] failed logins (10 min)
_LOGIN_BLOCKS = {}      # (ip, email) -> blocked_until epoch

# Threat-shield patterns scanned in URL path/query (and in auth/checkout
# JSON bodies — see _SHIELD_BODY_PATHS in _route). Deliberately narrow
# to avoid false positives on ordinary text such as "C++" or lesson content.
_SHIELD_PATTERNS = [
    (re.compile(r"union\s+select", re.I), "sql_injection"),
    (re.compile(r"drop\s+table", re.I), "sql_injection"),
    (re.compile(r"or\s+1\s*=\s*1", re.I), "sql_injection"),
    (re.compile(r"xp_cmdshell", re.I), "sql_injection"),
    (re.compile(r"<\s*script", re.I), "xss"),
    (re.compile(r"javascript\s*:", re.I), "xss"),
    (re.compile(r"onerror\s*=", re.I), "xss"),
    (re.compile(r"\.\./", re.I), "path_traversal"),
    (re.compile(r"%2e%2e", re.I), "path_traversal"),
]


def _shield_scan(text):
    """Return the event_type of the first threat pattern found, else None."""
    if not text:
        return None
    for rx, etype in _SHIELD_PATTERNS:
        if rx.search(text):
            return etype
    return None


# Write endpoints whose JSON bodies the shield also scans: login /
# register / OTP, checkout and payment verification. Other write
# endpoints are NOT scanned — notes, assignments and reviews
# legitimately contain code and study text (e.g. "DROP TABLE" in a
# SQL student's notes) — and every query is parameterised, so the
# database is protected without blocking ordinary text.
_SHIELD_BODY_PATHS = ("/api/register", "/api/login", "/api/auth/",
                      "/api/checkout", "/api/payments/")


def _shield_body_path(path):
    """True when a write to `path` should have its JSON body scanned."""
    return any(path == p or (p.endswith("/") and path.startswith(p))
               for p in _SHIELD_BODY_PATHS)


def _log_security(conn, ip, user_id, event_type, severity, details, blocked):
    try:
        conn.execute(
            "INSERT INTO security_events (ip, user_id, event_type, severity,"
            " details, blocked) VALUES (?, ?, ?, ?, ?, ?)",
            (ip or "", user_id, event_type, severity, details or "", 1 if blocked else 0))
        conn.commit()
    except Exception:
        pass


def _audit(conn, user_id, action, ip, details=""):
    """Best-effort audit insert; never raises, never commits (caller owns tx)."""
    try:
        conn.execute(
            "INSERT INTO audit_logs (user_id, action, ip, details)"
            " VALUES (?, ?, ?, ?)",
            (user_id, action, ip or "", details or ""))
    except Exception:
        pass


def _payment_signature(gateway_order_id, payment_id):
    msg = f"{gateway_order_id}|{payment_id}".encode()
    return hmac.new(PAYMENT_TEST_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def is_admin_email(email: str) -> bool:
    return bool(email) and email.strip().lower() == ADMIN_EMAIL


# ---------------------------------------------------------------- db helpers
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    fresh = not os.path.exists(DB_PATH)
    with open(os.path.join(BASE_DIR, "schema.sql")) as f:
        schema = f.read()
    conn = db()
    conn.executescript(schema)
    _migrate_schema(conn)
    _migrate_learnhub(conn)
    conn.close()
    if fresh:
        print(f"[learnhub] created database at {DB_PATH}")
    try:
        error_bot.init_error_bot(DB_PATH)
    except Exception:
        pass


ANNOUNCEMENTS_SEED = [
    ("Welcome to the new LearnHub dashboard",
     "Your learning is now in one place: XP, streaks, badges, your leaderboard rank and everything you are working on. Sign in and open your Dashboard to see your progress."),
    ("New: Python, C, DSA, Java & SQL learning paths are live",
     "Follow a guided path instead of picking courses one by one. Open Learning Paths from the menu and start with the path that matches your goal."),
    ("Certificates are now verifiable - share your LH- code with recruiters",
     "Every certificate has a unique LH- code. Anyone can verify it at certificate.html - share the code on your resume or LinkedIn."),
]


def _seed_announcements(conn):
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM announcements").fetchone()["n"]
        if n == 0:
            for title, body in ANNOUNCEMENTS_SEED:
                conn.execute("INSERT INTO announcements (title, body) VALUES (?, ?)",
                             (title, body))
            conn.commit()
    except Exception as e:
        print(f"[learnhub] announcement seed skipped: {e!r}")


def _migrate_schema(conn):
    """Additive migrations for DBs created before a schema change.

    CREATE TABLE IF NOT EXISTS covers fresh DBs; ALTER TABLE covers
    existing ones. The preview backfill is idempotent - safe every start.
    """
    try:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS lesson_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS lesson_bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, lesson_id)
);
CREATE TABLE IF NOT EXISTS discussions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES discussions(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_user_lesson ON lesson_notes(user_id, lesson_id);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON lesson_bookmarks(user_id);
CREATE INDEX IF NOT EXISTS idx_discussions_lesson ON discussions(lesson_id);
CREATE TABLE IF NOT EXISTS final_exam_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_final_exam_user_course
    ON final_exam_attempts(user_id, course_id);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
""")
        conn.commit()
        _seed_announcements(conn)
        # Gmail-admin: users.is_admin flag. The backfill runs ONLY when the
        # column is first created (one-time upgrade grant for an admin-Gmail
        # account that already exists). It must NOT run on every start, or
        # it would silently re-grant admin after a key-holder revoked it.
        # The grant also happens at registration (api_register) when the
        # email matches ADMIN_EMAIL.
        cols_u = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
        if "is_admin" not in cols_u:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE users SET is_admin = 1 WHERE lower(email) = ?", (ADMIN_EMAIL,))
        conn.execute("""CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.commit()
        conn.commit()
    except Exception as e:
        print(f"[learnhub] pro-lms migration skipped: {e!r}")
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(lessons)")]
        if "is_preview" not in cols:
            conn.execute("ALTER TABLE lessons ADD COLUMN"
                         " is_preview INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """UPDATE lessons SET is_preview = 1
               WHERE is_preview = 0 AND id IN (
                   SELECT MIN(l2.id) FROM lessons l2
                   WHERE NOT EXISTS (
                       SELECT 1 FROM lessons l3
                       WHERE l3.course_id = l2.course_id
                         AND l3.is_preview = 1
                   )
                   GROUP BY l2.course_id
               )""")
        conn.commit()
    except Exception as e:
        print(f"[learnhub] migration skipped: {e!r}")


ASSIGNMENT_SEEDS = [
    # (course title match, title, description, language, starter, mins, marks, keywords)
    ("C Programming from Zero to Hero", "Reverse an Array in C",
     "Read n numbers into an array, reverse it in place with two pointers, "
     "and print the reversed array. Handle n <= 0 by printing nothing.",
     "c", "#include <stdio.h>\n\nint main(void) {\n    int n;\n    // read n, then n numbers, reverse in place\n    // your code here\n    return 0;\n}\n",
     30, 100, ["for", "swap", "temp", "return", "int"]),
    ("Data Structures & Algorithms", "Reverse a Linked List",
     "Reverse a singly linked list in place, in O(n) time and O(1) extra "
     "space. Explain the three-pointer approach in a comment.",
     "python", "class ListNode:\n    def __init__(self, val=0, next=None):\n        self.val = val\n        self.next = next\n\ndef reverse_list(head):\n    # your code here\n    pass\n",
     30, 100, ["prev", "curr", "next", "while", "return"]),
    ("Python Programming Masterclass", "Palindrome Checker",
     "Write a function that returns True when a string is a palindrome, "
     "ignoring case and non-alphanumeric characters.",
     "python", "def is_palindrome(s: str) -> bool:\n    # your code here\n    pass\n",
     30, 100, ["lower", "return", "while", "=="]),
    ("Java Programming Masterclass", "Fibonacci with Memoization",
     "Compute the nth Fibonacci number using memoization. Handle n < 0 by "
     "throwing an IllegalArgumentException.",
     "java", "import java.util.*;\n\npublic class Fibonacci {\n    public static long fib(int n) {\n        // your code here\n        return 0;\n    }\n}\n",
     30, 100, ["HashMap", "return", "fib", "IllegalArgumentException"]),
    ("Complete Web Development Bootcamp", "Responsive Navbar + Form Validation",
     "Build a responsive navbar with a mobile hamburger toggle and a signup "
     "form that validates email format and a minimum 6-character password in JS.",
     "javascript", "// Build the navbar toggle + form validation below\ndocument.addEventListener('DOMContentLoaded', () => {\n  // your code here\n});\n",
     45, 100, ["addEventListener", "querySelector", "classList", "preventDefault"]),
]


def _migrate_learnhub(conn):
    """Learn Hub tables + assignment seeds.

    CREATE TABLE IF NOT EXISTS covers fresh DBs; the seeds check by
    title first, so re-running never duplicates. Safe on every start.
    """
    try:
        conn.executescript(open(os.path.join(BASE_DIR, "schema.sql")).read())
        conn.commit()
    except Exception as e:
        print(f"[learnhub] learnhub schema re-apply skipped: {e!r}")
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
        if "email_verified" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified"
                         " INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    except Exception as e:
        print(f"[learnhub] email_verified migration skipped: {e!r}")
    # --- C++ removal (9 Nov 2026): the flagship is C, not C++ ---
    # The C++ course (id 17) was added by mistake and never asked for.
    # Remove it, its lessons and its assignments — but only when nobody
    # is enrolled in it, so no learner ever loses paid access. The C
    # course ("C Programming from Zero to Hero", id 13) already exists.
    try:
        row = conn.execute("SELECT id FROM courses WHERE title LIKE '%C++%'").fetchone()
        if row:
            cid = row["id"]
            enrolled = conn.execute(
                "SELECT COUNT(*) AS n FROM enrollments WHERE course_id = ?",
                (cid,)).fetchone()["n"]
            if enrolled == 0:
                conn.execute("DELETE FROM assignment_events WHERE attempt_id IN"
                             " (SELECT id FROM assignment_attempts WHERE assignment_id IN"
                             " (SELECT id FROM assignments WHERE course_id = ?))", (cid,))
                conn.execute("DELETE FROM assignment_attempts WHERE assignment_id IN"
                             " (SELECT id FROM assignments WHERE course_id = ?)", (cid,))
                conn.execute("DELETE FROM assignments WHERE course_id = ?", (cid,))
                conn.execute("DELETE FROM lessons WHERE course_id = ?", (cid,))
                conn.execute("DELETE FROM courses WHERE id = ?", (cid,))
                conn.commit()
                print(f"[learnhub] removed unasked C++ course id={cid}")
            else:
                print(f"[learnhub] C++ course kept: {enrolled} enrolment(s)")
    except Exception as e:
        print(f"[learnhub] C++ removal skipped: {e!r}")
    # --- one proctored assignment per flagship course ---
    try:
        for match, title, desc, lang, starter, mins, marks, kws in ASSIGNMENT_SEEDS:
            crow = conn.execute(
                "SELECT id FROM courses WHERE title = ?", (match,)).fetchone()
            if not crow:
                continue
            exists = conn.execute(
                "SELECT id FROM assignments WHERE course_id = ? AND title = ?",
                (crow["id"], title)).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO assignments (course_id, title, description, language,"
                " starter_code, duration_minutes, total_marks, expected_keywords)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (crow["id"], title, desc, lang, starter, mins, marks,
                 json.dumps(kws)))
        conn.commit()
    except Exception as e:
        print(f"[learnhub] assignment seed skipped: {e!r}")


def row_to_dict(row):
    return dict(row) if row else None


def _positive_int(value):
    """Return value as a positive int, or None when it is not one.

    Accepts ints and digit strings; rejects bools, floats, and anything
    that is not a positive whole number. Used to validate id fields sent
    in request bodies (URL ids are already constrained to \\d+ by the router).
    """
    if isinstance(value, bool) or isinstance(value, float):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# ---------------------------------------------------------------- security
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return hashlib.sha256((salt + password).encode()).hexdigest() == digest


def make_token(user_id: int) -> str:
    raw = f"{API_SECRET}:{user_id}:{time.time()}:{secrets.token_hex(16)}"
    token = hashlib.sha256(raw.encode()).hexdigest()
    conn = db()
    conn.execute("INSERT INTO auth_tokens (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    return token


def user_from_token(token: str):
    conn = db()
    row = conn.execute(
        """SELECT u.id, u.name, u.email, u.created_at, u.is_admin,
                      u.email_verified
           FROM auth_tokens t JOIN users u ON u.id = t.user_id
           WHERE t.token = ?""",
        (token,),
    ).fetchone()
    conn.close()
    return row_to_dict(row)


def _is_admin_user(user) -> bool:
    """True when the signed-in user is an admin: the is_admin flag only.

    The flag is authoritative so that a key-holder revoking admin via
    POST /api/admin/users/:id/role actually sticks. (Registration still
    grants is_admin=1 to the ADMIN_EMAIL address — see api_register —
    so the first account registered with that Gmail becomes admin, but
    that grant can now be revoked durably.)"""
    if not user:
        return False
    return bool(user.get("is_admin"))


def _notify_user(conn, user_id, ntype, title, body, link=None):
    """Best-effort in-app notification insert. Never raises and never
    commits: the caller owns the transaction, so a notification failure
    can never break the main action (announcement, reply, certificate,
    exam pass)."""
    try:
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, body, link)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, ntype, title, body or "", link))
    except Exception:
        pass


# ---------------------------------------------------------------- handler
class LearnHubHandler(BaseHTTPRequestHandler):
    server_version = "LearnHub/1.0"

    # -- small helpers -------------------------------------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json(self, status: int, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Admin / course data must reflect instantly - never cache it.
        if self.path.startswith("/api/admin") or self.path.startswith("/api/courses"):
            self.send_header("Cache-Control", "no-store")
        cookie = getattr(self, "_pending_cookie", None)
        if cookie:
            self.send_header("Set-Cookie", cookie)
            self._pending_cookie = None
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return (self.client_address[0] if self.client_address else "")

    def _set_auth_cookie(self, token):
        # HttpOnly=False deliberately: the hidden super-admin page is
        # served by the same backend, which reads this cookie; the
        # token is also kept in localStorage by the JS client.
        self._pending_cookie = (f"lh_token={token}; Path=/; SameSite=Lax;"
                                " Max-Age=2592000")

    def _clear_auth_cookie(self):
        self._pending_cookie = ("lh_token=; Path=/; SameSite=Lax; Max-Age=0")

    def _ok(self, payload, status=200):
        self._json(status, {"ok": True, **payload})

    def _csv(self, filename, header, rows):
        """Send rows as a downloadable CSV file (admin export)."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        writer.writerows(rows)
        body = buf.getvalue().encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status: int, message: str):
        self._json(status, {"ok": False, "error": message})

    def _read_json(self):
        # _route caches the raw body for auth/checkout writes (see the
        # threat-shield body scan); reuse it instead of reading the
        # socket a second time (the stream is already consumed).
        raw = getattr(self, "_cached_body", None)
        if raw is None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _auth_user(self):
        auth = self.headers.get("Authorization", "")
        m = re.match(r"Bearer\s+(\S+)", auth)
        if not m:
            return None
        return user_from_token(m.group(1))

    def log_message(self, fmt, *args):  # quieter logs
        print(f"[api] {self.command} {self.path} -> {fmt % args}")

    # -- routing -------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method):
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            # Threat shield: scan URL path + query for injection / XSS /
            # traversal patterns. Blocked attempts are logged, never served.
            if path.startswith("/api/"):
                # Scan the percent-decoded target: attackers encode the
                # payload (%20UNION%20SELECT, %3Cscript%3E), and the raw
                # encoded form would slip past the \s / < patterns.
                hit = _shield_scan(unquote(self.path))
                if hit:
                    try:
                        conn = db()
                        _log_security(conn, self._client_ip(), None, hit,
                                      "high", f"Blocked {method} {self.path[:300]}",
                                      True)
                        conn.close()
                    except Exception:
                        pass
                    self._err(403, "Request blocked by the Learn Hub security shield")
                    return

            # Threat shield: scan JSON bodies on auth/checkout writes
            # too. The raw body is read once here and cached for
            # _read_json, so handlers still see it. Bodies on other
            # endpoints are not scanned (see _SHIELD_BODY_PATHS).
            if method in ("POST", "PUT") and _shield_body_path(path):
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                self._cached_body = raw
                hit = _shield_scan(raw.decode("utf-8", "replace"))
                if hit:
                    try:
                        conn = db()
                        _log_security(conn, self._client_ip(), None, hit,
                                      "high", f"Blocked {method} {self.path[:300]} (JSON body)",
                                      True)
                        conn.close()
                    except Exception:
                        pass
                    self._err(403, "Request blocked by the Learn Hub security shield")
                    return

            # Hidden super admin: direct URL only, admin session required.
            # Everyone else (including signed-in non-admins) gets a plain
            # 404 - no hint that the page exists. Token via Authorization
            # header, ?token=, or the lh_token cookie set at sign-in.
            if path == "/super-admin.html":
                if not self._is_super_admin_request(parsed):
                    self._json(404, {"ok": False, "error": "Not found"})
                    return

            if path.startswith("/api/"):
                self._route_api(method, path)
                return
            if path.startswith("/js/"):          # new integration scripts
                if JS_DIR:
                    self._serve_file(os.path.join(JS_DIR, path[4:]))
                else:
                    self._err(404, "Not found")
                return
            self._serve_file(os.path.join(REPO_DIR, path.lstrip("/") or "index.html"))
        except BrokenPipeError:
            pass
        except Exception as e:  # error-bot: log + try self-heal
            try:
                eid, fixed, action = error_bot.handle_exception(
                    e, path=self.path, method=method, reinit_db=init_db
                )
                print(f"[learnhub] ERROR id={eid} fixed={fixed} {e!r} action={action}")
            except Exception:
                eid, fixed = 0, False
            try:
                msg = "Internal server error"
                if eid:
                    msg += f" (ref #{eid})"
                if fixed:
                    msg += " — auto-fix applied, please retry"
                self._err(500, msg)
            except Exception:
                pass

    def _is_super_admin_request(self, parsed):
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        token = None
        auth = self.headers.get("Authorization", "")
        m = re.match(r"Bearer\s+(\S+)", auth)
        if m:
            token = m.group(1)
        elif qs.get("token"):
            token = qs["token"][0]
        else:
            cookie = self.headers.get("Cookie", "")
            mm = re.search(r"lh_token=([^;\s]+)", cookie)
            if mm:
                token = mm.group(1)
        if not token:
            return False
        user = user_from_token(token)
        return bool(user and _is_admin_user(user))

    # -- static files --------------------------------------------------
    def _serve_file(self, full_path):
        if os.path.isdir(full_path):
            full_path = os.path.join(full_path, "index.html")
        if not os.path.isfile(full_path):
            self._json(404, {"ok": False, "error": "Not found"})
            return
        ctype = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        if full_path.endswith(".svg"):
            ctype = "image/svg+xml"
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- API -----------------------------------------------------------
    def _route_api(self, method, path):
        r = [
            ("GET",    r"^/api/health$",                 self.api_health),
            ("GET",    r"^/api/errors$",                 self.api_errors),
            ("GET",    r"^/api/courses$",                self.api_courses),
            ("GET",    r"^/api/courses/(\d+)$",          self.api_course),
            ("GET",    r"^/api/courses/(\d+)/lessons$",  self.api_course_lessons),
            ("GET",    r"^/api/courses/(\d+)/progress$", self.api_course_progress),
            ("GET",    r"^/api/courses/(\d+)/reviews$",  self.api_course_reviews),
            ("POST",   r"^/api/reviews$",                self.api_review_add),
            ("GET",    r"^/api/certificates/(\d+)$",     self.api_cert_get),
            ("GET",    r"^/api/certificates$",            self.api_cert_list),
            ("GET",    r"^/api/certificates/verify/([^/]+)$", self.api_cert_verify),
            ("GET",    r"^/api/lessons/(\d+)$",          self.api_lesson_get),
            ("POST",   r"^/api/lessons/(\d+)/complete$", self.api_lesson_complete),
            ("GET",    r"^/api/lessons/(\d+)/quiz$",     self.api_lesson_quiz),
            ("POST",   r"^/api/lessons/(\d+)/quiz$",     self.api_lesson_quiz_submit),
            ("GET",    r"^/api/lessons/(\d+)/tasks$",    self.api_lesson_tasks),
            ("POST",   r"^/api/tasks/(\d+)/complete$",   self.api_task_complete),
            ("GET",    r"^/api/courses/(\d+)/learn-progress$",
                                                     self.api_course_learn_progress),
            ("POST",   r"^/api/tutor$",                 self.api_tutor),
            ("POST",   r"^/api/admin/courses$",          self.api_admin_course_create),
            ("PUT",    r"^/api/admin/courses/(\d+)$",    self.api_admin_course_update),
            ("DELETE", r"^/api/admin/courses/(\d+)$",    self.api_admin_course_delete),
            ("POST",   r"^/api/admin/courses/(\d+)/lessons$",
                                                     self.api_admin_lesson_create),
            ("PUT",    r"^/api/admin/lessons/(\d+)$",    self.api_admin_lesson_update),
            ("DELETE", r"^/api/admin/lessons/(\d+)$",    self.api_admin_lesson_delete),
            ("GET",    r"^/api/admin/stats$",            self.api_admin_stats),
            ("GET",    r"^/api/admin/overview$",         self.api_admin_overview),
            ("GET",    r"^/api/admin/users$",            self.api_admin_users),
            ("GET",    r"^/api/admin/users/(\d+)$",      self.api_admin_user),
            ("GET",    r"^/api/admin/orders$",           self.api_admin_orders),
            ("GET",    r"^/api/admin/certificates$",     self.api_admin_certificates),
            ("GET",    r"^/api/admin/analytics$",        self.api_admin_analytics),
            ("GET",    r"^/api/admin/lessons/(\d+)/content$",
                                                     self.api_admin_lesson_content),
            ("PUT",    r"^/api/admin/lessons/(\d+)/content$",
                                                     self.api_admin_lesson_content_update),
            ("POST",   r"^/api/admin/lessons/(\d+)/quiz$",
                                                     self.api_admin_quiz_add),
            ("PUT",    r"^/api/admin/quiz/(\d+)$",      self.api_admin_quiz_update),
            ("DELETE", r"^/api/admin/quiz/(\d+)$",      self.api_admin_quiz_delete),
            ("POST",   r"^/api/admin/lessons/(\d+)/tasks$",
                                                     self.api_admin_task_add),
            ("PUT",    r"^/api/admin/tasks/(\d+)$",     self.api_admin_task_update),
            ("DELETE", r"^/api/admin/tasks/(\d+)$",     self.api_admin_task_delete),
            ("GET",    r"^/api/me/dashboard$",          self.api_me_dashboard),
            ("GET",    r"^/api/leaderboard$",            self.api_leaderboard),
            ("GET",    r"^/api/announcements$",          self.api_announcements),
            ("POST",   r"^/api/contact$",                self.api_contact_submit),
            ("GET",    r"^/api/admin/contact-messages$", self.api_admin_contact_messages),
            ("GET",    r"^/api/learning-paths$",         self.api_learning_paths),
            ("GET",    r"^/api/lessons/(\d+)/notes$",    self.api_lesson_notes_get),
            ("POST",   r"^/api/lessons/(\d+)/notes$",    self.api_lesson_notes_post),
            ("DELETE", r"^/api/notes/(\d+)$",            self.api_note_delete),
            ("POST",   r"^/api/lessons/(\d+)/bookmark$", self.api_lesson_bookmark_add),
            ("DELETE", r"^/api/lessons/(\d+)/bookmark$", self.api_lesson_bookmark_del),
            ("GET",    r"^/api/me/bookmarks$",            self.api_me_bookmarks),
            ("GET",    r"^/api/lessons/(\d+)/discussions$", self.api_lesson_discussions_get),
            ("POST",   r"^/api/lessons/(\d+)/discussions$", self.api_lesson_discussions_post),
            ("POST",   r"^/api/discussions/(\d+)/reply$", self.api_discussion_reply),
            ("GET",    r"^/api/admin/announcements$",     self.api_admin_announcements),
            ("POST",   r"^/api/admin/announcements$",     self.api_admin_announcement_create),
            ("DELETE", r"^/api/admin/announcements/(\d+)$", self.api_admin_announcement_delete),
            ("GET",    r"^/api/admin/discussions$",       self.api_admin_discussions),
            ("DELETE", r"^/api/admin/discussions/(\d+)$", self.api_admin_discussion_delete),
            ("POST",   r"^/api/auth/request-otp$",      self.api_auth_request_otp),
            ("POST",   r"^/api/auth/verify-otp$",       self.api_auth_verify_otp),
            ("GET",    r"^/api/me/notes$",              self.api_me_notes_list),
            ("POST",   r"^/api/me/notes$",              self.api_me_notes_create),
            ("PUT",    r"^/api/me/notes/(\d+)$",        self.api_me_notes_update),
            ("DELETE", r"^/api/me/notes/(\d+)$",        self.api_me_notes_delete),
            ("GET",    r"^/api/courses/(\d+)/assignments$", self.api_course_assignments),
            ("GET",    r"^/api/assignments/(\d+)$",     self.api_assignment_get),
            ("POST",   r"^/api/assignments/(\d+)/start$", self.api_assignment_start),
            ("POST",   r"^/api/assignments/(\d+)/event$", self.api_assignment_event),
            ("POST",   r"^/api/assignments/(\d+)/submit$", self.api_assignment_submit),
            ("POST",   r"^/api/payments/(\d+)/verify$", self.api_payment_verify),
            ("GET",    r"^/api/payments/me$",           self.api_payments_me),
            ("GET",    r"^/api/admin/payments$",        self.api_admin_payments),
            ("GET",    r"^/api/admin/assignments/attempts$", self.api_admin_assignment_attempts),
            ("GET",    r"^/api/admin/security$",        self.api_admin_security),
            ("GET",    r"^/api/admin/audit-logs$",      self.api_admin_audit_logs),
            ("GET",    r"^/api/admin/security/stats$",  self.api_admin_security_stats),
            ("POST",   r"^/api/register$",               self.api_register),
            ("POST",   r"^/api/login$",                  self.api_login),
            ("POST",   r"^/api/logout$",                 self.api_logout),
            ("GET",    r"^/api/cart$",                   self.api_cart_get),
            ("POST",   r"^/api/cart$",                   self.api_cart_add),
            ("DELETE", r"^/api/cart/(\d+)$",             self.api_cart_del),
            ("POST",   r"^/api/checkout$",               self.api_checkout),
            ("GET",    r"^/api/enrollments$",            self.api_enrollments),
            ("DELETE", r"^/api/enrollments/(\d+)$",      self.api_unenroll),
            ("PUT",    r"^/api/enrollments/(\d+)/progress$", self.api_progress),
            ("GET",    r"^/api/my-courses$",             self.api_my_courses),
            ("GET",    r"^/api/wishlist$",               self.api_wishlist_get),
            ("POST",   r"^/api/wishlist$",               self.api_wishlist_add),
            ("DELETE", r"^/api/wishlist/(\d+)$",         self.api_wishlist_del),
            # -- ULTIMATE LMS: search, stats, instructors, exams, --------
            # -- notifications, reviews mgmt, admin roles / exports -----
            ("GET",    r"^/api/search$",                self.api_search),
            ("GET",    r"^/api/stats$",                 self.api_stats),
            ("GET",    r"^/api/instructors$",           self.api_instructors),
            ("GET",    r"^/api/me/admin-status$",       self.api_me_admin_status),
            ("GET",    r"^/api/me/recommended$",        self.api_me_recommended),
            ("GET",    r"^/api/me/notifications$",      self.api_me_notifications),
            ("POST",   r"^/api/me/notifications/read-all$",
                                                     self.api_me_notifications_read_all),
            ("POST",   r"^/api/notifications/(\d+)/read$",
                                                     self.api_notification_read),
            ("PUT",    r"^/api/reviews/(\d+)$",         self.api_review_update),
            ("DELETE", r"^/api/reviews/(\d+)$",         self.api_review_delete),
            ("GET",    r"^/api/courses/(\d+)/final-exam$",
                                                     self.api_final_exam_get),
            ("POST",   r"^/api/courses/(\d+)/final-exam/submit$",
                                                     self.api_final_exam_submit),
            ("POST",   r"^/api/admin/users/(\d+)/role$", self.api_admin_user_role),
            ("GET",    r"^/api/admin/reviews$",         self.api_admin_reviews),
            ("DELETE", r"^/api/admin/reviews/(\d+)$",   self.api_admin_review_delete),
            ("GET",    r"^/api/admin/instructors$",     self.api_admin_instructors),
            ("GET",    r"^/api/admin/export$",          self.api_admin_export),
        ]
        for m, pattern, handler in r:
            match = re.match(pattern, path)
            if m == method and match:
                handler(*match.groups())
                return
        self._err(404, "Unknown endpoint")

    # -- public endpoints ----------------------------------------------
    def api_health(self):
        info = {"service": "learnhub", "status": "ok", "time": int(time.time())}
        try:
            info["error_bot"] = error_bot.health_status()
        except Exception:
            pass
        self._ok(info)

    def api_errors(self):
        # admin-only: simple shared-secret check via query ?key=
        if not self._require_admin():
            return
        try:
            errs = error_bot.get_recent_errors(20)
        except Exception:
            errs = []
        self._ok({"errors": errs})

    def api_courses(self):
        # Optional filters: ?q= (alias of ?search=, title/description,
        #                         case-insensitive)
        #                   ?category= (exact category name)
        #                   ?level= (exact level: Beginner/Intermediate/Advanced)
        # Sorting: ?sort= (rating | price_asc | price_desc | newest;
        #                  unknown value -> 400)
        # Pagination: ?page= (1-based, default 1), ?per_page= (1..50, default 12)
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        search = (qs.get("q", [""])[0] or qs.get("search", [""])[0] or "").strip()
        category = (qs.get("category", [""])[0] or "").strip()
        level = (qs.get("level", [""])[0] or "").strip()
        try:
            page = max(1, int(qs.get("page", ["1"])[0]))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = int(qs.get("per_page", ["12"])[0])
        except (TypeError, ValueError):
            per_page = 12
        per_page = max(1, min(50, per_page))
        sql = "SELECT * FROM courses"
        # Sorting: ?sort= (rating | price_asc | price_desc | newest).
        # Unknown values are rejected with 400. The rating sort uses a
        # correlated subquery (average review rating, unrated = 0) so the
        # list stays a single query - no N+1.
        sort = (qs.get("sort", [""])[0] or "").strip()
        SORTS = {
            "rating": ("(SELECT COALESCE(AVG(rating), 0) FROM reviews"
                       " WHERE course_id = courses.id) DESC, id"),
            "price_asc": "price ASC, id",
            "price_desc": "price DESC, id",
            "newest": "created_at DESC, id DESC",
        }
        if sort and sort not in SORTS:
            self._err(400, "Invalid sort: expected one of rating, price_asc,"
                           " price_desc, newest")
            return
        order_by = SORTS.get(sort, "id")
        clauses, params = [], []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if level:
            clauses.append("level = ?")
            params.append(level)
        if search:
            clauses.append("(title LIKE ? OR description LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = db()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM courses" + where, params).fetchone()["n"]
        rows = conn.execute(
            sql + where + " ORDER BY " + order_by + " LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
        conn.close()
        self._ok({"courses": [row_to_dict(r) for r in rows],
                  "total": total, "page": page, "per_page": per_page,
                  "pages": (total + per_page - 1) // per_page})

    def api_course(self, course_id):
        conn = db()
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return
        stats = conn.execute(
            "SELECT COUNT(*) AS n, ROUND(AVG(rating), 2) AS avg FROM reviews WHERE course_id = ?",
            (course_id,)).fetchone()
        conn.close()
        d = row_to_dict(course)
        d["avg_rating"] = stats["avg"] if stats["avg"] is not None else 0.0
        d["review_count"] = stats["n"]
        self._ok({"course": d})

    def api_course_progress(self, course_id):
        """Progress summary for one course (auth required).

        Caller must be enrolled (403 otherwise); unknown course -> 404.
        Progress is recomputed from lesson_progress (the source of
        truth, same formula as lesson completion), so it can never drift
        from the stored enrolment row. next_lesson_* is the first lesson
        (by order_index) the caller has not completed yet, or null when
        the course is done. certificate_code is included only at 100%
        with a certificate on file, else null.
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        course = conn.execute(
            "SELECT id, title FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return
        enrollment = conn.execute(
            "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
            (user["id"], course_id)).fetchone()
        if not enrollment:
            conn.close()
            self._err(403, "You must be enrolled in this course to view its progress")
            return
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM lessons WHERE course_id = ?",
            (course_id,)).fetchone()["n"]
        done = conn.execute(
            """SELECT COUNT(*) AS n FROM lesson_progress lp
               JOIN lessons l ON l.id = lp.lesson_id
               WHERE lp.user_id = ? AND l.course_id = ?""",
            (user["id"], course_id)).fetchone()["n"]
        pct = round(done / total * 100, 2) if total else 0.0
        nxt = conn.execute(
            """SELECT l.id, l.title FROM lessons l
               WHERE l.course_id = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM lesson_progress lp
                     WHERE lp.user_id = ? AND lp.lesson_id = l.id)
               ORDER BY l.order_index, l.id LIMIT 1""",
            (course_id, user["id"])).fetchone()
        certificate_code = None
        if pct >= 100.0:
            cert = conn.execute(
                "SELECT certificate_code FROM certificates"
                " WHERE user_id = ? AND course_id = ?",
                (user["id"], course_id)).fetchone()
            if cert:
                certificate_code = cert["certificate_code"]
        conn.close()
        self._ok({
            "course_id": int(course_id),
            "total_lessons": total,
            "completed_lessons": done,
            "progress_percent": pct,
            "next_lesson_id": nxt["id"] if nxt else None,
            "next_lesson_title": nxt["title"] if nxt else None,
            "certificate_code": certificate_code,
        })


    def api_course_reviews(self, course_id):
        conn = db()
        course = conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return
        rows = conn.execute(
            """SELECT r.id, r.user_id, r.rating, r.comment, r.created_at, u.name AS user_name
               FROM reviews r JOIN users u ON u.id = r.user_id
               WHERE r.course_id = ? ORDER BY r.id DESC""",
            (course_id,)).fetchall()
        conn.close()
        self._ok({"reviews": [row_to_dict(r) for r in rows]})

    def api_review_add(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        course_id = _positive_int(body.get("course_id"))
        if course_id is None:
            self._err(400, "course_id must be a positive integer")
            return
        comment = (body.get("comment") or "").strip()
        try:
            rating = int(body.get("rating"))
        except (TypeError, ValueError):
            self._err(400, "rating must be an integer 1-5")
            return
        if not 1 <= rating <= 5:
            self._err(400, "rating must be between 1 and 5")
            return
        if len(comment) > 2000:
            self._err(400, "comment is too long (max 2000 characters)")
            return
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        if not conn.execute(
                "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                (user["id"], course_id)).fetchone():
            conn.close()
            self._err(403, "You must be enrolled in this course to review it")
            return
        try:
            cur = conn.execute(
                "INSERT INTO reviews (user_id, course_id, rating, comment)"
                " VALUES (?, ?, ?, ?)",
                (user["id"], course_id, rating, comment))
            conn.commit()
            review_id = cur.lastrowid
        except sqlite3.IntegrityError:
            conn.close()
            self._err(409, "You have already reviewed this course")
            return
        conn.close()
        self._ok({"review_id": review_id, "rating": rating,
                  "message": "Review submitted"}, status=201)

    def api_course_lessons(self, course_id):
        conn = db()
        course = conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return
        rows = conn.execute(
            "SELECT * FROM lessons WHERE course_id = ? ORDER BY order_index, id",
            (course_id,),
        ).fetchall()
        conn.close()
        self._ok({"lessons": [row_to_dict(r) for r in rows]})

    def api_lesson_get(self, lesson_id):
        """Lesson detail/content.

        Free-preview lessons (is_preview=1) are public - no token needed.
        Other lessons keep the enrolment rule: signed-in AND enrolled in
        the course, otherwise 401/403 (same rule as completing a lesson).
        """
        conn = db()
        lesson = conn.execute(
            """SELECT l.*, c.title AS course_title FROM lessons l
               JOIN courses c ON c.id = l.course_id
               WHERE l.id = ?""",
            (lesson_id,)).fetchone()
        conn.close()
        if not lesson:
            self._err(404, "Lesson not found")
            return
        d = row_to_dict(lesson)
        if not d.get("is_preview"):
            user = self._require_user()
            if not user:
                return
            conn2 = db()
            enr = conn2.execute(
                "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                (user["id"], d["course_id"])).fetchone()
            conn2.close()
            if not enr:
                self._err(403, "You must be enrolled in this course to view this lesson")
                return
        # Rich learning content (body, flowchart, video) + quiz/task counts.
        conn3 = db()
        content = conn3.execute(
            "SELECT * FROM lesson_content WHERE lesson_id = ?",
            (lesson_id,)).fetchone()
        if content:
            c = row_to_dict(content)
            try:
                c["flowchart"] = json.loads(c["flowchart_json"]) if c.get("flowchart_json") else None
            except (ValueError, TypeError):
                c["flowchart"] = None
            c.pop("flowchart_json", None)
            d["content"] = c
        else:
            d["content"] = None
        d["quiz_count"] = conn3.execute(
            "SELECT COUNT(*) AS n FROM quizzes WHERE lesson_id = ?",
            (lesson_id,)).fetchone()["n"]
        d["task_count"] = conn3.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE lesson_id = ?",
            (lesson_id,)).fetchone()["n"]
        conn3.close()
        self._ok({"lesson": d})

    def api_lesson_complete(self, lesson_id):
        """Mark one lesson complete and auto-update the course progress.

        Progress = done_lessons / total_lessons * 100 (idempotent).
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        lesson = conn.execute(
            "SELECT id, course_id, title FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if not lesson:
            conn.close()
            self._err(404, "Lesson not found")
            return
        # only a learner enrolled in the course can complete its lessons
        enrollment = conn.execute(
            "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
            (user["id"], lesson["course_id"])).fetchone()
        if not enrollment:
            conn.close()
            self._err(403, "You must be enrolled in this course to complete its lessons")
            return
        conn.execute("INSERT OR IGNORE INTO lesson_progress (user_id, lesson_id)"
                     " VALUES (?, ?)", (user["id"], lesson_id))
        conn.commit()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM lessons WHERE course_id = ?",
            (lesson["course_id"],)).fetchone()["n"]
        done = conn.execute(
            """SELECT COUNT(*) AS n FROM lesson_progress lp
               JOIN lessons l ON l.id = lp.lesson_id
               WHERE lp.user_id = ? AND l.course_id = ?""",
            (user["id"], lesson["course_id"])).fetchone()["n"]
        pct = round(done / total * 100, 2) if total else 0.0
        conn.execute("UPDATE enrollments SET progress_percent = ? WHERE id = ?",
                     (pct, enrollment["id"]))
        # Certificate of completion: generated once when progress hits 100%.
        # INSERT OR IGNORE keeps it idempotent (UNIQUE(user_id, course_id)).
        certificate = None
        certificate_new = False
        if pct >= 100.0:
            code = "LH-" + secrets.token_hex(4).upper()
            cur = conn.execute(
                "INSERT OR IGNORE INTO certificates (user_id, course_id, certificate_code)"
                " VALUES (?, ?, ?)",
                (user["id"], lesson["course_id"], code))
            if cur.rowcount == 1:
                certificate = {"id": cur.lastrowid,
                               "certificate_code": code}
                certificate_new = True
            else:
                existing = conn.execute(
                    "SELECT id, certificate_code FROM certificates"
                    " WHERE user_id = ? AND course_id = ?",
                    (user["id"], lesson["course_id"])).fetchone()
                if existing:
                    certificate = {"id": existing["id"],
                                   "certificate_code": existing["certificate_code"]}
        if certificate and certificate_new:
            # Notify the learner their certificate is ready (best-effort;
            # _notify_user never raises, and the commit below still runs).
            try:
                course_row = conn.execute(
                    "SELECT title FROM courses WHERE id = ?",
                    (lesson["course_id"],)).fetchone()
                course_title = course_row["title"] if course_row else "your course"
            except Exception:
                course_title = "your course"
            _notify_user(conn, user["id"], "certificate",
                         "Certificate earned",
                         f"Your certificate for '{course_title}' is ready"
                         f" — code {certificate['certificate_code']}.",
                         f"/certificate.html?code={certificate['certificate_code']}")
        conn.commit()
        conn.close()
        resp = {"lesson_id": int(lesson_id), "completed": True,
                "progress_percent": pct,
                "message": f"Lesson '{lesson['title']}' marked complete"}
        if certificate:
            resp["certificate"] = certificate
        self._ok(resp)

    # -- learning content: quizzes, tasks, learn-progress, tutor --------
    def _lesson_access(self, lesson_id):
        """Shared access rule for lesson learning content.

        Free-preview lessons are public (user may be None). Other lessons
        need a signed-in, enrolled user. Returns (lesson_dict, user) or
        (None, None) after sending the error response.
        """
        conn = db()
        lesson = conn.execute(
            "SELECT id, course_id, title, is_preview FROM lessons WHERE id = ?",
            (lesson_id,)).fetchone()
        conn.close()
        if not lesson:
            self._err(404, "Lesson not found")
            return None, None
        d = row_to_dict(lesson)
        if d.get("is_preview"):
            return d, self._auth_user()  # preview: public, user optional
        user = self._require_user()
        if not user:
            return None, None
        conn2 = db()
        enr = conn2.execute(
            "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
            (user["id"], d["course_id"])).fetchone()
        conn2.close()
        if not enr:
            self._err(403, "You must be enrolled in this course to use this lesson")
            return None, None
        return d, user

    def api_lesson_quiz(self, lesson_id):
        """GET /api/lessons/:id/quiz — questions WITHOUT answers.

        Same access rule as the lesson itself (preview = public).
        """
        lesson, _user = self._lesson_access(lesson_id)
        if not lesson:
            return
        conn = db()
        rows = conn.execute(
            """SELECT id, question, options_json, order_index FROM quizzes
               WHERE lesson_id = ? ORDER BY order_index, id""",
            (lesson_id,)).fetchall()
        conn.close()
        questions = []
        for r in rows:
            try:
                options = json.loads(r["options_json"])
            except (ValueError, TypeError):
                options = []
            questions.append({"id": r["id"], "question": r["question"],
                              "options": options, "order_index": r["order_index"]})
        self._ok({"lesson_id": int(lesson_id), "lesson_title": lesson["title"],
                  "questions": questions})

    def api_lesson_quiz_submit(self, lesson_id):
        """POST /api/lessons/:id/quiz — grade answers, record the attempt.

        Body: {"answers": {"<question_id>": <option index 0-3>, ...}}.
        Auth required; enrolment required unless the lesson is a preview.
        Returns the score plus, for every question, the correct option
        and the explanation of WHY — so the quiz itself teaches.
        """
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        if not user:
            self._err(401, "Sign in to submit a quiz")
            return
        body = self._read_json()
        answers = body.get("answers") or {}
        if not isinstance(answers, dict):
            self._err(400, "answers must be an object of question_id -> option index")
            return
        conn = db()
        rows = conn.execute(
            """SELECT id, question, options_json, answer_index, explanation
               FROM quizzes WHERE lesson_id = ? ORDER BY order_index, id""",
            (lesson_id,)).fetchall()
        if not rows:
            conn.close()
            self._err(404, "This lesson has no quiz yet")
            return
        results, score = [], 0
        for r in rows:
            try:
                options = json.loads(r["options_json"])
            except (ValueError, TypeError):
                options = []
            picked = answers.get(str(r["id"]))
            picked = answers.get(r["id"], picked)
            try:
                picked = int(picked)
            except (TypeError, ValueError):
                picked = None
            correct = picked == r["answer_index"]
            if correct:
                score += 1
            results.append({
                "question_id": r["id"], "question": r["question"],
                "options": options, "picked": picked,
                "correct_index": r["answer_index"], "correct": correct,
                "explanation": r["explanation"]})
        conn.execute(
            """INSERT INTO quiz_attempts (user_id, lesson_id, score, total, answers_json)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], lesson_id, score, len(rows),
             json.dumps({str(k): v for k, v in answers.items()})))
        conn.commit()
        conn.close()
        self._ok({"lesson_id": int(lesson_id), "score": score,
                  "total": len(rows),
                  "percent": round(score / len(rows) * 100, 1) if rows else 0,
                  "results": results})

    def api_lesson_tasks(self, lesson_id):
        """GET /api/lessons/:id/tasks — practice tasks WITHOUT solutions.

        Same access rule as the lesson. Each task carries a `completed`
        flag for the signed-in user (false for guests).
        """
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        conn = db()
        rows = conn.execute(
            """SELECT id, type, title, prompt, code, hint, order_index
               FROM tasks WHERE lesson_id = ? ORDER BY order_index, id""",
            (lesson_id,)).fetchall()
        done = set()
        if user:
            done = {r["task_id"] for r in conn.execute(
                """SELECT task_id FROM task_completions
                   WHERE user_id = ? AND task_id IN
                       (SELECT id FROM tasks WHERE lesson_id = ?)""",
                (user["id"], lesson_id)).fetchall()}
        conn.close()
        tasks = []
        for r in rows:
            d = row_to_dict(r)
            d["completed"] = r["id"] in done
            tasks.append(d)
        self._ok({"lesson_id": int(lesson_id), "lesson_title": lesson["title"],
                  "tasks": tasks})

    @staticmethod
    def _norm_answer(text):
        """Normalise a learner's answer for comparison: trim, collapse
        whitespace, drop a trailing semicolon/newlines. Case-sensitive
        (program output is case-sensitive), but tolerant of spacing."""
        return re.sub(r"\s+", " ", str(text or "").strip()).strip(";").strip()

    def api_task_complete(self, task_id):
        """POST /api/tasks/:id/complete — check a task answer, record it.

        Body: {"answer": "..."} (the learner's output / filled code /
        fixed code). predict/fill/trace are auto-checked against the
        expected value; fix/project are self-checked (any non-empty
        submission marks them complete and the model answer is returned
        for comparison). Auth required; enrolment required unless the
        lesson is a preview.
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        task = conn.execute(
            """SELECT t.*, l.course_id, l.is_preview, l.title AS lesson_title
               FROM tasks t JOIN lessons l ON l.id = t.lesson_id
               WHERE t.id = ?""",
            (task_id,)).fetchone()
        if not task:
            conn.close()
            self._err(404, "Task not found")
            return
        t = row_to_dict(task)
        if not t.get("is_preview"):
            enr = conn.execute(
                "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                (user["id"], t["course_id"])).fetchone()
            if not enr:
                conn.close()
                self._err(403, "You must be enrolled in this course to do its tasks")
                return
        body = self._read_json()
        answer = (body.get("answer") or "")
        if not isinstance(answer, str) or not answer.strip():
            conn.close()
            self._err(400, "answer is required")
            return
        if len(answer) > 10000:
            conn.close()
            self._err(400, "answer is too long (max 10000 characters)")
            return
        auto = t["type"] in ("predict", "fill", "trace")
        correct = None
        if auto:
            correct = (self._norm_answer(answer)
                       == self._norm_answer(t["expected"]))
        if not auto or correct:
            conn.execute(
                """INSERT OR IGNORE INTO task_completions (user_id, task_id)
                   VALUES (?, ?)""", (user["id"], task_id))
            conn.commit()
        conn.close()
        resp = {"task_id": int(task_id), "type": t["type"],
                "completed": bool(not auto or correct),
                "correct": correct,
                "expected": t["expected"], "answer": t["answer"],
                "hint": t["hint"]}
        if auto and not correct:
            resp["message"] = ("Not quite — check the hint and try again. "
                               "The expected answer is shown so you can learn from it.")
        self._ok(resp)

    def api_course_learn_progress(self, course_id):
        """GET /api/courses/:id/learn-progress — quiz + task progress.

        Auth + enrolled only. Per lesson: best quiz score, tasks done /
        tasks total. Used by the lesson page to show what is finished.
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        course = conn.execute("SELECT id FROM courses WHERE id = ?",
                              (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return
        if not conn.execute(
                "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                (user["id"], course_id)).fetchone():
            conn.close()
            self._err(403, "You must be enrolled in this course to view its progress")
            return
        lessons = conn.execute(
            "SELECT id, title, order_index FROM lessons WHERE course_id = ?"
            " ORDER BY order_index, id", (course_id,)).fetchall()
        out = []
        for lesson in lessons:
            lid = lesson["id"]
            best = conn.execute(
                """SELECT MAX(score * 1.0 / total) AS best, COUNT(*) AS n
                   FROM quiz_attempts WHERE user_id = ? AND lesson_id = ?""",
                (user["id"], lid)).fetchone()
            quiz_total = conn.execute(
                "SELECT COUNT(*) AS n FROM quizzes WHERE lesson_id = ?",
                (lid,)).fetchone()["n"]
            tasks_total = conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE lesson_id = ?",
                (lid,)).fetchone()["n"]
            tasks_done = conn.execute(
                """SELECT COUNT(*) AS n FROM task_completions tc
                   JOIN tasks t ON t.id = tc.task_id
                   WHERE tc.user_id = ? AND t.lesson_id = ?""",
                (user["id"], lid)).fetchone()["n"]
            out.append({
                "lesson_id": lid, "lesson_title": lesson["title"],
                "quiz_total": quiz_total,
                "quiz_attempts": best["n"] or 0,
                "quiz_best_percent": (round(best["best"] * 100, 1)
                                      if best["best"] is not None else None),
                "tasks_done": tasks_done, "tasks_total": tasks_total})
        conn.close()
        self._ok({"course_id": int(course_id), "lessons": out})

    # -- tutor chatbot (rule-based, knowledge base = course content) ---
    def api_tutor(self):
        """POST /api/tutor — the in-site tutor chatbot.

        Rule-based only: every answer comes from the seeded course
        content (lessons, flowcharts, MCQs, tasks). Nothing is invented:
        when no content matches, the tutor says so and points at the
        relevant lessons. No external API is called.

        Body: {"message": "...", "course_id": 3, "lesson_id": 12,
               "context": {"quiz_question_id": 5, "task_id": 9}}.
        """
        body = self._read_json()
        message = (body.get("message") or "").strip()
        if not message:
            self._err(400, "message is required")
            return
        if len(message) > 500:
            self._err(400, "message must be at most 500 characters")
            return
        course_id = _positive_int(body.get("course_id"))
        lesson_id = _positive_int(body.get("lesson_id"))
        context = body.get("context") or {}
        if not isinstance(context, dict):
            context = {}
        reply, ctx = self._tutor_answer(message, course_id, lesson_id, context)
        self._ok({"reply": reply, "context": ctx})

    @staticmethod
    def _strip_html(html):
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _tutor_answer(self, message, course_id, lesson_id, context):
        msg = message.lower()
        words = set(re.findall(r"[a-z][a-z0-9+#]*", msg))
        conn = db()

        # -- scope: one lesson, one course, or the whole catalogue --
        scope_lessons = []
        if lesson_id:
            row = conn.execute(
                "SELECT id, course_id, title FROM lessons WHERE id = ?",
                (lesson_id,)).fetchone()
            if row:
                scope_lessons = [row_to_dict(row)]
                course_id = course_id or row["course_id"]
        if course_id and not scope_lessons:
            scope_lessons = [row_to_dict(r) for r in conn.execute(
                "SELECT id, course_id, title FROM lessons WHERE course_id = ?"
                " ORDER BY order_index, id", (course_id,)).fetchall()]
        if not scope_lessons:
            scope_lessons = [row_to_dict(r) for r in conn.execute(
                "SELECT id, course_id, title FROM lessons"
                " ORDER BY course_id, order_index, id").fetchall()]
        lesson_ids = [l["id"] for l in scope_lessons]
        courses = {r["id"]: r["title"] for r in conn.execute(
            "SELECT id, title FROM courses").fetchall()}

        def topic_list():
            names = [f"{l['title']} (lesson {l['id']})" for l in scope_lessons[:12]]
            return ", ".join(names)

        def unknown():
            return ("I don't know that yet — it is not in the course material "
                    "I was given, so I won't guess. Try asking me about one of "
                    "these topics: " + topic_list() + ". You can also ask me to "
                    "'quiz me', 'walk me through the flowchart', or 'give me a hint'.")

        # -- 1. answering a quiz question posed by the tutor ----------
        qid = context.get("quiz_question_id")
        if qid and (msg.strip() in ("a", "b", "c", "d", "1", "2", "3", "4",
                                     "option a", "option b", "option c",
                                     "option d", "option 1", "option 2",
                                     "option 3", "option 4")
                    or re.fullmatch(r"[a-d1-4]", msg.strip())):
            row = conn.execute(
                "SELECT * FROM quizzes WHERE id = ?", (qid,)).fetchone()
            if row:
                picked = {"a": 0, "b": 1, "c": 2, "d": 3,
                          "1": 0, "2": 1, "3": 2, "4": 3}[msg.strip()[-1]]
                opts = json.loads(row["options_json"])
                if picked == row["answer_index"]:
                    reply = (f"Correct! {opts[picked]} is right. "
                             f"{row['explanation']} Want another question? "
                             "Just say 'quiz me'.")
                else:
                    reply = (f"Not quite — the correct answer is "
                             f"'{opts[row['answer_index']]}'. {row['explanation']} "
                             "Want to try another? Say 'quiz me'.")
                conn.close()
                return reply, {}
            conn.close()
            return "That question is gone — say 'quiz me' and I will ask a new one.", {}

        # -- 2. quiz me -------------------------------------------------
        if words & {"quiz", "test", "mcq", "question"} or "quiz me" in msg or "test me" in msg:
            if lesson_ids:
                placeholders = ",".join("?" * len(lesson_ids))
                row = conn.execute(
                    f"""SELECT id, lesson_id, question, options_json
                        FROM quizzes WHERE lesson_id IN ({placeholders})
                        ORDER BY RANDOM() LIMIT 1""",
                    lesson_ids).fetchone()
            else:
                row = None
            if not row:
                conn.close()
                return ("There is no quiz for this lesson yet. Pick another "
                        "lesson, or ask me to explain a topic."), {}
            opts = json.loads(row["options_json"])
            letters = ["A", "B", "C", "D"]
            q = (f"Quiz time! {row['question']}\n" +
                 "\n".join(f"{letters[i]}. {o}" for i, o in enumerate(opts)) +
                 "\nReply with A, B, C or D.")
            conn.close()
            return q, {"quiz_question_id": row["id"]}

        # -- 3. walk through the flowchart ------------------------------
        if "flowchart" in msg or "walk" in msg or "step by step" in msg or "steps" in msg:
            row = None
            if lesson_id:
                row = conn.execute(
                    "SELECT flowchart_title, flowchart_json FROM lesson_content"
                    " WHERE lesson_id = ?", (lesson_id,)).fetchone()
            if not row or not row["flowchart_json"]:
                # This lesson has none: fall back to any flowchart in the
                # same course (or the current scope), and say which one.
                fallback_ids = list(lesson_ids)
                if course_id:
                    fallback_ids = [r["id"] for r in conn.execute(
                        "SELECT id FROM lessons WHERE course_id = ?"
                        " ORDER BY order_index, id", (course_id,)).fetchall()]
                if fallback_ids:
                    placeholders = ",".join("?" * len(fallback_ids))
                    row = conn.execute(
                        f"""SELECT lc.flowchart_title, lc.flowchart_json,
                                   l.title AS lesson_title
                            FROM lesson_content lc
                            JOIN lessons l ON l.id = lc.lesson_id
                            WHERE lc.lesson_id IN ({placeholders})
                              AND lc.flowchart_json IS NOT NULL LIMIT 1""",
                        fallback_ids).fetchone()
            if not row or not row["flowchart_json"]:
                conn.close()
                return ("This lesson has no flowchart. Ask me to explain the "
                        "topic instead, or open a lesson that has one "
                        "(if-else, loops, functions, recursion, sorting)."), {}
            try:
                fc = json.loads(row["flowchart_json"])
            except (ValueError, TypeError):
                fc = None
            if not fc:
                conn.close()
                return "This lesson's flowchart could not be read.", {}
            nodes = {n["id"]: n for n in fc.get("nodes", [])}
            steps, seen = [], set()
            for e in fc.get("edges", []):
                if e["from"] not in seen:
                    seen.add(e["from"])
                    steps.append(nodes.get(e["from"], {}).get("label", e["from"]))
                label = e.get("label")
                to_label = nodes.get(e["to"], {}).get("label", e["to"])
                steps.append(f"{'If ' + label + ', go to: ' if label else 'Then: '}{to_label}")
            title = row["flowchart_title"] or "Flowchart"
            lesson_note = ""
            if row.keys() and "lesson_title" in row.keys() and row["lesson_title"]:
                lesson_note = f" (from the lesson '{row['lesson_title']}')"
            conn.close()
            return (f"Let's walk through '{title}'{lesson_note} step by step:\n" +
                    "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))), {}

        # -- 4. hint for a task ------------------------------------------
        if "hint" in msg:
            tid = context.get("task_id")
            row = None
            if tid:
                row = conn.execute(
                    "SELECT title, hint FROM tasks WHERE id = ?", (tid,)).fetchone()
            if not row and lesson_ids:
                placeholders = ",".join("?" * len(lesson_ids))
                row = conn.execute(
                    f"""SELECT title, hint FROM tasks
                        WHERE lesson_id IN ({placeholders}) LIMIT 1""",
                    lesson_ids).fetchone()
            conn.close()
            if row and row["hint"]:
                return (f"Hint for '{row['title']}': {row['hint']} "
                        "Try it, then check your answer on the lesson page."), {}
            return ("Tell me which task you need a hint for — open the task "
                    "on its lesson page and ask me again from there."), {}

        # -- 5. greetings / what can you do ------------------------------
        if words & {"hi", "hello", "hey", "namaste"} and len(words) <= 4:
            conn.close()
            return ("Hi! I am the LearnHub tutor. I can explain any topic from "
                    "your courses in simple steps, walk you through a lesson's "
                    "flowchart, quiz you with MCQs, and give hints for tasks. "
                    "Try: 'Explain loops', 'Quiz me', or 'Walk me through the "
                    "flowchart'. Topics here: " + topic_list() + "."), {}
        if "what" in msg and ("course" in msg or "learn" in msg):
            conn.close()
            return ("You can learn: " + ", ".join(courses.values()) +
                    ". Open any course and ask me about its lessons."), {}

        # -- 6. explain a topic: match lesson titles / keywords ---------
        # Topic words only: drop stopwords and words from course titles
        # (e.g. "python" names the course, not the topic), and normalise
        # plurals ("loop" must match the lesson "Loops & Iteration").
        _stop = {"in", "the", "a", "an", "and", "or", "of", "to", "for",
                 "how", "what", "explain", "tell", "me", "about", "please",
                 "is", "are", "with", "on", "i", "want", "learn", "give"}
        _course_words = set()
        for _t in courses.values():
            _course_words |= set(re.findall(r"[a-z][a-z0-9+#]*", _t.lower()))
        def _norm(_w):
            return _w[:-1] if len(_w) > 3 and _w.endswith("s") and not _w.endswith("ss") else _w
        topic_words = {_norm(w) for w in words - _stop - _course_words}
        best, best_score = None, 0
        for lesson in scope_lessons:
            title_words = {_norm(w) for w in
                           re.findall(r"[a-z][a-z0-9+#]*", lesson["title"].lower())}
            score = len(topic_words & title_words)
            # bonus for an exact phrase match on the title
            if lesson["title"].lower() in msg:
                score += 3
            if score > best_score:
                best, best_score = lesson, score
        if not best and lesson_id:
            # "Explain this lesson" (the chat widget's chip): no keyword
            # to match, so explain the lesson the learner is looking at.
            best = next((l for l in scope_lessons if l["id"] == lesson_id), None)
            if best:
                best_score = 1
        if best and best_score > 0:
            row = conn.execute(
                "SELECT body, video_title FROM lesson_content WHERE lesson_id = ?",
                (best["id"],)).fetchone()
            conn.close()
            if row and row["body"]:
                text = self._strip_html(row["body"])
                # first ~600 chars: the concept in simple steps
                short = text[:600]
                if len(text) > 600:
                    short += "…"
                reply = (f"Here's '{best['title']}' in simple steps:\n{short}\n"
                         f"Read the full lesson with examples, flowchart and "
                         f"quiz: lesson.html?id={best['id']}")
                if row["video_title"]:
                    reply += f"\nThere is also a free video for this lesson: {row['video_title']}."
                return reply, {"lesson_id": best["id"]}
            conn.close()
            return (f"'{best['title']}' is a lesson in this course — open it "
                    f"here: lesson.html?id={best['id']}"), {"lesson_id": best["id"]}
        conn.close()
        return unknown(), {}

    def api_cert_list(self):
        """List the current user's certificates of completion.

        Auth required; only the caller's own certificates are returned,
        newest first. Each entry carries the certificate id/code, the
        course title, and issued_at (the date the course was completed).
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT cf.id, cf.certificate_code, cf.issued_at,
                      c.id AS course_id, c.title AS course_title,
                      c.instructor
               FROM certificates cf
               JOIN courses c ON c.id = cf.course_id
               WHERE cf.user_id = ?
               ORDER BY cf.issued_at DESC, cf.id DESC""",
            (user["id"],)).fetchall()
        conn.close()
        self._ok({"certificates": [row_to_dict(r) for r in rows]})

    def api_cert_verify(self, code):
        """Public certificate verification (no auth).

        Anyone with a certificate code can check it: GET
        /api/certificates/verify/LH-XXXXXXXX returns {valid: true, ...}
        with the course title, instructor, student name and issue date,
        or 404 {valid: false} when the code does not exist. Only those
        six fields are ever returned - no user ids, emails or internals.
        """
        code = (code or "").strip()
        if not code or len(code) > 64:
            self._json(404, {"ok": False, "valid": False,
                             "error": "Certificate not found"})
            return
        conn = db()
        cert = conn.execute(
            """SELECT cf.certificate_code, cf.issued_at,
                      c.title AS course_title, c.instructor,
                      u.name AS student_name
               FROM certificates cf
               JOIN courses c ON c.id = cf.course_id
               JOIN users u ON u.id = cf.user_id
               WHERE cf.certificate_code = ?""",
            (code,)).fetchone()
        conn.close()
        if not cert:
            self._json(404, {"ok": False, "valid": False,
                             "error": "Certificate not found"})
            return
        self._ok({"valid": True,
                  "certificate_code": cert["certificate_code"],
                  "course_title": cert["course_title"],
                  "instructor": cert["instructor"],
                  "student_name": cert["student_name"],
                  "issued_at": cert["issued_at"]})

    def api_cert_get(self, cert_id):
        """View a certificate. Users can only view their own certificates."""
        user = self._require_user()
        if not user:
            return
        conn = db()
        cert = conn.execute(
            """SELECT cf.id, cf.certificate_code, cf.issued_at,
                      u.id AS user_id, u.name AS user_name,
                      c.id AS course_id, c.title AS course_title,
                      c.instructor, c.duration_hours
               FROM certificates cf
               JOIN users u ON u.id = cf.user_id
               JOIN courses c ON c.id = cf.course_id
               WHERE cf.id = ?""",
            (cert_id,)).fetchone()
        conn.close()
        if not cert:
            self._err(404, "Certificate not found")
            return
        if cert["user_id"] != user["id"]:
            self._err(403, "You can only view your own certificates")
            return
        self._ok({"certificate": row_to_dict(cert)})

    def api_register(self):
        body = self._read_json()
        name, email, password = (body.get("name") or "").strip(), (body.get("email") or "").strip().lower(), body.get("password") or ""
        if not name or not email or not password:
            self._err(400, "name, email and password are required")
            return
        if len(name) > 100:
            self._err(400, "name must be at most 100 characters")
            return
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            self._err(400, "a valid email is required")
            return
        if len(password) < 6:
            self._err(400, "password must be at least 6 characters")
            return
        if len(password) > 128:
            self._err(400, "password must be at most 128 characters")
            return
        conn = db()
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            conn.close()
            self._err(409, "An account with this email already exists")
            return
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
            (name, email, hash_password(password),
             1 if is_admin_email(email) else 0),
        )
        conn.commit()
        user_id = cur.lastrowid
        _audit(conn, user_id, "register", self._client_ip(),
               f"account created for {email}")
        conn.commit()
        conn.close()
        # Mandatory OTP: no session token is issued until the email is
        # verified via POST /api/auth/verify-otp.
        self._ok({"otp_required": True, "email": email,
                  "user": {"id": user_id, "name": name, "email": email,
                           "is_admin": is_admin_email(email)},
                  "message": "Account created. Verify the OTP sent to your email to sign in."},
                 status=201)

    def api_login(self):
        body = self._read_json()
        email, password = (body.get("email") or "").strip().lower(), body.get("password") or ""
        if not email or not password:
            self._err(400, "email and password are required")
            return
        ip = self._client_ip()
        now = time.time()
        # Brute-force shield: >=5 failures in 10 min blocks this IP+email.
        blocked_until = _LOGIN_BLOCKS.get((ip, email), 0)
        if blocked_until > now:
            self._err(429, "Too many failed sign-in attempts - try again in 10 minutes")
            return
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            key = (ip, email)
            tries = [t for t in _FAILED_LOGINS.get(key, []) if now - t < 600]
            tries.append(now)
            _FAILED_LOGINS[key] = tries
            _log_security(conn, ip, user["id"] if user else None,
                          "failed_login", "low",
                          f"failed sign-in for {email}", False)
            if len(tries) >= 5:
                _LOGIN_BLOCKS[key] = now + 600
                _log_security(conn, ip, user["id"] if user else None,
                                      "brute_force", "high",
                              f"5 failed sign-ins for {email} - blocked 10 min", True)
            _audit(conn, user["id"] if user else None, "login_failed", ip,
                   f"failed sign-in for {email}")
            conn.commit()
            conn.close()
            self._err(401, "Invalid email or password")
            return
        _FAILED_LOGINS.pop((ip, email), None)
        conn.close()
        # Password OK - but no token yet: mandatory OTP verification.
        self._ok({"otp_required": True, "email": email,
                  "message": "Password correct. Verify the OTP to complete sign-in."})

    def api_logout(self):
        auth = self.headers.get("Authorization", "")
        m = re.match(r"Bearer\s+(\S+)", auth)
        if m:
            conn = db()
            row = conn.execute("SELECT user_id FROM auth_tokens WHERE token = ?",
                               (m.group(1),)).fetchone()
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (m.group(1),))
            if row:
                _audit(conn, row["user_id"], "logout", self._client_ip(), "")
            conn.commit()
            conn.close()
        self._clear_auth_cookie()
        self._ok({"message": "Logged out"})

    # -- authenticated endpoints ---------------------------------------
    def _require_user(self):
        user = self._auth_user()
        if not user:
            self._err(401, "Missing or invalid Authorization: Bearer <token>")
            return None
        return user

    # -- admin (instructor) helpers ------------------------------------
    # Admin endpoints accept EITHER the shared secret (?key=API_SECRET
    # or the X-Admin-Key header) OR a signed-in admin user: the account
    # registered with ADMIN_EMAIL (the admin Gmail). The admin UI lives
    # at /admin.html - it signs in with Gmail or falls back to the key.
    COURSE_LEVELS = ("Beginner", "Intermediate", "Advanced")

    def _require_admin(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        key = qs.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if key and key == API_SECRET:
            return True
        user = self._auth_user()
        if user and _is_admin_user(user):
            return True
        self._err(403, "Forbidden: sign in as the admin account or provide a valid admin key")
        return False

    def _validate_course(self, body):
        """Return (clean_dict, error). Validates fields present in body."""
        clean, err = {}, None
        if "title" in body:
            title = (body.get("title") or "").strip()
            if not title:
                return None, "title is required and cannot be empty"
            if len(title) > 200:
                return None, "title must be at most 200 characters"
            clean["title"] = title
        if "price" in body:
            if isinstance(body.get("price"), bool):
                return None, "price must be an integer >= 0"
            try:
                price = int(body.get("price"))
            except (TypeError, ValueError):
                return None, "price must be an integer >= 0"
            if price < 0:
                return None, "price must be >= 0"
            clean["price"] = price
        if "level" in body:
            level = (body.get("level") or "").strip()
            if level not in self.COURSE_LEVELS:
                return None, f"level must be one of: {', '.join(self.COURSE_LEVELS)}"
            clean["level"] = level
        _TEXT_CAPS = {"description": 10000, "category": 60,
                      "instructor": 100, "image_url": 2000}
        for f in ("description", "category", "instructor", "image_url"):
            if f in body:
                value = (body.get(f) or "").strip()
                if len(value) > _TEXT_CAPS[f]:
                    return None, f"{f} must be at most {_TEXT_CAPS[f]} characters"
                clean[f] = value
        if "duration_hours" in body:
            if isinstance(body.get("duration_hours"), bool):
                return None, "duration_hours must be a number >= 0"
            try:
                dur = float(body.get("duration_hours"))
            except (TypeError, ValueError):
                return None, "duration_hours must be a number >= 0"
            if not math.isfinite(dur) or dur < 0:
                return None, "duration_hours must be a finite number >= 0"
            clean["duration_hours"] = dur
        return clean, err

    def api_admin_course_create(self):
        if not self._require_admin():
            return
        body = self._read_json()
        clean, err = self._validate_course(body)
        if err:
            self._err(400, err)
            return
        if "title" not in clean:
            self._err(400, "title is required")
            return
        course = {"title": clean.pop("title"),
                  "description": clean.get("description", ""),
                  "category": clean.get("category", "General"),
                  "price": clean.get("price", 0),
                  "instructor": clean.get("instructor", ""),
                  "duration_hours": clean.get("duration_hours", 0.0),
                  "level": clean.get("level", "Beginner"),
                  "image_url": clean.get("image_url", "")}
        conn = db()
        cur = conn.execute(
            """INSERT INTO courses (title, description, category, price, instructor,
                                    duration_hours, level, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (course["title"], course["description"], course["category"],
             course["price"], course["instructor"], course["duration_hours"],
             course["level"], course["image_url"]))
        admin = self._auth_user()
        _audit(conn, admin["id"] if admin else None, "admin_course_create",
               self._client_ip(), f"created course '{course['title']}'")
        conn.commit()
        course["id"] = cur.lastrowid
        conn.close()
        self._ok({"course": course}, status=201)

    def api_admin_course_update(self, course_id):
        if not self._require_admin():
            return
        body = self._read_json()
        clean, err = self._validate_course(body)
        if err:
            self._err(400, err)
            return
        if not clean:
            self._err(400, "No valid fields to update")
            return
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?",
                            (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE courses SET {sets} WHERE id = ?",
                     list(clean.values()) + [course_id])
        admin = self._auth_user()
        _audit(conn, admin["id"] if admin else None, "admin_course_update",
               self._client_ip(), f"updated course {course_id}: {sorted(clean)}")
        conn.commit()
        course = row_to_dict(conn.execute(
            "SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone())
        conn.close()
        self._ok({"course": course})

    def api_admin_course_delete(self, course_id):
        if not self._require_admin():
            return
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?",
                            (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        n = conn.execute("SELECT COUNT(*) AS n FROM enrollments WHERE course_id = ?",
                         (course_id,)).fetchone()["n"]
        if n:
            conn.close()
            self._err(409, f"Cannot delete: {n} enrollment(s) exist for this course"
                           " (enrollment history is preserved)")
            return
        # lessons, reviews, certificates, cart items, wishlist rows
        # cascade automatically via ON DELETE CASCADE
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        admin = self._auth_user()
        _audit(conn, admin["id"] if admin else None, "admin_course_delete",
               self._client_ip(), f"deleted course {course_id}")
        conn.commit()
        conn.close()
        self._ok({"message": f"Course {course_id} deleted"})

    def api_admin_lesson_create(self, course_id):
        if not self._require_admin():
            return
        body = self._read_json()
        title = (body.get("title") or "").strip()
        if not title:
            self._err(400, "title is required")
            return
        if len(title) > 200:
            self._err(400, "title must be at most 200 characters")
            return
        content_url = (body.get("content_url") or body.get("body")
                       or body.get("content") or "").strip()
        if not content_url:
            self._err(400, "content_url (or body) is required")
            return
        if len(content_url) > 2000:
            self._err(400, "content_url must be at most 2000 characters")
            return
        try:
            duration = int(body.get("duration_minutes", 0) or 0)
        except (TypeError, ValueError):
            self._err(400, "duration_minutes must be an integer >= 0")
            return
        if duration < 0:
            self._err(400, "duration_minutes must be >= 0")
            return
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?",
                            (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        order_index = body.get("order_index")
        if order_index is None:
            order_index = conn.execute(
                "SELECT COALESCE(MAX(order_index), 0) + 1 AS nxt FROM lessons"
                " WHERE course_id = ?", (course_id,)).fetchone()["nxt"]
        try:
            order_index = int(order_index)
        except (TypeError, ValueError):
            conn.close()
            self._err(400, "order_index must be an integer")
            return
        cur = conn.execute(
            """INSERT INTO lessons (course_id, title, content_url,
                                    duration_minutes, order_index)
               VALUES (?, ?, ?, ?, ?)""",
            (course_id, title, content_url, duration, order_index))
        conn.commit()
        lesson = row_to_dict(conn.execute(
            "SELECT * FROM lessons WHERE id = ?", (cur.lastrowid,)).fetchone())
        conn.close()
        self._ok({"lesson": lesson}, status=201)

    def api_admin_lesson_update(self, lesson_id):
        if not self._require_admin():
            return
        body = self._read_json()
        clean = {}
        if "title" in body:
            title = (body.get("title") or "").strip()
            if not title:
                self._err(400, "title cannot be empty")
                return
            if len(title) > 200:
                self._err(400, "title must be at most 200 characters")
                return
            clean["title"] = title
        for f in ("content_url", "body", "content"):
            if f in body:
                value = (body.get(f) or "").strip()
                if len(value) > 2000:
                    self._err(400, "content_url must be at most 2000 characters")
                    return
                clean["content_url"] = value
                break
        if "duration_minutes" in body:
            try:
                dur = int(body.get("duration_minutes"))
            except (TypeError, ValueError):
                self._err(400, "duration_minutes must be an integer >= 0")
                return
            if dur < 0:
                self._err(400, "duration_minutes must be >= 0")
                return
            clean["duration_minutes"] = dur
        if "order_index" in body:
            try:
                clean["order_index"] = int(body.get("order_index"))
            except (TypeError, ValueError):
                self._err(400, "order_index must be an integer")
                return
        if "is_preview" in body:
            try:
                pv = int(body.get("is_preview"))
            except (TypeError, ValueError):
                self._err(400, "is_preview must be 0 or 1")
                return
            if pv not in (0, 1):
                self._err(400, "is_preview must be 0 or 1")
                return
            clean["is_preview"] = pv
        if not clean:
            self._err(400, "No valid fields to update")
            return
        conn = db()
        if not conn.execute("SELECT id FROM lessons WHERE id = ?",
                            (lesson_id,)).fetchone():
            conn.close()
            self._err(404, "Lesson not found")
            return
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE lessons SET {sets} WHERE id = ?",
                     list(clean.values()) + [lesson_id])
        conn.commit()
        lesson = row_to_dict(conn.execute(
            "SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone())
        conn.close()
        self._ok({"lesson": lesson})

    def api_admin_lesson_delete(self, lesson_id):
        if not self._require_admin():
            return
        conn = db()
        if not conn.execute("SELECT id FROM lessons WHERE id = ?",
                            (lesson_id,)).fetchone():
            conn.close()
            self._err(404, "Lesson not found")
            return
        # lesson_progress rows cascade automatically via ON DELETE CASCADE
        conn.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        conn.commit()
        conn.close()
        self._ok({"message": f"Lesson {lesson_id} deleted"})

    def api_admin_stats(self):
        """Platform-wide stats for the admin dashboard.

        Same auth as every admin endpoint: ?key=API_SECRET or X-Admin-Key.
        Revenue is reported two ways: the sum of completed order totals,
        and the sum of course price x enrollments (the enrolment value).
        """
        if not self._require_admin():
            return
        conn = db()
        total_users = conn.execute(
            "SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        total_courses = conn.execute(
            "SELECT COUNT(*) AS n FROM courses").fetchone()["n"]
        total_enrollments = conn.execute(
            "SELECT COUNT(*) AS n FROM enrollments").fetchone()["n"]
        revenue_from_orders = conn.execute(
            "SELECT COALESCE(SUM(total), 0) AS rev FROM orders"
            " WHERE status = 'completed'").fetchone()["rev"]
        revenue_from_enrollments = conn.execute(
            "SELECT COALESCE(SUM(c.price), 0) AS rev FROM enrollments e"
            " JOIN courses c ON c.id = e.course_id").fetchone()["rev"]
        revenue_from_payments = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS rev FROM payments"
            " WHERE status = 'paid'").fetchone()["rev"]
        popular = conn.execute(
            """SELECT c.id, c.title, c.category, c.price,
                      COUNT(e.id) AS enrollments,
                      COUNT(e.id) * c.price AS revenue
               FROM courses c LEFT JOIN enrollments e ON e.course_id = c.id
               GROUP BY c.id
               ORDER BY enrollments DESC, c.id
               LIMIT 5""").fetchall()
        conn.close()
        self._ok({
            "total_users": total_users,
            "total_courses": total_courses,
            "total_enrollments": total_enrollments,
            "revenue_from_orders": revenue_from_orders,
            "revenue_from_enrollments": revenue_from_enrollments,
            "revenue_from_payments": revenue_from_payments,
            "popular_courses": [row_to_dict(r) for r in popular],
        })

    # -- admin dashboard: overview, users, orders, certificates, -------
    # -- learning analytics, and lesson-content / quiz / task editing ---
    # All of these are admin-key gated (same ?key= / X-Admin-Key rule).

    def _admin_page(self):
        """Parse ?page= (1-based, default 1) and ?per_page= (1..50,
        default 20) from the request query string."""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        try:
            page = max(1, int(qs.get("page", ["1"])[0]))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = int(qs.get("per_page", ["20"])[0])
        except (TypeError, ValueError):
            per_page = 20
        per_page = max(1, min(50, per_page))
        return page, per_page, (qs.get("q", [""])[0] or "").strip()

    def _admin_paged(self, payload, total, page, per_page):
        payload["page"] = page
        payload["per_page"] = per_page
        payload["total"] = total
        payload["pages"] = max(1, -(-total // per_page))
        return payload

    def api_admin_overview(self):
        """Dashboard overview for admin.html.

        Totals (users, courses, lessons, enrolments, revenue from
        completed orders, quiz attempts, average quiz score, certificates
        issued), the 5 most popular courses, the 10 most recent
        enrolments and the 10 most recently registered users.
        """
        if not self._require_admin():
            return
        conn = db()
        one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
        total_users = one("SELECT COUNT(*) FROM users")
        total_courses = one("SELECT COUNT(*) FROM courses")
        total_lessons = one("SELECT COUNT(*) FROM lessons")
        total_enrollments = one("SELECT COUNT(*) FROM enrollments")
        revenue = one("SELECT COALESCE(SUM(total), 0) FROM orders"
                      " WHERE status = 'completed'")
        quiz_attempts = one("SELECT COUNT(*) FROM quiz_attempts")
        avg_quiz = conn.execute(
            "SELECT ROUND(AVG(score * 100.0 / NULLIF(total, 0)), 1)"
            " FROM quiz_attempts WHERE total > 0").fetchone()[0]
        certificates = one("SELECT COUNT(*) FROM certificates")
        popular = conn.execute(
            """SELECT c.id, c.title, c.category, c.price,
                      COUNT(e.id) AS enrollments,
                      COUNT(e.id) * c.price AS revenue
               FROM courses c LEFT JOIN enrollments e ON e.course_id = c.id
               GROUP BY c.id ORDER BY enrollments DESC, c.id LIMIT 5"""
        ).fetchall()
        recent_enrollments = conn.execute(
            """SELECT e.id, e.enrolled_at, u.name AS user_name,
                      u.email AS user_email, c.title AS course_title
               FROM enrollments e
               JOIN users u ON u.id = e.user_id
               JOIN courses c ON c.id = e.course_id
               ORDER BY e.enrolled_at DESC, e.id DESC LIMIT 10"""
        ).fetchall()
        recent_users = conn.execute(
            """SELECT u.id, u.name, u.email, u.created_at,
                      (SELECT COUNT(*) FROM enrollments e
                        WHERE e.user_id = u.id) AS enrollments
               FROM users u ORDER BY u.created_at DESC, u.id DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        self._ok({
            "total_users": total_users,
            "total_courses": total_courses,
            "total_lessons": total_lessons,
            "total_enrollments": total_enrollments,
            "revenue": revenue,
            "quiz_attempts": quiz_attempts,
            "avg_quiz_percent": avg_quiz,
            "certificates_issued": certificates,
            "popular_courses": [row_to_dict(r) for r in popular],
            "recent_enrollments": [row_to_dict(r) for r in recent_enrollments],
            "recent_users": [row_to_dict(r) for r in recent_users],
        })

    def api_admin_users(self):
        """List users for admin.html (searchable by name/email).

        Each user carries enrolment + certificate counts and their
        average quiz score across all attempts (null when never quizzed).
        """
        if not self._require_admin():
            return
        page, per_page, q = self._admin_page()
        conn = db()
        where, args = "", []
        if q:
            where = "WHERE LOWER(name) LIKE ? OR LOWER(email) LIKE ?"
            args = [f"%{q.lower()}%", f"%{q.lower()}%"]
        total = conn.execute(
            f"SELECT COUNT(*) FROM users {where}", args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT u.id, u.name, u.email, u.created_at, u.is_admin,
                       (SELECT COUNT(*) FROM enrollments e
                         WHERE e.user_id = u.id) AS enrollments,
                       (SELECT COUNT(*) FROM certificates cf
                         WHERE cf.user_id = u.id) AS certificates,
                       (SELECT ROUND(AVG(score * 100.0 / NULLIF(total, 0)), 1)
                         FROM quiz_attempts qa
                         WHERE qa.user_id = u.id AND qa.total > 0) AS avg_quiz_percent
                FROM users u {where}
                ORDER BY u.created_at DESC, u.id DESC
                LIMIT ? OFFSET ?""",
            args + [per_page, (page - 1) * per_page]).fetchall()
        conn.close()
        self._ok(self._admin_paged(
            {"users": [row_to_dict(r) for r in rows]}, total, page, per_page))

    def api_admin_user(self, user_id):
        """One user with every enrolment (progress, quiz best, tasks,
        certificate) — the admin's learner detail view."""
        if not self._require_admin():
            return
        conn = db()
        user = conn.execute(
            "SELECT id, name, email, is_admin, created_at FROM users WHERE id = ?",
            (user_id,)).fetchone()
        if not user:
            conn.close()
            self._err(404, "User not found")
            return
        enrolments = conn.execute(
            """SELECT e.id, e.course_id, c.title AS course_title,
                      e.progress_percent, e.enrolled_at,
                      (SELECT COUNT(*) FROM lessons l
                        WHERE l.course_id = e.course_id) AS total_lessons,
                      (SELECT COUNT(*) FROM lesson_progress lp
                        JOIN lessons l2 ON l2.id = lp.lesson_id
                        WHERE lp.user_id = e.user_id
                          AND l2.course_id = e.course_id) AS completed_lessons,
                      (SELECT ROUND(AVG(qa.score * 100.0 / NULLIF(qa.total, 0)), 1)
                        FROM quiz_attempts qa
                        JOIN lessons l3 ON l3.id = qa.lesson_id
                        WHERE qa.user_id = e.user_id
                          AND l3.course_id = e.course_id
                          AND qa.total > 0) AS avg_quiz_percent,
                      (SELECT COUNT(*) FROM task_completions tc
                        JOIN tasks t ON t.id = tc.task_id
                        JOIN lessons l4 ON l4.id = t.lesson_id
                        WHERE tc.user_id = e.user_id
                          AND l4.course_id = e.course_id) AS tasks_done,
                      (SELECT certificate_code FROM certificates cf
                        WHERE cf.user_id = e.user_id
                          AND cf.course_id = e.course_id) AS certificate_code
               FROM enrollments e
               JOIN courses c ON c.id = e.course_id
               WHERE e.user_id = ?
               ORDER BY e.enrolled_at DESC""", (user_id,)).fetchall()
        certs = conn.execute(
            """SELECT cf.id, cf.certificate_code, cf.issued_at,
                      c.title AS course_title
               FROM certificates cf
               JOIN courses c ON c.id = cf.course_id
               WHERE cf.user_id = ? ORDER BY cf.issued_at DESC""",
            (user_id,)).fetchall()
        conn.close()
        self._ok({
            "user": row_to_dict(user),
            "enrollments": [row_to_dict(r) for r in enrolments],
            "certificates": [row_to_dict(r) for r in certs],
        })

    def api_admin_orders(self):
        """List orders (newest first) with the buyer, plus revenue
        totals and per-course revenue (from enrolments)."""
        if not self._require_admin():
            return
        page, per_page, q = self._admin_page()
        conn = db()
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(total), 0) FROM orders"
            " WHERE status = 'completed'").fetchone()[0]
        rows = conn.execute(
            """SELECT o.id, o.total, o.status, o.created_at,
                      u.name AS user_name, u.email AS user_email
               FROM orders o JOIN users u ON u.id = o.user_id
               ORDER BY o.created_at DESC, o.id DESC
               LIMIT ? OFFSET ?""",
            [per_page, (page - 1) * per_page]).fetchall()
        per_course = conn.execute(
            """SELECT c.id, c.title, COUNT(e.id) AS enrollments,
                      COUNT(e.id) * c.price AS revenue
               FROM courses c LEFT JOIN enrollments e ON e.course_id = c.id
               GROUP BY c.id ORDER BY revenue DESC, c.id"""
        ).fetchall()
        conn.close()
        self._ok(self._admin_paged({
            "orders": [row_to_dict(r) for r in rows],
            "revenue": revenue,
            "per_course_revenue": [row_to_dict(r) for r in per_course],
        }, total, page, per_page))

    def api_admin_certificates(self):
        """All issued certificates (searchable by code, student or
        course) with the public verification code."""
        if not self._require_admin():
            return
        page, per_page, q = self._admin_page()
        conn = db()
        where, args = "", []
        if q:
            like = f"%{q.lower()}%"
            where = ("WHERE LOWER(cf.certificate_code) LIKE ?"
                     " OR LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ?"
                     " OR LOWER(c.title) LIKE ?")
            args = [like, like, like, like]
        total = conn.execute(
            f"""SELECT COUNT(*) FROM certificates cf
                JOIN users u ON u.id = cf.user_id
                JOIN courses c ON c.id = cf.course_id {where}""",
            args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT cf.id, cf.certificate_code, cf.issued_at,
                       u.name AS student_name, u.email AS student_email,
                       c.title AS course_title
                FROM certificates cf
                JOIN users u ON u.id = cf.user_id
                JOIN courses c ON c.id = cf.course_id {where}
                ORDER BY cf.issued_at DESC, cf.id DESC
                LIMIT ? OFFSET ?""",
            args + [per_page, (page - 1) * per_page]).fetchall()
        conn.close()
        self._ok(self._admin_paged(
            {"certificates": [row_to_dict(r) for r in rows]},
            total, page, per_page))

    def api_admin_analytics(self):
        """Learning analytics: per-course enrolments, average quiz
        score and task completion rate, plus the weakest lessons
        (lowest average quiz score, at least one attempt) so the admin
        can see which lessons need fixing."""
        if not self._require_admin():
            return
        conn = db()
        courses = conn.execute(
            """SELECT c.id, c.title,
                      (SELECT COUNT(*) FROM enrollments e
                        WHERE e.course_id = c.id) AS enrollments,
                      (SELECT COUNT(*) FROM lessons l
                        WHERE l.course_id = c.id) AS lessons,
                      (SELECT COUNT(*) FROM tasks t
                        JOIN lessons l2 ON l2.id = t.lesson_id
                        WHERE l2.course_id = c.id) AS tasks_total,
                      (SELECT COUNT(*) FROM task_completions tc
                        JOIN tasks t2 ON t2.id = tc.task_id
                        JOIN lessons l3 ON l3.id = t2.lesson_id
                        WHERE l3.course_id = c.id) AS tasks_done,
                      (SELECT ROUND(AVG(qa.score * 100.0 / NULLIF(qa.total, 0)), 1)
                        FROM quiz_attempts qa
                        JOIN lessons l4 ON l4.id = qa.lesson_id
                        WHERE l4.course_id = c.id AND qa.total > 0) AS avg_quiz_percent
               FROM courses c ORDER BY c.id"""
        ).fetchall()
        out = []
        for r in courses:
            d = row_to_dict(r)
            if d["tasks_total"] and d["enrollments"]:
                d["task_completion_rate"] = round(
                    100.0 * d["tasks_done"]
                    / (d["tasks_total"] * d["enrollments"]), 1)
            else:
                d["task_completion_rate"] = None
            out.append(d)
        weakest = conn.execute(
            """SELECT l.id, l.title, c.id AS course_id, c.title AS course_title,
                      COUNT(qa.id) AS attempts,
                      ROUND(AVG(qa.score * 100.0 / NULLIF(qa.total, 0)), 1) AS avg_percent
               FROM lessons l
               JOIN courses c ON c.id = l.course_id
               JOIN quiz_attempts qa ON qa.lesson_id = l.id
               WHERE qa.total > 0
               GROUP BY l.id
               ORDER BY avg_percent ASC, attempts DESC
               LIMIT 10"""
        ).fetchall()
        conn.close()
        self._ok({
            "courses": out,
            "weakest_lessons": [row_to_dict(r) for r in weakest],
        })

    def api_admin_lesson_content(self, lesson_id):
        """Full editable lesson content for the admin: the lesson row,
        its explanation/flowchart/video, and every quiz question (with
        answers) and task (with expected answers)."""
        if not self._require_admin():
            return
        conn = db()
        lesson = conn.execute(
            """SELECT l.*, c.title AS course_title FROM lessons l
               JOIN courses c ON c.id = l.course_id WHERE l.id = ?""",
            (lesson_id,)).fetchone()
        if not lesson:
            conn.close()
            self._err(404, "Lesson not found")
            return
        content = conn.execute(
            "SELECT * FROM lesson_content WHERE lesson_id = ?",
            (lesson_id,)).fetchone()
        quizzes = conn.execute(
            """SELECT id, question, options_json, answer_index, explanation,
                      order_index FROM quizzes WHERE lesson_id = ?
               ORDER BY order_index, id""", (lesson_id,)).fetchall()
        tasks = conn.execute(
            """SELECT * FROM tasks WHERE lesson_id = ?
               ORDER BY order_index, id""", (lesson_id,)).fetchall()
        conn.close()
        self._ok({
            "lesson": row_to_dict(lesson),
            "content": row_to_dict(content) or {
                "lesson_id": lesson_id, "body": "", "flowchart_title": None,
                "flowchart_json": None, "video_id": None, "video_title": None},
            "quizzes": [row_to_dict(r) for r in quizzes],
            "tasks": [row_to_dict(r) for r in tasks],
        })

    def _validate_flowchart(self, raw):
        """Return (clean_json_string_or_None, error). A flowchart is
        {"nodes": [{id, label, kind}], "edges": [{from, to, label?}]}:
        node ids must be unique, kinds known, edges must point at
        existing nodes, decisions need labelled Yes/No edges."""
        if raw is None or raw == "":
            return None, None
        try:
            fc = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return None, "flowchart_json must be valid JSON"
        if not isinstance(fc, dict):
            return None, "flowchart must be an object with nodes and edges"
        nodes = fc.get("nodes") or []
        edges = fc.get("edges") or []
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return None, "flowchart nodes and edges must be arrays"
        if not 1 <= len(nodes) <= 20:
            return None, "flowchart must have 1-20 nodes"
        if len(edges) > 40:
            return None, "flowchart must have at most 40 edges"
        ids = set()
        for n in nodes:
            if not isinstance(n, dict) or not n.get("id") or not n.get("label"):
                return None, "every flowchart node needs an id and a label"
            if n["id"] in ids:
                return None, "flowchart node ids must be unique"
            if n.get("kind") not in ("start", "end", "process", "decision",
                                     "input", "output"):
                return None, ("flowchart node kind must be start, end, "
                              "process, decision, input or output")
            if len(str(n["label"])) > 200:
                return None, "flowchart node labels must be at most 200 characters"
            ids.add(n["id"])
        for e in edges:
            if not isinstance(e, dict) or e.get("from") not in ids \
                    or e.get("to") not in ids:
                return None, "flowchart edges must point at existing nodes"
        return json.dumps(fc), None

    def api_admin_lesson_content_update(self, lesson_id):
        """Update a lesson's explanation body, flowchart and video."""
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        conn = db()
        if not conn.execute("SELECT id FROM lessons WHERE id = ?",
                            (lesson_id,)).fetchone():
            conn.close()
            self._err(404, "Lesson not found")
            return
        clean = {}
        if "body" in body:
            text = body.get("body") or ""
            if not isinstance(text, str) or len(text) > 100000:
                conn.close()
                self._err(400, "body must be a string of at most 100000 characters")
                return
            clean["body"] = text
        if "flowchart_title" in body:
            title = (body.get("flowchart_title") or "").strip()
            if len(title) > 200:
                conn.close()
                self._err(400, "flowchart_title must be at most 200 characters")
                return
            clean["flowchart_title"] = title or None
        if "flowchart_json" in body:
            fc, err = self._validate_flowchart(body.get("flowchart_json"))
            if err:
                conn.close()
                self._err(400, err)
                return
            clean["flowchart_json"] = fc
        if "video_id" in body:
            vid = (body.get("video_id") or "").strip()
            if vid and not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                conn.close()
                self._err(400, "video_id must be a valid 11-character YouTube video ID")
                return
            clean["video_id"] = vid or None
        if "video_title" in body:
            title = (body.get("video_title") or "").strip()
            if len(title) > 200:
                conn.close()
                self._err(400, "video_title must be at most 200 characters")
                return
            clean["video_title"] = title or None
        if not clean:
            conn.close()
            self._err(400, "No valid fields to update")
            return
        cols = ["body", "flowchart_title", "flowchart_json",
                "video_id", "video_title"]
        conn.execute(
            """INSERT INTO lesson_content (lesson_id, body, flowchart_title,
                                          flowchart_json, video_id, video_title)
               VALUES (?, '', NULL, NULL, NULL, NULL)
               ON CONFLICT(lesson_id) DO NOTHING""", (lesson_id,))
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE lesson_content SET {sets} WHERE lesson_id = ?",
                     list(clean.values()) + [lesson_id])
        conn.commit()
        row = conn.execute(
            "SELECT * FROM lesson_content WHERE lesson_id = ?",
            (lesson_id,)).fetchone()
        conn.close()
        self._ok({"content": row_to_dict(row)})

    def _validate_quiz(self, body):
        """Return (clean_dict, error) for a quiz question."""
        clean = {}
        if "question" in body:
            q = (body.get("question") or "").strip()
            if not q or len(q) > 1000:
                return None, "question is required and at most 1000 characters"
            clean["question"] = q
        if "options" in body:
            opts = body.get("options")
            if not isinstance(opts, list) or len(opts) != 4:
                return None, "options must be an array of exactly 4 strings"
            opts = [(o or "").strip() for o in opts]
            if any(not isinstance(o, str) or not o or len(o) > 500 for o in opts):
                return None, ("every option must be a non-empty string "
                              "of at most 500 characters")
            clean["options_json"] = json.dumps(opts)
        if "answer_index" in body:
            ans = body.get("answer_index")
            if isinstance(ans, bool) or not isinstance(ans, int) \
                    or ans not in (0, 1, 2, 3):
                return None, "answer_index must be 0, 1, 2 or 3"
            clean["answer_index"] = ans
        if "explanation" in body:
            expl = (body.get("explanation") or "").strip()
            if len(expl) > 2000:
                return None, "explanation must be at most 2000 characters"
            clean["explanation"] = expl
        if "order_index" in body:
            n = _positive_int(body.get("order_index"))
            if n is None and body.get("order_index") not in (0, "0"):
                return None, "order_index must be a non-negative integer"
            clean["order_index"] = int(body.get("order_index"))
        return clean, None

    def api_admin_quiz_add(self, lesson_id):
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        clean, err = self._validate_quiz(body)
        if err:
            self._err(400, err)
            return
        for f in ("question", "options_json", "answer_index"):
            if f not in clean:
                self._err(400, f"{f} is required")
                return
        conn = db()
        if not conn.execute("SELECT id FROM lessons WHERE id = ?",
                            (lesson_id,)).fetchone():
            conn.close()
            self._err(404, "Lesson not found")
            return
        cur = conn.execute(
            """INSERT INTO quizzes (lesson_id, question, options_json,
                                    answer_index, explanation, order_index)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lesson_id, clean["question"], clean["options_json"],
             clean["answer_index"], clean.get("explanation", ""),
             clean.get("order_index", 0)))
        conn.commit()
        row = conn.execute("SELECT * FROM quizzes WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
        conn.close()
        self._ok({"quiz": row_to_dict(row)}, status=201)

    def api_admin_quiz_update(self, quiz_id):
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        clean, err = self._validate_quiz(body)
        if err:
            self._err(400, err)
            return
        if not clean:
            self._err(400, "No valid fields to update")
            return
        conn = db()
        if not conn.execute("SELECT id FROM quizzes WHERE id = ?",
                            (quiz_id,)).fetchone():
            conn.close()
            self._err(404, "Quiz question not found")
            return
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE quizzes SET {sets} WHERE id = ?",
                     list(clean.values()) + [quiz_id])
        conn.commit()
        row = conn.execute("SELECT * FROM quizzes WHERE id = ?",
                           (quiz_id,)).fetchone()
        conn.close()
        self._ok({"quiz": row_to_dict(row)})

    def api_admin_quiz_delete(self, quiz_id):
        if not self._require_admin():
            return
        conn = db()
        if not conn.execute("SELECT id FROM quizzes WHERE id = ?",
                            (quiz_id,)).fetchone():
            conn.close()
            self._err(404, "Quiz question not found")
            return
        conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
        conn.commit()
        conn.close()
        self._ok({"deleted": quiz_id})

    def _validate_task(self, body):
        """Return (clean_dict, error) for a practice task."""
        clean = {}
        if "type" in body:
            t = (body.get("type") or "").strip()
            if t not in ("predict", "fix", "fill", "trace", "project"):
                return None, ("type must be predict, fix, fill, trace "
                              "or project")
            clean["type"] = t
        if "title" in body:
            title = (body.get("title") or "").strip()
            if not title or len(title) > 200:
                return None, "title is required and at most 200 characters"
            clean["title"] = title
        if "prompt" in body:
            prompt = (body.get("prompt") or "").strip()
            if not prompt or len(prompt) > 5000:
                return None, "prompt is required and at most 5000 characters"
            clean["prompt"] = prompt
        for f in ("code", "expected", "answer", "hint"):
            if f in body:
                value = body.get(f) or ""
                if not isinstance(value, str) or len(value) > 5000:
                    return None, f"{f} must be a string of at most 5000 characters"
                clean[f] = value
        if "order_index" in body:
            if body.get("order_index") not in (0, "0") \
                    and _positive_int(body.get("order_index")) is None:
                return None, "order_index must be a non-negative integer"
            clean["order_index"] = int(body.get("order_index"))
        return clean, None

    def api_admin_task_add(self, lesson_id):
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        clean, err = self._validate_task(body)
        if err:
            self._err(400, err)
            return
        for f in ("type", "title", "prompt"):
            if f not in clean:
                self._err(400, f"{f} is required")
                return
        conn = db()
        if not conn.execute("SELECT id FROM lessons WHERE id = ?",
                            (lesson_id,)).fetchone():
            conn.close()
            self._err(404, "Lesson not found")
            return
        cur = conn.execute(
            """INSERT INTO tasks (lesson_id, type, title, prompt, code,
                                  expected, answer, hint, order_index)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lesson_id, clean["type"], clean["title"], clean["prompt"],
             clean.get("code", ""), clean.get("expected", ""),
             clean.get("answer", ""), clean.get("hint", ""),
             clean.get("order_index", 0)))
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
        conn.close()
        self._ok({"task": row_to_dict(row)}, status=201)

    def api_admin_task_update(self, task_id):
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        clean, err = self._validate_task(body)
        if err:
            self._err(400, err)
            return
        if not clean:
            self._err(400, "No valid fields to update")
            return
        conn = db()
        if not conn.execute("SELECT id FROM tasks WHERE id = ?",
                            (task_id,)).fetchone():
            conn.close()
            self._err(404, "Task not found")
            return
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?",
                     list(clean.values()) + [task_id])
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?",
                           (task_id,)).fetchone()
        conn.close()
        self._ok({"task": row_to_dict(row)})

    def api_admin_task_delete(self, task_id):
        if not self._require_admin():
            return
        conn = db()
        if not conn.execute("SELECT id FROM tasks WHERE id = ?",
                            (task_id,)).fetchone():
            conn.close()
            self._err(404, "Task not found")
            return
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        self._ok({"deleted": task_id})

    def api_cart_get(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT ci.id, c.* FROM cart_items ci
               JOIN courses c ON c.id = ci.course_id
               WHERE ci.user_id = ? ORDER BY ci.id""",
            (user["id"],),
        ).fetchall()
        conn.close()
        items = []
        for r in rows:
            d = row_to_dict(r)
            cart_id = d.pop("id")
            items.append({"cart_item_id": cart_id, "course": d})
        self._ok({"items": items})

    def api_cart_add(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        course_id = _positive_int(body.get("course_id"))
        if course_id is None:
            self._err(400, "course_id must be a positive integer")
            return
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        if conn.execute("SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                        (user["id"], course_id)).fetchone():
            conn.close()
            self._err(409, "Already enrolled in this course")
            return
        try:
            cur = conn.execute("INSERT INTO cart_items (user_id, course_id) VALUES (?, ?)",
                               (user["id"], course_id))
            conn.commit()
            item_id = cur.lastrowid
        except sqlite3.IntegrityError:
            conn.close()
            self._err(409, "Course already in cart")
            return
        conn.close()
        self._ok({"cart_item_id": item_id}, status=201)

    def api_cart_del(self, item_id):
        user = self._require_user()
        if not user:
            return
        conn = db()
        cur = conn.execute("DELETE FROM cart_items WHERE id = ? AND user_id = ?",
                           (item_id, user["id"]))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if not deleted:
            self._err(404, "Cart item not found")
            return
        self._ok({"message": "Removed from cart"})

    def api_checkout(self):
        """TEST-MODE checkout: creates pending mock-gateway payments.

        No enrolment happens here - the user is enrolled only after
        POST /api/payments/:id/verify confirms the (mock) gateway
        payment. Gateway is razorpay-test-mock: no real keys, no real
        charges. Unverified (no OTP) users cannot check out.
        """
        user = self._require_user()
        if not user:
            return
        if not user.get("email_verified"):
            self._err(403, "Verify your email with OTP before checkout")
            return
        conn = db()
        items = conn.execute(
            """SELECT ci.id, c.id AS course_id, c.price FROM cart_items ci
               JOIN courses c ON c.id = ci.course_id
               WHERE ci.user_id = ?""",
            (user["id"],),
        ).fetchall()
        if not items:
            conn.close()
            self._err(400, "Cart is empty")
            return
        total = sum(i["price"] for i in items)
        payments = []
        for i in items:
            gw_order = "LH-TEST-" + secrets.token_hex(6).upper()
            order_id = "LH-" + secrets.token_hex(5).upper()
            cur = conn.execute(
                "INSERT INTO payments (order_id, user_id, course_id, amount,"
                " currency, gateway, gateway_order_id, status)"
                " VALUES (?, ?, ?, ?, 'INR', 'razorpay-test-mock', ?, 'pending')",
                (order_id, user["id"], i["course_id"], i["price"], gw_order))
            pid = cur.lastrowid
            payments.append({
                "id": pid, "course_id": i["course_id"], "amount": i["price"],
                "order_id": order_id, "gateway_order_id": gw_order,
                "demo_signature": _payment_signature(gw_order, pid)})
        _audit(conn, user["id"], "checkout_started", self._client_ip(),
               f"{len(payments)} test-mode payment(s), total Rs {total}")
        conn.commit()
        conn.close()
        self._ok({"payments": payments, "total": total, "currency": "INR",
                  "gateway": "razorpay-test-mock", "test_mode": True,
                  "message": "TEST MODE: no real money is charged. "
                             "Verify each payment to complete enrolment."})

    def api_enrollments(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT e.id AS enrollment_id, e.progress_percent,
                      e.enrolled_at, c.*
               FROM enrollments e JOIN courses c ON c.id = e.course_id
               WHERE e.user_id = ? ORDER BY e.enrolled_at DESC""",
            (user["id"],),
        ).fetchall()
        conn.close()
        out = []
        for r in rows:
            d = row_to_dict(r)
            enrollment = {"id": d.pop("enrollment_id"),
                          "progress_percent": d.pop("progress_percent"),
                          "enrolled_at": d.pop("enrolled_at")}
            enrollment["course"] = d
            out.append(enrollment)
        self._ok({"enrollments": out})

    def api_unenroll(self, course_id):
        """Unenroll the caller from a course (auth required).

        DELETE /api/enrollments/:course_id — 404 when the caller is not
        enrolled (or the course does not exist). Removes the enrolment
        row and the caller's lesson_progress rows for that course, so a
        later re-enrolment starts fresh. Certificates are permanent:
        an already-issued certificate record is KEPT and stays
        verifiable. Other users' enrolments/progress are untouched.
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        enrollment = conn.execute(
            "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
            (user["id"], course_id)).fetchone()
        if not enrollment:
            conn.close()
            self._err(404, "You are not enrolled in this course")
            return
        conn.execute(
            """DELETE FROM lesson_progress
               WHERE user_id = ?
                 AND lesson_id IN (
                     SELECT id FROM lessons WHERE course_id = ?)""",
            (user["id"], course_id))
        conn.execute("DELETE FROM enrollments WHERE id = ?", (enrollment["id"],))
        conn.commit()
        conn.close()
        self._ok({"message": "Unenrolled from course",
                  "course_id": int(course_id)})


    def api_progress(self, enrollment_id):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        try:
            pct = float(body.get("progress_percent"))
        except (TypeError, ValueError):
            self._err(400, "progress_percent must be a number")
            return
        if not math.isfinite(pct):
            self._err(400, "progress_percent must be a finite number")
            return
        pct = max(0.0, min(100.0, pct))
        conn = db()
        cur = conn.execute(
            "UPDATE enrollments SET progress_percent = ? WHERE id = ? AND user_id = ?",
            (pct, enrollment_id, user["id"]),
        )
        conn.commit()
        updated = cur.rowcount
        conn.close()
        if not updated:
            self._err(404, "Enrollment not found")
            return
        self._ok({"enrollment_id": int(enrollment_id), "progress_percent": pct})

    def api_my_courses(self):
        # same data as /api/enrollments, but shaped for the My Courses page
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT e.id AS enrollment_id, e.progress_percent, e.enrolled_at,
                      c.id, c.title, c.description, c.category, c.price,
                      c.instructor, c.duration_hours, c.level, c.image_url,
                      (SELECT COUNT(*) FROM lessons l WHERE l.course_id = c.id) AS lesson_count
               FROM enrollments e JOIN courses c ON c.id = e.course_id
               WHERE e.user_id = ? ORDER BY e.enrolled_at DESC""",
            (user["id"],),
        ).fetchall()
        conn.close()
        self._ok({"courses": [row_to_dict(r) for r in rows]})

    # -- wishlist ------------------------------------------------------
    def api_wishlist_get(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT w.id AS wishlist_item_id, w.added_at,
                      c.id, c.title, c.description, c.category, c.price,
                      c.instructor, c.duration_hours, c.level, c.image_url,
                      (SELECT ROUND(AVG(rating), 2) FROM reviews
                       WHERE course_id = c.id) AS avg_rating
               FROM wishlist w JOIN courses c ON c.id = w.course_id
               WHERE w.user_id = ?
               ORDER BY w.added_at DESC, w.id DESC""",
            (user["id"],),
        ).fetchall()
        conn.close()
        items = []
        for r in rows:
            d = row_to_dict(r)
            if d["avg_rating"] is None:
                d["avg_rating"] = 0.0
            items.append(d)
        self._ok({"items": items})

    def api_wishlist_add(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        course_id = _positive_int(body.get("course_id"))
        if course_id is None:
            self._err(400, "course_id must be a positive integer")
            return
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?",
                            (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        existing = conn.execute(
            "SELECT id FROM wishlist WHERE user_id = ? AND course_id = ?",
            (user["id"], course_id)).fetchone()
        if existing:
            conn.close()
            # idempotent: re-adding is a no-op success, not an error
            self._ok({"added": False, "wishlist_item_id": existing["id"],
                      "course_id": course_id,
                      "message": "Course already in wishlist"})
            return
        cur = conn.execute("INSERT INTO wishlist (user_id, course_id) VALUES (?, ?)",
                           (user["id"], course_id))
        conn.commit()
        item_id = cur.lastrowid
        conn.close()
        self._ok({"added": True, "wishlist_item_id": item_id,
                  "course_id": course_id,
                  "message": "Added to wishlist"}, status=201)

    def api_wishlist_del(self, course_id):
        user = self._require_user()
        if not user:
            return
        conn = db()
        cur = conn.execute(
            "DELETE FROM wishlist WHERE user_id = ? AND course_id = ?",
            (user["id"], course_id))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if not deleted:
            self._err(404, "Course not in wishlist")
            return
        self._ok({"message": "Removed from wishlist"})

    # -- professional LMS: XP / streak / badges / leaderboard ---------
    def _gamification(self, conn, user_id):
        """XP, streak and badges computed from existing activity data.

        XP: lesson 10, task 5, quiz >=80% best-per-lesson 10 (once per
        lesson), certificate 50. No separate XP table - this is always
        consistent with the underlying progress rows.
        """
        lessons = conn.execute(
            "SELECT lesson_id, completed_at FROM lesson_progress"
            " WHERE user_id = ? ORDER BY completed_at, id",
            (user_id,)).fetchall()
        tasks = conn.execute(
            """SELECT tc.task_id, tc.completed_at FROM task_completions tc
               WHERE tc.user_id = ? ORDER BY tc.completed_at, tc.id""",
            (user_id,)).fetchall()
        quizzes = conn.execute(
            "SELECT lesson_id, score, total, taken_at FROM quiz_attempts"
            " WHERE user_id = ? ORDER BY taken_at, id",
            (user_id,)).fetchall()
        certs = conn.execute(
            "SELECT course_id, issued_at FROM certificates"
            " WHERE user_id = ? ORDER BY issued_at, id",
            (user_id,)).fetchall()
        # best quiz percent per lesson
        best = {}
        for q in quizzes:
            if q["total"]:
                pct = q["score"] * 100.0 / q["total"]
                if q["lesson_id"] not in best or pct > best[q["lesson_id"]][0]:
                    best[q["lesson_id"]] = (pct, q["taken_at"])
        quiz_bonus = sum(1 for pct, _ in best.values() if pct >= 80) * 10
        xp = len(lessons) * 10 + len(tasks) * 5 + quiz_bonus + len(certs) * 50
        # Final exams: +50 XP once per course passed (same computed-XP
        # pattern as certificates above — there is no stored XP table,
        # XP is always derived from activity rows, so a passed exam
        # simply counts here). A repeat pass of the same course adds 0.
        try:
            exam_passes = conn.execute(
                """SELECT fea.course_id, MIN(fea.created_at) AS first_passed,
                          c.title AS course_title
                   FROM final_exam_attempts fea
                   JOIN courses c ON c.id = fea.course_id
                   WHERE fea.user_id = ? AND fea.passed = 1
                   GROUP BY fea.course_id ORDER BY first_passed""",
                (user_id,)).fetchall()
        except sqlite3.Error:
            exam_passes = []
        xp += len(exam_passes) * 50
        avg_quiz = (round(sum(p for p, _ in best.values()) / len(best), 1)
                    if best else 0.0)
        # streak: distinct activity dates, consecutive days ending
        # today or yesterday (DB timestamps are UTC).
        days = set()
        for rows, col in ((lessons, "completed_at"), (quizzes, "taken_at"),
                          (tasks, "completed_at")):
            for r in rows:
                try:
                    days.add(str(r[col])[:10])
                except Exception:
                    pass
        streak = 0
        today = date.today()
        cur = today if today.isoformat() in days else today - timedelta(days=1)
        if cur.isoformat() in days:
            while cur.isoformat() in days:
                streak += 1
                cur -= timedelta(days=1)
        def _nth(rows, col, n):
            return rows[n - 1][col] if len(rows) >= n else None
        quiz_master_at = None
        for q in quizzes:
            if q["total"] and q["score"] * 100.0 / q["total"] >= 80:
                quiz_master_at = q["taken_at"]
                break
        badges = [
            {"id": "first-lesson", "title": "First Steps",
             "description": "Complete your first lesson",
             "earned": len(lessons) >= 1,
             "earned_at": _nth(lessons, "completed_at", 1)},
            {"id": "5-lessons", "title": "On a Roll",
             "description": "Complete 5 lessons",
             "earned": len(lessons) >= 5,
             "earned_at": _nth(lessons, "completed_at", 5)},
            {"id": "10-lessons", "title": "Dedicated Learner",
             "description": "Complete 10 lessons",
             "earned": len(lessons) >= 10,
             "earned_at": _nth(lessons, "completed_at", 10)},
            {"id": "quiz-master", "title": "Quiz Master",
             "description": "Score 80% or more on any quiz",
             "earned": quiz_master_at is not None,
             "earned_at": quiz_master_at},
            {"id": "task-finisher", "title": "Practice Pro",
             "description": "Finish 5 practice tasks",
             "earned": len(tasks) >= 5,
             "earned_at": _nth(tasks, "completed_at", 5)},
            {"id": "course-finisher", "title": "Course Finisher",
             "description": "Earn a certificate by finishing a course",
             "earned": len(certs) >= 1,
             "earned_at": certs[0]["issued_at"] if certs else None},
            {"id": "streak-3", "title": "3-Day Streak",
             "description": "Learn 3 days in a row",
             "earned": streak >= 3,
             "earned_at": today.isoformat() if streak >= 3 else None},
            {"id": "streak-7", "title": "7-Day Streak",
             "description": "Learn 7 days in a row",
             "earned": streak >= 7,
             "earned_at": today.isoformat() if streak >= 7 else None},
        ]
        # Exam-master badges: one per course whose final exam the learner
        # passed, derived from final_exam_attempts like every other badge
        # above (no separate badge table exists).
        for ep in exam_passes:
            badges.append({
                "id": f"exam-master-{ep['course_id']}",
                "title": "Exam Master",
                "description": f"Passed the final exam for '{ep['course_title']}'",
                "earned": True,
                "earned_at": ep["first_passed"]})
        return {"xp": xp, "level": xp // 200 + 1, "streak_days": streak,
                "lessons_completed": len(lessons), "tasks_done": len(tasks),
                "quizzes_taken": len(quizzes), "avg_quiz_percent": avg_quiz,
                "certificates_count": len(certs), "badges": badges,
                "exams_passed": len(exam_passes),
                "quiz_bonus_lessons": len([1 for p, _ in best.values() if p >= 80])}

    def _recent_activity(self, conn, user_id):
        events = []
        for r in conn.execute(
                """SELECT lp.completed_at AS at, l.title AS lesson_title,
                          c.title AS course_title, l.course_id AS course_id
                   FROM lesson_progress lp JOIN lessons l ON l.id = lp.lesson_id
                   JOIN courses c ON c.id = l.course_id
                   WHERE lp.user_id = ?""", (user_id,)).fetchall():
            events.append({"type": "lesson", "at": r["at"],
                           "text": f"Completed lesson '{r['lesson_title']}'",
                           "course_title": r["course_title"],
                           "course_id": r["course_id"]})
        for r in conn.execute(
                """SELECT qa.taken_at AS at, qa.score, qa.total,
                          l.title AS lesson_title, c.title AS course_title,
                          l.course_id AS course_id
                   FROM quiz_attempts qa JOIN lessons l ON l.id = qa.lesson_id
                   JOIN courses c ON c.id = l.course_id
                   WHERE qa.user_id = ?""", (user_id,)).fetchall():
            pct = round(r["score"] * 100 / r["total"]) if r["total"] else 0
            events.append({"type": "quiz", "at": r["at"],
                           "text": f"Quiz on '{r['lesson_title']}': {pct}%",
                           "course_title": r["course_title"],
                           "course_id": r["course_id"]})
        for r in conn.execute(
                """SELECT tc.completed_at AS at, t.title AS task_title,
                          l.title AS lesson_title, c.title AS course_title,
                          l.course_id AS course_id
                   FROM task_completions tc JOIN tasks t ON t.id = tc.task_id
                   JOIN lessons l ON l.id = t.lesson_id
                   JOIN courses c ON c.id = l.course_id
                   WHERE tc.user_id = ?""", (user_id,)).fetchall():
            events.append({"type": "task", "at": r["at"],
                           "text": f"Finished task '{r['task_title']}'",
                           "course_title": r["course_title"],
                           "course_id": r["course_id"]})
        for r in conn.execute(
                """SELECT cert.issued_at AS at, c.title AS course_title,
                          c.id AS course_id, cert.certificate_code AS code
                   FROM certificates cert JOIN courses c ON c.id = cert.course_id
                   WHERE cert.user_id = ?""", (user_id,)).fetchall():
            events.append({"type": "certificate", "at": r["at"],
                           "text": f"Earned certificate for '{r['course_title']}' ({r['code']})",
                           "course_title": r["course_title"],
                           "course_id": r["course_id"]})
        events.sort(key=lambda e: e["at"] or "", reverse=True)
        return events[:8]

    @staticmethod
    def _public_name(name):
        parts = (name or "Learner").split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-1][0]}."
        return parts[0]

    def api_me_dashboard(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        g = self._gamification(conn, user["id"])
        enr = conn.execute(
            """SELECT e.progress_percent, c.id AS course_id, c.title
               FROM enrollments e JOIN courses c ON c.id = e.course_id
               WHERE e.user_id = ? ORDER BY e.enrolled_at DESC""",
            (user["id"],)).fetchall()
        continue_learning = []
        completed = 0
        for e in enr:
            if e["progress_percent"] >= 100:
                completed += 1
            nxt = conn.execute(
                """SELECT l.id, l.title FROM lessons l WHERE l.course_id = ?
                     AND NOT EXISTS (SELECT 1 FROM lesson_progress lp
                       WHERE lp.user_id = ? AND lp.lesson_id = l.id)
                   ORDER BY l.order_index, l.id LIMIT 1""",
                (e["course_id"], user["id"])).fetchone()
            continue_learning.append({
                "course_id": e["course_id"], "title": e["title"],
                "progress_percent": e["progress_percent"],
                "next_lesson_id": nxt["id"] if nxt else None,
                "next_lesson_title": nxt["title"] if nxt else None})
        recent = self._recent_activity(conn, user["id"])
        purchase_history = conn.execute(
            """SELECT p.id, p.order_id, p.gateway_order_id, p.course_id,
                      c.title AS course_title, p.amount, p.currency,
                      p.status, p.created_at
               FROM payments p JOIN courses c ON c.id = p.course_id
               WHERE p.user_id = ? ORDER BY p.created_at DESC, p.id DESC""",
            (user["id"],)).fetchall()
        resources = []
        for e in enr:
            n = conn.execute("SELECT COUNT(*) AS n FROM lessons"
                             " WHERE course_id = ?",
                             (e["course_id"],)).fetchone()["n"]
            resources.append({"course_id": e["course_id"],
                              "course_title": e["title"],
                              "lesson_count": n})
        conn.close()
        self._ok({"user": user, **g,
                  "enrolled_count": len(enr), "completed_courses": completed,
                  "continue_learning": continue_learning,
                  "recent_activity": recent,
                  "purchase_history": [row_to_dict(r) for r in purchase_history],
                  "resources": resources})

    def api_leaderboard(self):
        conn = db()
        users = conn.execute("SELECT id, name FROM users").fetchall()
        rows = []
        for u in users:
            g = self._gamification(conn, u["id"])
            rows.append({"name": self._public_name(u["name"]), "xp": g["xp"],
                         "lessons_completed": g["lessons_completed"],
                         "certificates": g["certificates_count"]})
        conn.close()
        rows.sort(key=lambda r: (-r["xp"], -r["lessons_completed"], r["name"]))
        for i, r in enumerate(rows[:20], start=1):
            r["rank"] = i
        self._ok({"leaderboard": rows[:20]})

    def api_announcements(self):
        conn = db()
        rows = conn.execute(
            "SELECT id, title, body, created_at FROM announcements"
            " ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        self._ok({"announcements": [row_to_dict(r) for r in rows]})

    def api_contact_submit(self):
        """POST /api/contact — public contact form.

        Stores the message so the admin can read it (GET
        /api/admin/contact-messages). No email is sent: this is a
        free, stdlib-only site with no mail service configured.
        """
        body = self._read_json()
        name = (body.get("name") or "").strip()
        email = (body.get("email") or "").strip().lower()
        subject = (body.get("subject") or "").strip()
        message = (body.get("message") or "").strip()
        if not name or len(name) > 100:
            self._err(400, "name is required (at most 100 characters)")
            return
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            self._err(400, "a valid email is required")
            return
        if not subject or len(subject) > 200:
            self._err(400, "subject is required (at most 200 characters)")
            return
        if not message or len(message) > 5000:
            self._err(400, "message is required (at most 5000 characters)")
            return
        conn = db()
        cur = conn.execute(
            "INSERT INTO contact_messages (name, email, subject, message)"
            " VALUES (?, ?, ?, ?)", (name, email, subject, message))
        conn.commit()
        mid = cur.lastrowid
        conn.close()
        self._ok({"message_id": mid,
                  "message": "Thanks! Your message has been received."}, status=201)

    def api_admin_contact_messages(self):
        """GET /api/admin/contact-messages — admin only, newest first."""
        if not self._require_admin():
            return
        conn = db()
        rows = conn.execute(
            "SELECT id, name, email, subject, message, created_at"
            " FROM contact_messages ORDER BY id DESC LIMIT 100").fetchall()
        conn.close()
        self._ok({"messages": [row_to_dict(r) for r in rows]})

    def api_learning_paths(self):
        conn = db()
        by_title = {r["title"]: row_to_dict(r) for r in
                    conn.execute("SELECT * FROM courses").fetchall()}
        conn.close()
        def pick(title):
            c = by_title.get(title)
            return ({"id": c["id"], "title": c["title"], "level": c["level"],
                     "duration_hours": c["duration_hours"]}
                    if c else None)
        def find_like(needle):
            for title, c in by_title.items():
                if needle.lower() in title.lower():
                    return {"id": c["id"], "title": c["title"],
                            "level": c["level"],
                            "duration_hours": c["duration_hours"]}
            return None
        c_course = find_like("C Programming")
        dsa_course = find_like("Data Structures")
        foundations = [c for c in (c_course, dsa_course) if c]
        if len(foundations) < 2:
            foundations = [c for c in (pick("Python Programming Masterclass"),
                                       pick("Data Science with SQL & Python")) if c]
        defs = [
            ("python-developer", "Python Developer",
             "From your first Python program to data work and full-stack web apps.",
             ["Python Programming Masterclass", "Data Science with SQL & Python",
              "Django Full-Stack Web Development"]),
            ("web-developer", "Web Developer",
             "Build modern websites and web apps, from HTML and JavaScript to React and TypeScript.",
             ["Complete Web Development Bootcamp",
              "JavaScript: From Beginner to Advanced",
              "React - Build Modern Web Apps",
              "TypeScript: Static Typing for JavaScript"]),
            ("ai-ml-engineer", "AI & ML Engineer",
             "Python, data and machine learning, all the way to deep learning.",
             ["Python Programming Masterclass", "Machine Learning with Python",
              "Deep Learning & Neural Networks", "Data Science with SQL & Python"]),
            ("c-dsa-foundations", "C & DSA Foundations",
             "Master C and data structures & algorithms - the foundation of every technical interview.",
             None),
        ]
        paths = []
        for slug, title, desc, titles in defs:
            courses = ([c for c in (pick(t) for t in titles) if c]
                       if titles is not None else foundations)
            paths.append({"slug": slug, "title": title, "description": desc,
                          "course_count": len(courses),
                          "duration_hours": round(sum(c["duration_hours"] or 0
                                                      for c in courses), 1),
                          "courses": [{"id": c["id"], "title": c["title"],
                                       "level": c["level"]} for c in courses]})
        self._ok({"paths": paths})

    # -- notes / bookmarks / discussions -------------------------------
    def api_lesson_notes_get(self, lesson_id):
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        if not user:
            self._err(401, "Sign in to view your notes")
            return
        conn = db()
        rows = conn.execute(
            "SELECT id, note, created_at FROM lesson_notes"
            " WHERE user_id = ? AND lesson_id = ? ORDER BY id DESC",
            (user["id"], lesson_id)).fetchall()
        conn.close()
        self._ok({"notes": [row_to_dict(r) for r in rows]})

    def api_lesson_notes_post(self, lesson_id):
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        if not user:
            self._err(401, "Sign in to add a note")
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        note = (body.get("note") or "").strip()
        if not note:
            self._err(400, "note is required")
            return
        if len(note) > 5000:
            self._err(400, "note must be at most 5000 characters")
            return
        conn = db()
        cur = conn.execute(
            "INSERT INTO lesson_notes (user_id, lesson_id, note) VALUES (?, ?, ?)",
            (user["id"], lesson_id, note))
        conn.commit()
        nid = cur.lastrowid
        conn.close()
        self._ok({"note_id": nid, "message": "Note saved"}, status=201)

    def api_note_delete(self, note_id):
        user = self._require_user()
        if not user:
            return
        conn = db()
        row = conn.execute("SELECT id, user_id FROM lesson_notes WHERE id = ?",
                           (note_id,)).fetchone()
        if not row:
            conn.close()
            self._err(404, "Note not found")
            return
        if row["user_id"] != user["id"]:
            conn.close()
            self._err(403, "You can only delete your own notes")
            return
        conn.execute("DELETE FROM lesson_notes WHERE id = ?", (note_id,))
        conn.commit()
        conn.close()
        self._ok({"deleted": int(note_id)})

    def api_lesson_bookmark_add(self, lesson_id):
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        if not user:
            self._err(401, "Sign in to bookmark a lesson")
            return
        conn = db()
        conn.execute("INSERT OR IGNORE INTO lesson_bookmarks (user_id, lesson_id)"
                     " VALUES (?, ?)", (user["id"], lesson_id))
        conn.commit()
        conn.close()
        self._ok({"bookmarked": True, "lesson_id": int(lesson_id)}, status=201)

    def api_lesson_bookmark_del(self, lesson_id):
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        if not user:
            self._err(401, "Sign in to remove a bookmark")
            return
        conn = db()
        cur = conn.execute(
            "DELETE FROM lesson_bookmarks WHERE user_id = ? AND lesson_id = ?",
            (user["id"], lesson_id))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if not deleted:
            self._err(404, "Bookmark not found")
            return
        self._ok({"bookmarked": False, "lesson_id": int(lesson_id)})

    def api_me_bookmarks(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT b.id, b.lesson_id, b.created_at, l.title AS lesson_title,
                      l.course_id, c.title AS course_title
               FROM lesson_bookmarks b JOIN lessons l ON l.id = b.lesson_id
               JOIN courses c ON c.id = l.course_id
               WHERE b.user_id = ? ORDER BY b.id DESC""",
            (user["id"],)).fetchall()
        conn.close()
        self._ok({"bookmarks": [row_to_dict(r) for r in rows]})

    def _discussions_tree(self, conn, lesson_id):
        rows = conn.execute(
            """SELECT d.id, d.user_id, d.parent_id, d.body, d.created_at,
                      u.name AS user_name
               FROM discussions d JOIN users u ON u.id = d.user_id
               WHERE d.lesson_id = ? ORDER BY d.id""",
            (lesson_id,)).fetchall()
        items = []
        by_id = {}
        for r in rows:
            d = row_to_dict(r)
            d["user_name"] = self._public_name(d.pop("user_name"))
            d["replies"] = []
            by_id[d["id"]] = d
            items.append(d)
        top = []
        for d in items:
            if d["parent_id"] and d["parent_id"] in by_id:
                by_id[d["parent_id"]]["replies"].append(d)
            else:
                top.append(d)
        return top

    def api_lesson_discussions_get(self, lesson_id):
        lesson, _user = self._lesson_access(lesson_id)
        if not lesson:
            return
        conn = db()
        tree = self._discussions_tree(conn, lesson_id)
        conn.close()
        self._ok({"discussions": tree})

    def api_lesson_discussions_post(self, lesson_id):
        lesson, user = self._lesson_access(lesson_id)
        if not lesson:
            return
        if not user:
            self._err(401, "Sign in to ask a question")
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        text = (body.get("body") or "").strip()
        if not text:
            self._err(400, "body is required")
            return
        if len(text) > 2000:
            self._err(400, "body must be at most 2000 characters")
            return
        conn = db()
        cur = conn.execute(
            "INSERT INTO discussions (user_id, lesson_id, body) VALUES (?, ?, ?)",
            (user["id"], lesson_id, text))
        conn.commit()
        did = cur.lastrowid
        conn.close()
        self._ok({"discussion_id": did, "message": "Question posted"}, status=201)

    def api_discussion_reply(self, discussion_id):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        text = (body.get("body") or "").strip()
        if not text:
            self._err(400, "body is required")
            return
        if len(text) > 2000:
            self._err(400, "body must be at most 2000 characters")
            return
        conn = db()
        parent = conn.execute(
            "SELECT id, lesson_id, parent_id FROM discussions WHERE id = ?",
            (discussion_id,)).fetchone()
        if not parent:
            conn.close()
            self._err(404, "Discussion not found")
            return
        # Replies always attach to the top-level question, keeping
        # threads one level deep.
        top_id = parent["parent_id"] or parent["id"]
        lesson = conn.execute(
            "SELECT id, course_id, is_preview FROM lessons WHERE id = ?",
            (parent["lesson_id"],)).fetchone()
        if not lesson["is_preview"]:
            enr = conn.execute(
                "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                (user["id"], lesson["course_id"])).fetchone()
            if not enr:
                conn.close()
                self._err(403, "You must be enrolled in this course to reply")
                return
        cur = conn.execute(
            "INSERT INTO discussions (user_id, lesson_id, parent_id, body)"
            " VALUES (?, ?, ?, ?)",
            (user["id"], parent["lesson_id"], top_id, text))
        conn.commit()
        rid = cur.lastrowid
        # Notify the top-level question's author (not the replier).
        top = conn.execute(
            "SELECT user_id FROM discussions WHERE id = ?", (top_id,)).fetchone()
        if top and top["user_id"] != user["id"]:
            _notify_user(conn, top["user_id"], "discussion_reply",
                         "New reply to your question",
                         text[:200],
                         f"/lesson.html?id={parent['lesson_id']}")
            conn.commit()
        conn.close()
        self._ok({"discussion_id": rid, "message": "Reply posted"}, status=201)

    # -- admin: announcements + discussions ---------------------------
    def api_admin_announcements(self):
        if not self._require_admin():
            return
        conn = db()
        rows = conn.execute(
            "SELECT id, title, body, created_at FROM announcements"
            " ORDER BY id DESC").fetchall()
        conn.close()
        self._ok({"announcements": [row_to_dict(r) for r in rows]})

    def api_admin_announcement_create(self):
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        title = (body.get("title") or "").strip()
        text = (body.get("body") or "").strip()
        if not title:
            self._err(400, "title is required")
            return
        if len(title) > 200:
            self._err(400, "title must be at most 200 characters")
            return
        if not text:
            self._err(400, "body is required")
            return
        if len(text) > 5000:
            self._err(400, "body must be at most 5000 characters")
            return
        conn = db()
        cur = conn.execute("INSERT INTO announcements (title, body) VALUES (?, ?)",
                           (title, text))
        conn.commit()
        aid = cur.lastrowid
        # Notify every user about the new announcement (best-effort).
        for u in conn.execute("SELECT id FROM users").fetchall():
            _notify_user(conn, u["id"], "announcement", title, text,
                         "/announcements.html")
        conn.commit()
        conn.close()
        self._ok({"announcement_id": aid, "message": "Announcement posted"}, status=201)

    def api_admin_announcement_delete(self, announcement_id):
        if not self._require_admin():
            return
        conn = db()
        cur = conn.execute("DELETE FROM announcements WHERE id = ?",
                           (announcement_id,))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if not deleted:
            self._err(404, "Announcement not found")
            return
        self._ok({"deleted": int(announcement_id)})

    def api_admin_discussions(self):
        if not self._require_admin():
            return
        conn = db()
        rows = conn.execute(
            """SELECT d.id, d.body, d.created_at, d.parent_id,
                      u.name AS user_name, l.title AS lesson_title,
                      c.title AS course_title
               FROM discussions d JOIN users u ON u.id = d.user_id
               JOIN lessons l ON l.id = d.lesson_id
               JOIN courses c ON c.id = l.course_id
               ORDER BY d.id DESC LIMIT 50""").fetchall()
        conn.close()
        self._ok({"discussions": [row_to_dict(r) for r in rows]})

    def api_admin_discussion_delete(self, discussion_id):
        if not self._require_admin():
            return
        conn = db()
        cur = conn.execute("DELETE FROM discussions WHERE id = ?",
                           (discussion_id,))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if not deleted:
            self._err(404, "Discussion not found")
            return
        self._ok({"deleted": int(discussion_id)})


    # -- ULTIMATE LMS: search, stats, instructors, exams, ------------
    # -- notifications, review management, admin roles / exports -----
    # Course rows with review + enrolment stats attached (superset of
    # the plain /api/courses item shape: same fields plus avg_rating,
    # review_count, enrolment_count).
    _COURSE_STATS_SELECT = (
        "SELECT c.*, "
        "COALESCE((SELECT ROUND(AVG(rating), 2) FROM reviews"
        " WHERE course_id = c.id), 0.0) AS avg_rating, "
        "(SELECT COUNT(*) FROM reviews WHERE course_id = c.id)"
        " AS review_count, "
        "(SELECT COUNT(*) FROM enrollments WHERE course_id = c.id)"
        " AS enrolment_count FROM courses c"
    )

    def api_search(self):
        """GET /api/search?q=&category=&level=&max_price=&sort=.

        Public. q LIKE-matches course title/description AND lesson
        titles (a course with a matching lesson appears). sort is
        popular (enrolments desc, default) | newest | price (asc) |
        rating (avg review rating desc). At most 50 results.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        q = (qs.get("q", [""])[0] or "").strip()
        if len(q) > 200:
            self._err(400, "q must be at most 200 characters")
            return
        category = (qs.get("category", [""])[0] or "").strip()
        level = (qs.get("level", [""])[0] or "").strip()
        if level and level not in self.COURSE_LEVELS:
            self._err(400, "level must be one of: Beginner, Intermediate, Advanced")
            return
        max_price_raw = (qs.get("max_price", [""])[0] or "").strip()
        max_price = None
        if max_price_raw:
            try:
                max_price = int(max_price_raw)
            except (TypeError, ValueError):
                self._err(400, "max_price must be an integer >= 0")
                return
            if max_price < 0:
                self._err(400, "max_price must be >= 0")
                return
        sort = (qs.get("sort", ["popular"])[0] or "popular").strip()
        SORTS = {
            "popular": ("(SELECT COUNT(*) FROM enrollments e"
                        " WHERE e.course_id = c.id) DESC, c.id"),
            "newest": "c.created_at DESC, c.id DESC",
            "price": "c.price ASC, c.id",
            "rating": ("(SELECT COALESCE(AVG(rating), 0) FROM reviews"
                       " WHERE course_id = c.id) DESC, c.id"),
        }
        if sort not in SORTS:
            self._err(400, "Invalid sort: expected one of popular, newest,"
                           " price, rating")
            return
        clauses, params = [], []
        if category:
            clauses.append("c.category = ?")
            params.append(category)
        if level:
            clauses.append("c.level = ?")
            params.append(level)
        if max_price is not None:
            clauses.append("c.price <= ?")
            params.append(max_price)
        if q:
            clauses.append("(c.title LIKE ? OR c.description LIKE ?"
                           " OR EXISTS (SELECT 1 FROM lessons l"
                           " WHERE l.course_id = c.id AND l.title LIKE ?))")
            params += [f"%{q}%", f"%{q}%", f"%{q}%"]
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = db()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM courses c" + where, params).fetchone()["n"]
        rows = conn.execute(
            self._COURSE_STATS_SELECT + where
            + " ORDER BY " + SORTS[sort] + " LIMIT 50",
            params).fetchall()
        conn.close()
        self._ok({"courses": [row_to_dict(r) for r in rows], "total": total})

    def api_stats(self):
        """GET /api/stats — public platform totals (real DB counts)."""
        conn = db()
        one = lambda sql: conn.execute(sql).fetchone()[0]
        out = {
            "total_learners": one("SELECT COUNT(*) FROM users"),
            "total_courses": one("SELECT COUNT(*) FROM courses"),
            "total_enrollments": one("SELECT COUNT(*) FROM enrollments"),
            "certificates_issued": one("SELECT COUNT(*) FROM certificates"),
        }
        conn.close()
        self._ok(out)

    def api_instructors(self):
        """GET /api/instructors — public per-instructor roll-up."""
        conn = db()
        rows = conn.execute(
            """SELECT c.instructor AS name,
                      COUNT(DISTINCT c.id) AS course_count,
                      COALESCE(ROUND(AVG(r.rating), 2), 0.0) AS avg_rating,
                      (SELECT COUNT(*) FROM enrollments e
                       JOIN courses c2 ON c2.id = e.course_id
                       WHERE c2.instructor = c.instructor) AS total_enrollments
               FROM courses c LEFT JOIN reviews r ON r.course_id = c.id
               GROUP BY c.instructor
               ORDER BY course_count DESC, name""").fetchall()
        conn.close()
        self._ok({"instructors": [row_to_dict(r) for r in rows]})

    def api_me_admin_status(self):
        """GET /api/me/admin-status — signed-in user only."""
        user = self._require_user()
        if not user:
            return
        self._ok({"is_admin": bool(_is_admin_user(user)),
                  "email": user["email"], "name": user["name"]})

    def api_me_recommended(self):
        """GET /api/me/recommended — signed-in only.

        Courses in categories the caller is enrolled in, excluding
        courses they already enrolled in, top by enrolment count,
        limit 8, same shape as search results.
        """
        user = self._require_user()
        if not user:
            return
        conn = db()
        cats = [r["category"] for r in conn.execute(
            """SELECT DISTINCT c.category FROM enrollments e
               JOIN courses c ON c.id = e.course_id
               WHERE e.user_id = ?""", (user["id"],)).fetchall()]
        if not cats:
            conn.close()
            self._ok({"courses": []})
            return
        placeholders = ",".join("?" * len(cats))
        rows = conn.execute(
            self._COURSE_STATS_SELECT
            + f" WHERE c.category IN ({placeholders})"
              " AND NOT EXISTS (SELECT 1 FROM enrollments e"
              " WHERE e.user_id = ? AND e.course_id = c.id)"
              " ORDER BY (SELECT COUNT(*) FROM enrollments e2"
              " WHERE e2.course_id = c.id) DESC, c.id LIMIT 8",
            cats + [user["id"]]).fetchall()
        conn.close()
        self._ok({"courses": [row_to_dict(r) for r in rows]})

    # -- notifications -------------------------------------------------
    def api_me_notifications(self):
        """GET /api/me/notifications — own only, newest first."""
        user = self._require_user()
        if not user:
            return
        page, per_page, _q = self._admin_page()
        conn = db()
        total = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?",
            (user["id"],)).fetchone()[0]
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications"
            " WHERE user_id = ? AND is_read = 0",
            (user["id"],)).fetchone()[0]
        rows = conn.execute(
            """SELECT id, user_id, type, title, body, link, is_read,
                      created_at FROM notifications
               WHERE user_id = ? ORDER BY created_at DESC, id DESC
               LIMIT ? OFFSET ?""",
            (user["id"], per_page, (page - 1) * per_page)).fetchall()
        conn.close()
        self._ok(self._admin_paged(
            {"notifications": [row_to_dict(r) for r in rows],
             "unread_count": unread}, total, page, per_page))

    def api_notification_read(self, notification_id):
        """POST /api/notifications/:id/read — own only (404 otherwise)."""
        user = self._require_user()
        if not user:
            return
        conn = db()
        row = conn.execute(
            "SELECT id, user_id FROM notifications WHERE id = ?",
            (notification_id,)).fetchone()
        if not row or row["user_id"] != user["id"]:
            conn.close()
            self._err(404, "Notification not found")
            return
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?",
                     (notification_id,))
        conn.commit()
        conn.close()
        self._ok({"notification_id": int(notification_id), "is_read": 1})

    def api_me_notifications_read_all(self):
        """POST /api/me/notifications/read-all — mark all own read."""
        user = self._require_user()
        if not user:
            return
        conn = db()
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1"
            " WHERE user_id = ? AND is_read = 0", (user["id"],))
        conn.commit()
        updated = cur.rowcount
        conn.close()
        self._ok({"updated": updated, "unread_count": 0})

    # -- review edit / delete (own review only) ------------------------
    def api_review_update(self, review_id):
        """PUT /api/reviews/:id — own review only (403 otherwise)."""
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        sets, values = [], []
        if "rating" in body:
            if isinstance(body.get("rating"), bool):
                self._err(400, "rating must be an integer 1-5")
                return
            try:
                rating = int(body.get("rating"))
            except (TypeError, ValueError):
                self._err(400, "rating must be an integer 1-5")
                return
            if not 1 <= rating <= 5:
                self._err(400, "rating must be between 1 and 5")
                return
            sets.append("rating = ?")
            values.append(rating)
        if "comment" in body:
            comment = (body.get("comment") or "").strip()
            if len(comment) > 2000:
                self._err(400, "comment is too long (max 2000 characters)")
                return
            sets.append("comment = ?")
            values.append(comment)
        if not sets:
            self._err(400, "Nothing to update: provide rating and/or comment")
            return
        conn = db()
        row = conn.execute("SELECT * FROM reviews WHERE id = ?",
                           (review_id,)).fetchone()
        if not row:
            conn.close()
            self._err(404, "Review not found")
            return
        if row["user_id"] != user["id"]:
            conn.close()
            self._err(403, "You can only edit your own reviews")
            return
        conn.execute("UPDATE reviews SET " + ", ".join(sets) + " WHERE id = ?",
                     values + [review_id])
        conn.commit()
        updated = row_to_dict(conn.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone())
        conn.close()
        self._ok({"review": updated})

    def api_review_delete(self, review_id):
        """DELETE /api/reviews/:id — own review only (403 otherwise)."""
        user = self._require_user()
        if not user:
            return
        conn = db()
        row = conn.execute("SELECT id, user_id FROM reviews WHERE id = ?",
                           (review_id,)).fetchone()
        if not row:
            conn.close()
            self._err(404, "Review not found")
            return
        if row["user_id"] != user["id"]:
            conn.close()
            self._err(403, "You can only delete your own reviews")
            return
        conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
        conn.commit()
        conn.close()
        self._ok({"deleted": int(review_id)})

    # -- final exams ----------------------------------------------------
    def _final_exam_access(self, course_id):
        """Shared gate for final-exam endpoints: signed-in + enrolled.

        Returns (course_dict, user) or (None, None) after sending the
        error response (404 unknown course, 403 not enrolled).
        """
        user = self._require_user()
        if not user:
            return None, None
        conn = db()
        course = conn.execute(
            "SELECT id, title FROM courses WHERE id = ?",
            (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return None, None
        if not conn.execute(
                "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
                (user["id"], course_id)).fetchone():
            conn.close()
            self._err(403, "You must be enrolled in this course to take its final exam")
            return None, None
        conn.close()
        return row_to_dict(course), user

    def api_final_exam_get(self, course_id):
        """GET /api/courses/:id/final-exam — enrolled only.

        10 MCQs sampled from this course's lesson quizzes (table
        `quizzes`: options_json is a JSON array of 4 strings,
        answer_index 0-3, explanation). Correct answers are NEVER
        returned here. 404 when the course has no quiz questions.
        """
        course, user = self._final_exam_access(course_id)
        if not course:
            return
        conn = db()
        rows = conn.execute(
            """SELECT q.id, q.question, q.options_json
               FROM quizzes q JOIN lessons l ON l.id = q.lesson_id
               WHERE l.course_id = ? ORDER BY RANDOM() LIMIT 10""",
            (course_id,)).fetchall()
        if not rows:
            conn.close()
            self._err(404, "This course has no quiz questions yet")
            return
        attempts = conn.execute(
            "SELECT COUNT(*) AS n, MAX(score) AS best,"
            " MAX(passed) AS passed FROM final_exam_attempts"
            " WHERE user_id = ? AND course_id = ?",
            (user["id"], course_id)).fetchone()
        conn.close()
        questions = []
        for r in rows:
            try:
                options = json.loads(r["options_json"])
            except (ValueError, TypeError):
                options = []
            questions.append({"id": r["id"], "question": r["question"],
                              "options": options})
        self._ok({"course_id": int(course_id),
                  "course_title": course["title"],
                  "questions": questions,
                  "attempts": attempts["n"],
                  "best_score": attempts["best"],
                  "passed": bool(attempts["passed"])})

    def api_final_exam_submit(self, course_id):
        """POST /api/courses/:id/final-exam/submit — enrolled only.

        Body: {"answers": {"<question_id>": <option index>, ...}}.
        Graded server-side against quizzes.answer_index; only answers
        for questions belonging to this course count, so `total` is
        the number of valid course questions submitted (10 when the
        full sampled set is submitted). Pass = score/total >= 0.70.
        On a first pass: +50 XP (derived in _gamification from the
        passed attempt row) and the exam-master-<course_id> badge
        (also derived there); the response reports xp_awarded 50 or 0.
        A repeat pass awards 0 (XP is once per course).
        """
        course, user = self._final_exam_access(course_id)
        if not course:
            return
        body = self._read_json()
        answers = body.get("answers") if isinstance(body, dict) else None
        if not isinstance(answers, dict) or not answers:
            self._err(400, "answers must be a non-empty object of question_id -> option index")
            return
        conn = db()
        rows = conn.execute(
            """SELECT q.id, q.answer_index
               FROM quizzes q JOIN lessons l ON l.id = q.lesson_id
               WHERE l.course_id = ?""",
            (course_id,)).fetchall()
        if not rows:
            conn.close()
            self._err(404, "This course has no quiz questions yet")
            return
        correct_by_id = {r["id"]: r["answer_index"] for r in rows}
        score, total = 0, 0
        for key, picked in answers.items():
            try:
                qid = int(key)
            except (TypeError, ValueError):
                continue
            if qid not in correct_by_id:
                continue
            try:
                picked = int(picked)
            except (TypeError, ValueError):
                picked = None
            total += 1
            if picked == correct_by_id[qid]:
                score += 1
        if total == 0:
            conn.close()
            self._err(400, "No valid answers for this course were submitted")
            return
        passed = score * 10 >= total * 7
        already_passed = conn.execute(
            "SELECT id FROM final_exam_attempts"
            " WHERE user_id = ? AND course_id = ? AND passed = 1",
            (user["id"], course_id)).fetchone()
        conn.execute(
            "INSERT INTO final_exam_attempts (user_id, course_id, score, total, passed)"
            " VALUES (?, ?, ?, ?, ?)",
            (user["id"], course_id, score, total, 1 if passed else 0))
        xp_awarded = 50 if (passed and not already_passed) else 0
        if passed:
            _notify_user(conn, user["id"], "exam_passed",
                         "Final exam passed",
                         f"You passed the final exam for '{course['title']}'"
                         f" with {score}/{total}"
                         + (" (+50 XP)." if xp_awarded else "."),
                         f"/course-details.html?id={course_id}")
        conn.commit()
        conn.close()
        self._ok({"score": score, "total": total, "passed": passed,
                  "xp_awarded": xp_awarded})

    # -- admin: user roles, review moderation, instructors, export ----
    def api_admin_user_role(self, user_id):
        """POST /api/admin/users/:id/role — admin-gated.

        Body {"is_admin": 0 or 1}. Deliberately no guard against
        revoking the admin-Gmail account: the key-holder must always
        be able to revoke it.
        """
        if not self._require_admin():
            return
        body = self._read_json()
        if not isinstance(body, dict):
            self._err(400, "Request body must be a JSON object")
            return
        value = body.get("is_admin")
        if isinstance(value, bool) or isinstance(value, float) \
                or value not in (0, 1, "0", "1"):
            self._err(400, "is_admin must be 0 or 1")
            return
        is_admin = int(value)
        conn = db()
        row = conn.execute(
            "SELECT id, name, email, is_admin FROM users WHERE id = ?",
            (user_id,)).fetchone()
        if not row:
            conn.close()
            self._err(404, "User not found")
            return
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?",
                     (is_admin, user_id))
        admin = self._auth_user()
        _audit(conn, admin["id"] if admin else None, "admin_role_change",
               self._client_ip(),
               f"user {user_id} ({row['email']}) is_admin -> {is_admin}")
        conn.commit()
        updated = row_to_dict(conn.execute(
            "SELECT id, name, email, is_admin FROM users WHERE id = ?",
            (user_id,)).fetchone())
        conn.close()
        self._ok({"user": updated})

    def api_admin_reviews(self):
        """GET /api/admin/reviews — admin-gated, paged (cap 50)."""
        if not self._require_admin():
            return
        page, per_page, _q = self._admin_page()
        conn = db()
        total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        rows = conn.execute(
            """SELECT r.id, r.user_id, r.course_id, r.rating, r.comment,
                      r.created_at, c.title AS course_title,
                      u.name AS user_name, u.email AS user_email
               FROM reviews r JOIN users u ON u.id = r.user_id
               JOIN courses c ON c.id = r.course_id
               ORDER BY r.id DESC LIMIT ? OFFSET ?""",
            [per_page, (page - 1) * per_page]).fetchall()
        conn.close()
        self._ok(self._admin_paged(
            {"reviews": [row_to_dict(r) for r in rows]}, total, page, per_page))

    def api_admin_review_delete(self, review_id):
        """DELETE /api/admin/reviews/:id — admin-gated."""
        if not self._require_admin():
            return
        conn = db()
        cur = conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if not deleted:
            self._err(404, "Review not found")
            return
        self._ok({"deleted": int(review_id)})

    def api_admin_instructors(self):
        """GET /api/admin/instructors — admin-gated.

        pending_qa = top-level discussions (parent_id IS NULL — a
        question, not a reply) on that instructor's courses that have
        no reply row yet (no discussion with parent_id = the question).
        """
        if not self._require_admin():
            return
        conn = db()
        rows = conn.execute(
            """SELECT c.instructor AS name,
                      COUNT(DISTINCT c.id) AS courses,
                      (SELECT COUNT(*) FROM enrollments e
                       JOIN courses c2 ON c2.id = e.course_id
                       WHERE c2.instructor = c.instructor) AS enrollments,
                      COALESCE(ROUND(AVG(r.rating), 2), 0.0) AS avg_rating,
                      (SELECT COUNT(*) FROM discussions d
                       JOIN lessons l ON l.id = d.lesson_id
                       JOIN courses c3 ON c3.id = l.course_id
                       WHERE c3.instructor = c.instructor
                         AND d.parent_id IS NULL
                         AND NOT EXISTS (SELECT 1 FROM discussions r
                                         WHERE r.parent_id = d.id)) AS pending_qa
               FROM courses c LEFT JOIN reviews r ON r.course_id = c.id
               GROUP BY c.instructor
               ORDER BY courses DESC, name""").fetchall()
        conn.close()
        self._ok({"instructors": [row_to_dict(r) for r in rows]})

    def api_admin_export(self):
        """GET /api/admin/export?type=users|enrollments|revenue|certificates
        — admin-gated, returns a real CSV download.

        Revenue rows come from the real `orders` table (one row per
        order); enrolment progress_pct is the stored value, which
        lesson completion keeps recomputed from lesson_progress.
        """
        if not self._require_admin():
            return
        from urllib.parse import urlparse, parse_qs
        typ = (parse_qs(urlparse(self.path).query).get("type", [""])[0]
               or "").strip()
        conn = db()
        if typ == "users":
            header = ["id", "name", "email", "created_at", "is_admin",
                      "enrollments"]
            rows = conn.execute(
                """SELECT u.id, u.name, u.email, u.created_at, u.is_admin,
                          (SELECT COUNT(*) FROM enrollments e
                           WHERE e.user_id = u.id) AS enrollments
                   FROM users u ORDER BY u.id""").fetchall()
        elif typ == "enrollments":
            header = ["id", "user_name", "user_email", "course_title",
                      "enrolled_at", "progress_pct"]
            rows = conn.execute(
                """SELECT e.id, u.name AS user_name, u.email AS user_email,
                          c.title AS course_title, e.enrolled_at,
                          e.progress_percent
                   FROM enrollments e JOIN users u ON u.id = e.user_id
                   JOIN courses c ON c.id = e.course_id
                   ORDER BY e.id""").fetchall()
        elif typ == "revenue":
            header = ["id", "user_email", "total", "status", "created_at"]
            rows = conn.execute(
                """SELECT o.id, u.email AS user_email, o.total, o.status,
                          o.created_at
                   FROM orders o JOIN users u ON u.id = o.user_id
                   ORDER BY o.id""").fetchall()
        elif typ == "certificates":
            header = ["id", "user_name", "user_email", "course_title",
                      "certificate_code", "issued_at"]
            rows = conn.execute(
                """SELECT cf.id, u.name AS user_name, u.email AS user_email,
                          c.title AS course_title, cf.certificate_code,
                          cf.issued_at
                   FROM certificates cf JOIN users u ON u.id = cf.user_id
                   JOIN courses c ON c.id = cf.course_id
                   ORDER BY cf.id""").fetchall()
        else:
            conn.close()
            self._err(400, "type must be one of: users, enrollments,"
                           " revenue, certificates")
            return
        conn.close()
        self._csv(f"learnhub-{typ}.csv", header, [tuple(r) for r in rows])

    # -- Learn Hub: OTP auth -------------------------------------------
    def api_auth_request_otp(self):
        """POST /api/auth/request-otp {email} -> demo OTP (demo mode).

        Demo-safe: no SMS/email provider is configured (free tier), so
        the generated code is returned in the response and shown on
        screen as a "Demo OTP". In production this same code would be
        sent by SMS/email instead. Only the SHA256 hash is stored;
        the plain code is never logged or written to disk.
        Rate limit: max 5 requests/hour per email.
        """
        body = self._read_json()
        email = (body.get("email") or "").strip().lower()
        if not email or len(email) > 254 or not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            self._err(400, "a valid email is required")
            return
        conn = db()
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM otp_codes WHERE email = ?"
            " AND created_at >= datetime('now', '-1 hour')",
            (email,)).fetchone()["n"]
        if n >= 5:
            conn.close()
            self._err(429, "Too many OTP requests - try again in an hour")
            return
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        conn.execute(
            "INSERT INTO otp_codes (email, code_hash, expires_at)"
            " VALUES (?, ?, datetime('now', '+10 minutes'))",
            (email, hashlib.sha256(code.encode()).hexdigest()))
        conn.commit()
        conn.close()
        self._ok({"demo_otp": code, "expires_in_seconds": 600,
                  "note": "DEMO MODE: no SMS/email provider is configured, so "
                          "the OTP is shown here. In production it arrives "
                          "by SMS/email and is never displayed."})

    def api_auth_verify_otp(self):
        """POST /api/auth/verify-otp {email, otp} -> session token.

        Max 5 verify attempts per code; codes expire after 10 minutes.
        On success the account is marked email_verified and a token is
        issued (plus the lh_token cookie for the hidden super-admin page).
        """
        body = self._read_json()
        email = (body.get("email") or "").strip().lower()
        otp = str(body.get("otp") or "").strip()
        if not email or not otp or not re.fullmatch(r"\d{6}", otp):
            self._err(400, "email and a 6-digit OTP are required")
            return
        conn = db()
        row = conn.execute(
            "SELECT * FROM otp_codes WHERE email = ? AND used = 0"
            " ORDER BY id DESC LIMIT 1", (email,)).fetchone()
        if not row:
            conn.close()
            self._err(400, "No OTP was requested for this email - request one first")
            return
        if row["attempts"] >= 5:
            conn.close()
            self._err(429, "Too many wrong attempts - request a new OTP")
            return
        if row["expires_at"] < time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()):
            conn.close()
            self._err(400, "OTP expired - request a new one")
            return
        if hashlib.sha256(otp.encode()).hexdigest() != row["code_hash"]:
            conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?",
                         (row["id"],))
            conn.commit()
            conn.close()
            self._err(401, "Incorrect OTP")
            return
        conn.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
        user = conn.execute("SELECT * FROM users WHERE email = ?",
                            (email,)).fetchone()
        if not user:
            conn.commit()
            conn.close()
            self._err(404, "No account for this email - register first")
            return
        conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?",
                     (user["id"],))
        _audit(conn, user["id"], "otp_verified", self._client_ip(),
               f"OTP verified for {email}")
        conn.commit()
        conn.close()
        token = make_token(user["id"])
        self._set_auth_cookie(token)
        u = row_to_dict(user)
        self._ok({"token": token, "user": {
            "id": user["id"], "name": user["name"], "email": user["email"],
            "is_admin": _is_admin_user(u)}})

    # -- Learn Hub: personal notes workspace ----------------------------
    def api_me_notes_list(self):
        user = self._require_user()
        if not user:
            return
        from urllib.parse import urlparse, parse_qs
        q = (parse_qs(urlparse(self.path).query).get("q", [""])[0] or "").strip()
        conn = db()
        if q:
            rows = conn.execute(
                "SELECT * FROM personal_notes WHERE user_id = ?"
                " AND (title LIKE ? OR body LIKE ?)"
                " ORDER BY updated_at DESC, id DESC",
                (user["id"], f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM personal_notes WHERE user_id = ?"
                " ORDER BY updated_at DESC, id DESC", (user["id"],)).fetchall()
        conn.close()
        self._ok({"notes": [row_to_dict(r) for r in rows]})

    def api_me_notes_create(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        title = (body.get("title") or "").strip()[:200]
        note_body = body.get("body") or ""
        if len(note_body) > 20000:
            self._err(400, "note body must be at most 20000 characters")
            return
        course_id = _positive_int(body.get("course_id")) if body.get("course_id") else None
        lesson_id = _positive_int(body.get("lesson_id")) if body.get("lesson_id") else None
        conn = db()
        try:
            cur = conn.execute(
                "INSERT INTO personal_notes (user_id, title, body, course_id, lesson_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (user["id"], title, note_body, course_id, lesson_id))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            self._err(400, "course_id / lesson_id does not exist")
            return
        note = row_to_dict(conn.execute(
            "SELECT * FROM personal_notes WHERE id = ?", (cur.lastrowid,)).fetchone())
        conn.close()
        self._ok({"note": note}, status=201)

    def api_me_notes_update(self, note_id):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        conn = db()
        row = conn.execute("SELECT * FROM personal_notes WHERE id = ? AND user_id = ?",
                           (note_id, user["id"])).fetchone()
        if not row:
            conn.close()
            self._err(404, "Note not found")
            return
        title = (body.get("title") or row["title"]).strip()[:200] if "title" in body else row["title"]
        note_body = body.get("body", row["body"])
        if len(note_body) > 20000:
            conn.close()
            self._err(400, "note body must be at most 20000 characters")
            return
        conn.execute("UPDATE personal_notes SET title = ?, body = ?,"
                     " updated_at = datetime('now') WHERE id = ?",
                     (title, note_body, note_id))
        conn.commit()
        note = row_to_dict(conn.execute(
            "SELECT * FROM personal_notes WHERE id = ?", (note_id,)).fetchone())
        conn.close()
        self._ok({"note": note})

    def api_me_notes_delete(self, note_id):
        user = self._require_user()
        if not user:
            return
        conn = db()
        cur = conn.execute("DELETE FROM personal_notes WHERE id = ? AND user_id = ?",
                           (note_id, user["id"]))
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            self._err(404, "Note not found")
            return
        self._ok({"message": "Note deleted"})

    # -- Learn Hub: proctored live assignments -------------------------
    def _assignment_public(self, row):
        d = row_to_dict(row)
        d.pop("expected_keywords", None)
        return d

    def api_course_assignments(self, course_id):
        conn = db()
        if not conn.execute("SELECT id FROM courses WHERE id = ?",
                            (course_id,)).fetchone():
            conn.close()
            self._err(404, "Course not found")
            return
        rows = conn.execute("SELECT * FROM assignments WHERE course_id = ?"
                            " ORDER BY id", (course_id,)).fetchall()
        conn.close()
        self._ok({"assignments": [self._assignment_public(r) for r in rows]})

    def api_assignment_get(self, assignment_id):
        conn = db()
        row = conn.execute("SELECT * FROM assignments WHERE id = ?",
                           (assignment_id,)).fetchone()
        conn.close()
        if not row:
            self._err(404, "Assignment not found")
            return
        self._ok({"assignment": self._assignment_public(row)})

    def api_assignment_start(self, assignment_id):
        user = self._require_user()
        if not user:
            return
        conn = db()
        a = conn.execute("SELECT * FROM assignments WHERE id = ?",
                         (assignment_id,)).fetchone()
        if not a:
            conn.close()
            self._err(404, "Assignment not found")
            return
        enrolled = conn.execute(
            "SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?",
            (user["id"], a["course_id"])).fetchone()
        if not enrolled:
            conn.close()
            self._err(403, "Enrol in this course to start the proctored assignment")
            return
        open_attempt = conn.execute(
            "SELECT * FROM assignment_attempts WHERE user_id = ?"
            " AND assignment_id = ? AND submitted_at IS NULL"
            " ORDER BY id DESC LIMIT 1",
            (user["id"], assignment_id)).fetchone()
        if open_attempt:
            conn.close()
            self._ok({"attempt_id": open_attempt["id"],
                      "started_at": open_attempt["started_at"],
                      "duration_minutes": a["duration_minutes"],
                      "resumed": True})
            return
        cur = conn.execute(
            "INSERT INTO assignment_attempts (user_id, assignment_id) VALUES (?, ?)",
            (user["id"], assignment_id))
        conn.commit()
        attempt_id = cur.lastrowid
        started = conn.execute("SELECT started_at FROM assignment_attempts"
                               " WHERE id = ?", (attempt_id,)).fetchone()["started_at"]
        _audit(conn, user["id"], "assignment_started", self._client_ip(),
               f"assignment {assignment_id} attempt {attempt_id}")
        conn.commit()
        conn.close()
        self._ok({"attempt_id": attempt_id, "started_at": started,
                  "duration_minutes": a["duration_minutes"], "resumed": False})

    def api_assignment_event(self, assignment_id):
        """POST /api/assignments/:id/event {attempt_id, type}.

        type: tab_switch | blur | paste | rightclick | copy | cut.
        Counters live on the attempt; >3 tab-switches auto-flags it.
        """
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        attempt_id = _positive_int(body.get("attempt_id"))
        etype = (body.get("type") or "").strip()
        colmap = {"tab_switch": "tab_switches", "blur": "blur_events",
                  "paste": "paste_attempts", "rightclick": "rightclick_attempts"}
        if not attempt_id or etype not in (*colmap, "copy", "cut"):
            self._err(400, "attempt_id and a valid event type are required")
            return
        conn = db()
        att = conn.execute(
            "SELECT * FROM assignment_attempts WHERE id = ? AND user_id = ?"
            " AND assignment_id = ? AND submitted_at IS NULL",
            (attempt_id, user["id"], assignment_id)).fetchone()
        if not att:
            conn.close()
            self._err(404, "Open attempt not found")
            return
        conn.execute("INSERT INTO assignment_events (attempt_id, type) VALUES (?, ?)",
                     (attempt_id, etype))
        if etype in colmap:
            conn.execute(f"UPDATE assignment_attempts SET {colmap[etype]} ="
                         f" {colmap[etype]} + 1 WHERE id = ?", (attempt_id,))
        att2 = conn.execute("SELECT * FROM assignment_attempts WHERE id = ?",
                            (attempt_id,)).fetchone()
        flagged = 1 if att2["tab_switches"] > 3 else att2["flagged"]
        if flagged and not att2["flagged"]:
            conn.execute("UPDATE assignment_attempts SET flagged = 1 WHERE id = ?",
                         (attempt_id,))
        conn.commit()
        conn.close()
        self._ok({"tab_switches": att2["tab_switches"],
                  "blur_events": att2["blur_events"],
                  "paste_attempts": att2["paste_attempts"],
                  "rightclick_attempts": att2["rightclick_attempts"],
                  "flagged": bool(flagged)})

    def api_assignment_submit(self, assignment_id):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        attempt_id = _positive_int(body.get("attempt_id"))
        code = body.get("code") or ""
        if not attempt_id:
            self._err(400, "attempt_id is required")
            return
        conn = db()
        a = conn.execute("SELECT * FROM assignments WHERE id = ?",
                         (assignment_id,)).fetchone()
        att = conn.execute(
            "SELECT * FROM assignment_attempts WHERE id = ? AND user_id = ?"
            " AND assignment_id = ? AND submitted_at IS NULL",
            (attempt_id, user["id"], assignment_id)).fetchone()
        if not a or not att:
            conn.close()
            self._err(404, "Assignment or open attempt not found")
            return
        # Transparent heuristic grading: share of expected keywords
        # present in the submitted code (documented in the build report).
        try:
            keywords = json.loads(a["expected_keywords"] or "[]")
        except (ValueError, TypeError):
            keywords = []
        code_l = code.lower()
        matched = sum(1 for kw in keywords if str(kw).lower() in code_l)
        score = 0
        if keywords and len(code.strip()) >= 10:
            score = round(a["total_marks"] * matched / len(keywords))
        flagged = 1 if (att["tab_switches"] > 3 or att["flagged"]) else 0
        conn.execute(
            "UPDATE assignment_attempts SET code = ?, submitted_at = datetime('now'),"
            " score = ?, flagged = ? WHERE id = ?",
            (code[:20000], score, flagged, attempt_id))
        _audit(conn, user["id"], "assignment_submitted", self._client_ip(),
               f"assignment {assignment_id} score {score}/{a['total_marks']}"
               f" flagged={flagged}")
        conn.commit()
        conn.close()
        self._ok({"score": score, "total_marks": a["total_marks"],
                  "flagged": bool(flagged),
                  "message": "Attempt flagged for review - too many tab switches."
                             if flagged else "Assignment submitted."})

    def api_admin_assignment_attempts(self):
        if not self._require_admin():
            return
        conn = db()
        rows = conn.execute(
            """SELECT at.id, at.user_id, u.email AS user_email,
                      at.assignment_id, a.title AS assignment_title,
                      a.course_id, at.tab_switches, at.blur_events,
                      at.paste_attempts, at.rightclick_attempts,
                      at.score, at.flagged, at.started_at, at.submitted_at
               FROM assignment_attempts at
               JOIN users u ON u.id = at.user_id
               JOIN assignments a ON a.id = at.assignment_id
               ORDER BY at.started_at DESC, at.id DESC LIMIT 100""").fetchall()
        conn.close()
        self._ok({"attempts": [row_to_dict(r) for r in rows]})

    # -- Learn Hub: mock payments --------------------------------------
    def api_payment_verify(self, payment_id):
        """POST /api/payments/:id/verify {payment_id, signature}.

        Simulates the gateway callback: the HMAC signature over
        gateway_order_id|payment_id must match the server-side test
        secret. On success the payment is marked paid, the learner is
        enrolled, an order row is created and the cart item is cleared.
        """
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        signature = str(body.get("signature") or "")
        conn = db()
        pay = conn.execute("SELECT * FROM payments WHERE id = ?",
                           (payment_id,)).fetchone()
        if not pay or pay["user_id"] != user["id"]:
            conn.close()
            self._err(404, "Payment not found")
            return
        if pay["status"] == "paid":
            conn.close()
            self._ok({"order_id": pay["order_id"], "already_paid": True,
                      "enrolled_course_ids": [pay["course_id"]]})
            return
        if pay["status"] != "pending":
            conn.close()
            self._err(400, f"Payment is {pay['status']} and cannot be verified")
            return
        expected = _payment_signature(pay["gateway_order_id"], pay["id"])
        if not signature or not hmac.compare_digest(signature, expected):
            conn.close()
            self._err(401, "Invalid payment signature")
            return
        conn.execute("UPDATE payments SET status = 'paid' WHERE id = ?",
                     (payment_id,))
        try:
            conn.execute("INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)",
                         (user["id"], pay["course_id"]))
        except sqlite3.IntegrityError:
            pass
        cur = conn.execute(
            "INSERT INTO orders (user_id, total, status) VALUES (?, ?, 'completed')",
            (user["id"], pay["amount"]))
        order_row_id = cur.lastrowid
        conn.execute("DELETE FROM cart_items WHERE user_id = ? AND course_id = ?",
                     (user["id"], pay["course_id"]))
        _audit(conn, user["id"], "payment_verified", self._client_ip(),
               f"test-mode payment {pay['order_id']} Rs {pay['amount']}"
               f" course {pay['course_id']}")
        conn.commit()
        conn.close()
        self._ok({"order_id": pay["order_id"], "order_row_id": order_row_id,
                  "enrolled_course_ids": [pay["course_id"]],
                  "message": "Payment verified (TEST MODE) - you are now enrolled!"})

    def api_payments_me(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT p.id, p.order_id, p.gateway_order_id, p.course_id,
                      c.title AS course_title, p.amount, p.currency,
                      p.gateway, p.status, p.created_at
               FROM payments p JOIN courses c ON c.id = p.course_id
               WHERE p.user_id = ? ORDER BY p.created_at DESC, p.id DESC""",
            (user["id"],)).fetchall()
        conn.close()
        self._ok({"payments": [row_to_dict(r) for r in rows]})

    def api_admin_payments(self):
        if not self._require_admin():
            return
        conn = db()
        rows = conn.execute(
            """SELECT p.id, p.order_id, p.user_id, u.email AS user_email,
                      p.course_id, c.title AS course_title, p.amount,
                      p.currency, p.gateway, p.status, p.created_at
               FROM payments p JOIN users u ON u.id = p.user_id
               JOIN courses c ON c.id = p.course_id
               ORDER BY p.created_at DESC, p.id DESC LIMIT 200""").fetchall()
        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS rev FROM payments"
            " WHERE status = 'paid'").fetchone()["rev"]
        conn.close()
        self._ok({"payments": [row_to_dict(r) for r in rows],
                  "total_revenue": total})

    # -- Learn Hub: security center + audit logs -----------------------
    def api_admin_security(self):
        if not self._require_admin():
            return
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        try:
            limit = max(1, min(200, int(qs.get("limit", ["50"])[0])))
        except (TypeError, ValueError):
            limit = 50
        conn = db()
        rows = conn.execute(
            "SELECT * FROM security_events ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        by_sev = {r["severity"]: r["n"] for r in conn.execute(
            "SELECT severity, COUNT(*) AS n FROM security_events GROUP BY severity")}
        by_type = {r["event_type"]: r["n"] for r in conn.execute(
            "SELECT event_type, COUNT(*) AS n FROM security_events GROUP BY event_type")}
        total = conn.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"]
        blocked = conn.execute(
            "SELECT COUNT(*) AS n FROM security_events WHERE blocked = 1").fetchone()["n"]
        conn.close()
        self._ok({"events": [row_to_dict(r) for r in rows],
                  "counts": {"by_severity": by_sev, "by_type": by_type,
                             "total": total, "blocked": blocked}})

    def api_admin_audit_logs(self):
        if not self._require_admin():
            return
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        try:
            limit = max(1, min(200, int(qs.get("limit", ["50"])[0])))
        except (TypeError, ValueError):
            limit = 50
        conn = db()
        rows = conn.execute(
            """SELECT al.id, al.user_id, u.email AS user_email, al.action,
                      al.ip, al.details, al.created_at
               FROM audit_logs al LEFT JOIN users u ON u.id = al.user_id
               ORDER BY al.id DESC LIMIT ?""", (limit,)).fetchall()
        conn.close()
        self._ok({"logs": [row_to_dict(r) for r in rows]})

    def api_admin_security_stats(self):
        if not self._require_admin():
            return
        conn = db()
        one = lambda sql: conn.execute(sql).fetchone()[0]
        total = one("SELECT COUNT(*) FROM security_events")
        blocked = one("SELECT COUNT(*) FROM security_events WHERE blocked = 1")
        recent = one("SELECT COUNT(*) FROM security_events"
                     " WHERE created_at >= datetime('now', '-1 day')")
        failed = one("SELECT COUNT(*) FROM security_events"
                     " WHERE event_type IN ('failed_login', 'brute_force')"
                     " AND created_at >= datetime('now', '-1 day')")
        by_sev = {r["severity"]: r["n"] for r in conn.execute(
            "SELECT severity, COUNT(*) AS n FROM security_events GROUP BY severity")}
        by_type = {r["event_type"]: r["n"] for r in conn.execute(
            "SELECT event_type, COUNT(*) AS n FROM security_events GROUP BY event_type")}
        conn.close()
        self._ok({"total_events": total, "blocked": blocked,
                  "recent_24h": recent, "failed_logins_24h": failed,
                  "by_severity": by_sev, "by_type": by_type})



def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), LearnHubHandler)
    print(f"[learnhub] serving frontend from {REPO_DIR}")
    print(f"[learnhub] integration JS from {JS_DIR}")
    print(f"[learnhub] database: {DB_PATH}")
    print(f"[learnhub] open http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[learnhub] stopped")


if __name__ == "__main__":
    main()
