-- LearnHub LMS - SQLite schema
-- Run with: sqlite3 learnhub.db < schema.sql

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
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
    order_index      INTEGER NOT NULL DEFAULT 0
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
