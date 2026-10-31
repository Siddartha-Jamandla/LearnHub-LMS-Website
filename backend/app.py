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

import hashlib
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

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
    conn.close()
    if fresh:
        print(f"[learnhub] created database at {DB_PATH}")


def row_to_dict(row):
    return dict(row) if row else None


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
        """SELECT u.id, u.name, u.email, u.created_at
           FROM auth_tokens t JOIN users u ON u.id = t.user_id
           WHERE t.token = ?""",
        (token,),
    ).fetchone()
    conn.close()
    return row_to_dict(row)


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
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, payload, status=200):
        self._json(status, {"ok": True, **payload})

    def _err(self, status: int, message: str):
        self._json(status, {"ok": False, "error": message})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode() or "{}")
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
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

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
            ("GET",    r"^/api/courses$",                self.api_courses),
            ("GET",    r"^/api/courses/(\d+)$",          self.api_course),
            ("GET",    r"^/api/courses/(\d+)/lessons$",  self.api_course_lessons),
            ("POST",   r"^/api/register$",               self.api_register),
            ("POST",   r"^/api/login$",                  self.api_login),
            ("POST",   r"^/api/logout$",                 self.api_logout),
            ("GET",    r"^/api/cart$",                   self.api_cart_get),
            ("POST",   r"^/api/cart$",                   self.api_cart_add),
            ("DELETE", r"^/api/cart/(\d+)$",             self.api_cart_del),
            ("POST",   r"^/api/checkout$",               self.api_checkout),
            ("GET",    r"^/api/enrollments$",            self.api_enrollments),
            ("PUT",    r"^/api/enrollments/(\d+)/progress$", self.api_progress),
            ("GET",    r"^/api/my-courses$",             self.api_my_courses),
        ]
        for m, pattern, handler in r:
            match = re.match(pattern, path)
            if m == method and match:
                handler(*match.groups())
                return
        self._err(404, "Unknown endpoint")

    # -- public endpoints ----------------------------------------------
    def api_health(self):
        self._ok({"service": "learnhub", "status": "ok", "time": int(time.time())})

    def api_courses(self):
        conn = db()
        rows = conn.execute("SELECT * FROM courses ORDER BY id").fetchall()
        conn.close()
        self._ok({"courses": [row_to_dict(r) for r in rows]})

    def api_course(self, course_id):
        conn = db()
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        conn.close()
        if not course:
            self._err(404, "Course not found")
            return
        self._ok({"course": row_to_dict(course)})

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

    def api_register(self):
        body = self._read_json()
        name, email, password = (body.get("name") or "").strip(), (body.get("email") or "").strip().lower(), body.get("password") or ""
        if not name or not email or not password:
            self._err(400, "name, email and password are required")
            return
        if len(password) < 6:
            self._err(400, "password must be at least 6 characters")
            return
        conn = db()
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            conn.close()
            self._err(409, "An account with this email already exists")
            return
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, hash_password(password)),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        token = make_token(user_id)
        self._ok({"token": token, "user": {"id": user_id, "name": name, "email": email}}, status=201)

    def api_login(self):
        body = self._read_json()
        email, password = (body.get("email") or "").strip().lower(), body.get("password") or ""
        if not email or not password:
            self._err(400, "email and password are required")
            return
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if not user or not verify_password(password, user["password_hash"]):
            self._err(401, "Invalid email or password")
            return
        token = make_token(user["id"])
        self._ok({"token": token, "user": row_to_dict(user) and {
            "id": user["id"], "name": user["name"], "email": user["email"]}})

    def api_logout(self):
        auth = self.headers.get("Authorization", "")
        m = re.match(r"Bearer\s+(\S+)", auth)
        if m:
            conn = db()
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (m.group(1),))
            conn.commit()
            conn.close()
        self._ok({"message": "Logged out"})

    # -- authenticated endpoints ---------------------------------------
    def _require_user(self):
        user = self._auth_user()
        if not user:
            self._err(401, "Missing or invalid Authorization: Bearer <token>")
            return None
        return user

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
        course_id = body.get("course_id")
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
        user = self._require_user()
        if not user:
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
        # Enroll in every course (idempotent: skip ones already enrolled)
        enrolled = []
        for i in items:
            try:
                conn.execute(
                    "INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)",
                    (user["id"], i["course_id"]),
                )
                enrolled.append(i["course_id"])
            except sqlite3.IntegrityError:
                pass  # already enrolled
        cur = conn.execute(
            "INSERT INTO orders (user_id, total, status) VALUES (?, ?, 'completed')",
            (user["id"], total),
        )
        order_id = cur.lastrowid
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user["id"],))
        conn.commit()
        conn.close()
        self._ok({"order_id": order_id, "total": total,
                  "enrolled_course_ids": enrolled,
                  "message": "Checkout complete - you are now enrolled!"})

    def api_enrollments(self):
        user = self._require_user()
        if not user:
            return
        conn = db()
        rows = conn.execute(
            """SELECT e.id, e.progress_percent, e.enrolled_at, c.*
               FROM enrollments e JOIN courses c ON c.id = e.course_id
               WHERE e.user_id = ? ORDER BY e.enrolled_at DESC""",
            (user["id"],),
        ).fetchall()
        conn.close()
        out = []
        for r in rows:
            d = row_to_dict(r)
            enrollment = {"id": d.pop("id"),
                          "progress_percent": d.pop("progress_percent"),
                          "enrolled_at": d.pop("enrolled_at")}
            enrollment["course"] = d
            out.append(enrollment)
        self._ok({"enrollments": out})

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
