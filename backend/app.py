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
    conn.close()
    if fresh:
        print(f"[learnhub] created database at {DB_PATH}")
    try:
        error_bot.init_error_bot(DB_PATH)
    except Exception:
        pass


def _migrate_schema(conn):
    """Additive migrations for DBs created before a schema change.

    CREATE TABLE IF NOT EXISTS covers fresh DBs; ALTER TABLE covers
    existing ones. The preview backfill is idempotent - safe every start.
    """
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
            "popular_courses": [row_to_dict(r) for r in popular],
        })

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
