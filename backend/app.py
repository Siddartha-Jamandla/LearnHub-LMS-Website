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

    if fresh:
        print(f"[learnhub] created database at {DB_PATH}")
    try:
        error_bot.init_error_bot(DB_PATH)
    except Exception:
        pass



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
        try:
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
            ("GET",    r"^/api/courses/(\d+)/reviews$",  self.api_course_reviews),
            ("POST",   r"^/api/reviews$",                self.api_review_add),
            ("GET",    r"^/api/certificates/(\d+)$",     self.api_cert_get),
            ("POST",   r"^/api/lessons/(\d+)/complete$", self.api_lesson_complete),
            ("POST",   r"^/api/admin/courses$",          self.api_admin_course_create),
            ("PUT",    r"^/api/admin/courses/(\d+)$",    self.api_admin_course_update),
            ("DELETE", r"^/api/admin/courses/(\d+)$",    self.api_admin_course_delete),
            ("POST",   r"^/api/admin/courses/(\d+)/lessons$",
                                                     self.api_admin_lesson_create),
            ("PUT",    r"^/api/admin/lessons/(\d+)$",    self.api_admin_lesson_update),
            ("DELETE", r"^/api/admin/lessons/(\d+)$",    self.api_admin_lesson_delete),
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
            ("GET",    r"^/api/wishlist$",               self.api_wishlist_get),
            ("POST",   r"^/api/wishlist$",               self.api_wishlist_add),
            ("DELETE", r"^/api/wishlist/(\d+)$",         self.api_wishlist_del),
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
            sql + where + " ORDER BY id LIMIT ? OFFSET ?",
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

    def api_course_reviews(self, course_id):
        conn = db()
        course = conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            conn.close()
            self._err(404, "Course not found")
            return
        rows = conn.execute(
            """SELECT r.id, r.rating, r.comment, r.created_at, u.name AS user_name
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
        course_id = body.get("course_id")
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
        if pct >= 100.0:
            code = "LH-" + secrets.token_hex(4).upper()
            cur = conn.execute(
                "INSERT OR IGNORE INTO certificates (user_id, course_id, certificate_code)"
                " VALUES (?, ?, ?)",
                (user["id"], lesson["course_id"], code))
            if cur.rowcount == 1:
                certificate = {"id": cur.lastrowid,
                               "certificate_code": code}
            else:
                existing = conn.execute(
                    "SELECT id, certificate_code FROM certificates"
                    " WHERE user_id = ? AND course_id = ?",
                    (user["id"], lesson["course_id"])).fetchone()
                if existing:
                    certificate = {"id": existing["id"],
                                   "certificate_code": existing["certificate_code"]}
        conn.commit()
        conn.close()
        resp = {"lesson_id": int(lesson_id), "completed": True,
                "progress_percent": pct,
                "message": f"Lesson '{lesson['title']}' marked complete"}
        if certificate:
            resp["certificate"] = certificate
        self._ok(resp)

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

    # -- admin (instructor) helpers ------------------------------------
    # All admin endpoints are gated on the shared secret: ?key=API_SECRET
    # (or the X-Admin-Key header). The admin UI lives at /admin.html.
    COURSE_LEVELS = ("Beginner", "Intermediate", "Advanced")

    def _require_admin(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        key = qs.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if key != API_SECRET:
            self._err(403, "Forbidden: invalid or missing admin key")
            return False
        return True

    def _validate_course(self, body):
        """Return (clean_dict, error). Validates fields present in body."""
        clean, err = {}, None
        if "title" in body:
            title = (body.get("title") or "").strip()
            if not title:
                return None, "title is required and cannot be empty"
            clean["title"] = title
        if "price" in body:
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
        for f in ("description", "category", "instructor", "image_url"):
            if f in body:
                clean[f] = (body.get(f) or "").strip()
        if "duration_hours" in body:
            try:
                dur = float(body.get("duration_hours"))
            except (TypeError, ValueError):
                return None, "duration_hours must be a number >= 0"
            if dur < 0:
                return None, "duration_hours must be >= 0"
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
        content_url = (body.get("content_url") or body.get("body")
                       or body.get("content") or "").strip()
        if not content_url:
            self._err(400, "content_url (or body) is required")
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
            clean["title"] = title
        for f in ("content_url", "body", "content"):
            if f in body:
                clean["content_url"] = (body.get(f) or "").strip()
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
        course_id = body.get("course_id")
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
