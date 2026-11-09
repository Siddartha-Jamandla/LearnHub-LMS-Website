-- LearnHub LMS - SQLite schema
-- Run with: sqlite3 learnhub.db < schema.sql

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,   -- 1 = site admin (Gmail-admin)
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS courses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL,
    price          INTEGER NOT NULL,          -- price in INR
    instructor     TEXT NOT NULL,
    duration_hours REAL NOT NULL,
    level          TEXT NOT NULL,             -- Beginner / Intermediate / Advanced
    image_url      TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lessons (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id        INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    content_url      TEXT,
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    order_index      INTEGER NOT NULL DEFAULT 0,
    is_preview       INTEGER NOT NULL DEFAULT 0   -- 1 = free preview, viewable without enrolment
);

CREATE TABLE IF NOT EXISTS enrollments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id        INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    enrolled_at      TEXT NOT NULL DEFAULT (datetime('now')),
    progress_percent REAL NOT NULL DEFAULT 0,
    UNIQUE (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS cart_items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total      INTEGER NOT NULL,          -- total in INR
    status     TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Which lessons a learner has marked complete. Drives the auto-computed
-- enrollments.progress_percent (done_lessons / total_lessons * 100).
CREATE TABLE IF NOT EXISTS lesson_progress (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id    INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    completed_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, lesson_id)
);

-- Auth tokens so login sessions survive a server restart.
CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Course wishlist: courses a learner wants to take later.
-- One entry per user per course (idempotent adds).
CREATE TABLE IF NOT EXISTS wishlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    added_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_wishlist_user ON wishlist(user_id);

CREATE INDEX IF NOT EXISTS idx_lessons_course   ON lessons(course_id);
CREATE INDEX IF NOT EXISTS idx_enroll_user      ON enrollments(user_id);
CREATE INDEX IF NOT EXISTS idx_cart_user        ON cart_items(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user      ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_courses_category ON courses(category);
CREATE INDEX IF NOT EXISTS idx_lesson_progress_user ON lesson_progress(user_id);

-- Course reviews: one review per user per course, rating 1-5.
CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_course ON reviews(course_id);

-- Certificates of completion: generated once when an enrolled learner's
-- progress hits 100%. One certificate per user per course.
CREATE TABLE IF NOT EXISTS certificates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id        INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    certificate_code TEXT    NOT NULL UNIQUE,       -- e.g. LH-3F9A2C1B
    issued_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_certificates_user ON certificates(user_id);

-- ------------------------------------------------------------------
-- Learning content: real lessons, quizzes, tasks and the tutor KB.
-- Seeded from backend/content/*.json by backend/seed_content.py.
-- ------------------------------------------------------------------

-- Rich lesson content: teachable explanation (HTML fragment), an
-- optional logic flowchart (nodes/edges JSON, rendered client-side
-- as inline SVG) and one free YouTube tutorial video (verified ID).
CREATE TABLE IF NOT EXISTS lesson_content (
    lesson_id       INTEGER PRIMARY KEY REFERENCES lessons(id) ON DELETE CASCADE,
    body            TEXT NOT NULL DEFAULT '',
    flowchart_title TEXT,
    flowchart_json  TEXT,              -- {"nodes": [...], "edges": [...]} or NULL
    video_id        TEXT,              -- verified YouTube video ID or NULL
    video_title     TEXT
);

-- Per-lesson MCQ quiz questions. options_json is a JSON array of
-- exactly 4 strings; answer_index is 0-3; explanation says WHY.
CREATE TABLE IF NOT EXISTS quizzes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id    INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    question     TEXT NOT NULL,
    options_json TEXT NOT NULL,
    answer_index INTEGER NOT NULL CHECK (answer_index BETWEEN 0 AND 3),
    explanation  TEXT NOT NULL DEFAULT '',
    order_index  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_quizzes_lesson ON quizzes(lesson_id);

-- One row per quiz submission. answers_json maps question id -> the
-- option index the learner picked, so results can be reviewed.
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id    INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    score        INTEGER NOT NULL,
    total        INTEGER NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '{}',
    taken_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_lesson
    ON quiz_attempts(user_id, lesson_id);

-- Practice tasks: predict the output, fix the bug, fill in the blank,
-- trace the code, or a mini-project (one per course, last lesson).
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id   INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,         -- predict | fix | fill | trace | project
    title       TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    code        TEXT NOT NULL DEFAULT '',
    expected    TEXT NOT NULL DEFAULT '',
    answer      TEXT NOT NULL DEFAULT '',
    hint        TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tasks_lesson ON tasks(lesson_id);

CREATE TABLE IF NOT EXISTS task_completions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    completed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_task_completions_user
    ON task_completions(user_id);

-- ------------------------------------------------------------------
-- Professional LMS: announcements, lesson notes, bookmarks, Q&A.
-- ------------------------------------------------------------------
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

-- ------------------------------------------------------------------
-- ULTIMATE LMS: final exam attempts + notifications.
-- ------------------------------------------------------------------

-- One row per final-exam submission. Multiple attempts allowed;
-- `passed` is 1 when score/total >= 0.70. XP (+50) and the
-- exam-master badge are derived from passed rows (see _gamification),
-- not stored separately.
CREATE TABLE IF NOT EXISTS final_exam_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    score      INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    passed     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_final_exam_user_course
    ON final_exam_attempts(user_id, course_id);

-- In-app notifications (announcements, discussion replies,
-- certificates, exam passes). is_read 0 = unread.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    link       TEXT,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
