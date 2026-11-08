# LearnHub LMS - Full-Stack Edition

LearnHub is an online learning platform offering expert-led courses in web
development, programming, design, marketing, AI, and business - now rebuilt
as a **complete full-stack project**:

- **Frontend** - HTML, CSS, JavaScript (the original site, now API-powered)
- **Backend** - Python **standard library only** (`http.server`, `sqlite3`, `json`, `hashlib`)
- **Database** - SQLite with a clean relational schema

No Flask, no Django, no npm packages. Clone, run one command, and learn.
🌐 **Live Demo:** https://learnhubapp.pythonanywhere.com/

## Architecture

```
LearnHub-LMS-Website/
├── index.html, courses.html, cart.html, ...   # frontend (original site)
├── js/
│   ├── api.js      # API client: backend when online, localStorage fallback offline
│   └── auth.js     # login/register form wiring + auth guards
├── backend/
│   ├── app.py          # REST API + static file server (python3 backend/app.py)
│   ├── schema.sql      # database schema
│   ├── seed.py         # seeds 12 courses + lessons (python3 backend/seed.py)
│   ├── requirements.txt# stdlib only - nothing to install
│   └── .env.example    # optional config
├── INTEGRATION.md      # exact <script> tags to add per page
├── TEST_RESULTS.md     # local API test log
├── run.sh / run.bat    # one-command local dev start
└── .gitignore
```

The backend serves the frontend itself: open `http://localhost:8000` and every
page is delivered by `app.py`, with `/js/api.js` and `/js/auth.js` served from
the new `js/` directory.

## Quick start

```bash
# 1. Clone
git clone https://github.com/Siddartha-Jamandla/LearnHub-LMS-Website.git
cd LearnHub-LMS-Website

# 2. Run (seeds the DB on first run, then starts the server)
./run.sh            # Linux / macOS
run.bat             # Windows

# 3. Open http://localhost:8000
```

Manual alternative:

```bash
python3 backend/seed.py     # create + seed SQLite DB
python3 backend/app.py      # start API + static server on :8000
```

Config via environment (see `backend/.env.example`): `PORT`, `DB_PATH`, `API_SECRET`.

## REST API

Base URL: `http://localhost:8000/api`. All responses are JSON shaped as
`{"ok": true, ...}` or `{"ok": false, "error": "..."}`. CORS is enabled.

Authenticated endpoints need `Authorization: Bearer <token>` (token comes
from `/api/register` or `/api/login`).

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/health` | - | Service status |
| GET | `/api/courses` | - | List courses. `?q=`/`?search=` (title/description), `?category=`, `?level=`; sort with `?sort=` (`rating` = avg review rating, `price_asc`, `price_desc`, `newest`; unknown value → 400); paginated via `?page=` & `?per_page=` (max 50). Returns `courses` + `total/page/per_page/pages`. Frontend: `LearnHubAPI.getCourses({sort: "rating"})` passes `sort` straight through |
| GET | `/api/courses/:id` | - | One course (includes `avg_rating` + `review_count`) |
| GET | `/api/courses/:id/lessons` | - | Lessons for a course (each includes `is_preview`: 1 = free preview) |
| GET | `/api/courses/:id/progress` | token | Progress summary for an enrolled course: `{course_id, total_lessons, completed_lessons, progress_percent, next_lesson_id, next_lesson_title, certificate_code}` — 404 unknown course, 403 not enrolled; `certificate_code` is null until 100% with a certificate on file |
| GET | `/api/lessons/:id` | - for previews | Lesson detail/content. Free-preview lessons are public; other lessons need a token **and** enrolment in the course (401/403 otherwise). Includes `content` (teachable explanation HTML, `flowchart` nodes/edges, `video_id`/`video_title`), `quiz_count` and `task_count` |
| GET | `/api/lessons/:id/quiz` | - for previews | Quiz questions for a lesson — options only, **no answers** (same access rule as the lesson) |
| POST | `/api/lessons/:id/quiz` | token | Submit quiz answers `{"answers": {"<question_id>": <option 0-3>}}` → `{score, total, percent, results[]}`. Each result carries the correct option + the explanation of WHY. Attempts are recorded (enrolled, or signed-in for preview lessons) |
| GET | `/api/lessons/:id/tasks` | - for previews | Practice tasks for a lesson — prompt + code + hint, **no solutions**; each carries a `completed` flag for the signed-in learner |
| POST | `/api/tasks/:id/complete` | token | Check a task answer `{"answer": "..."}`. `predict`/`fill`/`trace` are auto-checked against the expected value; `fix`/`project` are self-checked (any non-empty submission completes and returns the model answer for comparison). Returns `{correct, completed, expected, answer, hint}` |
| GET | `/api/courses/:id/learn-progress` | token | Per-lesson quiz best score + tasks done/total for an enrolled course |
| POST | `/api/tutor` | - | Rule-based tutor chatbot: `{"message", "course_id"?, "lesson_id"?, "context"?}` → `{"reply", "context"}`. Answers come only from the seeded course content — explains topics in simple steps, walks through a lesson's flowchart step by step, quizzes with MCQs (answer with A/B/C/D), gives task hints. Says "I don't know" instead of inventing anything outside the course material |
| GET | `/api/courses/:id/reviews` | - | Reviews for a course (newest first, with reviewer name) |
| POST | `/api/reviews` | token | `{course_id, rating (1-5), comment?}` → 201. Must be enrolled; one review per user per course |
| POST | `/api/register` | - | `{name, email, password}` → token |
| POST | `/api/login` | - | `{email, password}` → token |
| POST | `/api/logout` | token | Invalidate token |
| GET | `/api/cart` | token | Cart items with course details |
| POST | `/api/cart` | token | `{course_id}` → add to cart |
| DELETE | `/api/cart/:id` | token | Remove cart item |
| POST | `/api/checkout` | token | Enrol in all cart courses, create order, clear cart |
| GET | `/api/enrollments` | token | Enrolments with progress |
| DELETE | `/api/enrollments/:courseId` | token | Unenrol from a course (404 if not enrolled). Deletes your lesson progress for the course — a later re-enrolment starts fresh — but keeps any already-earned certificate (certificates are permanent) |
| PUT | `/api/enrollments/:id/progress` | token | `{progress_percent: 0-100}` |
| POST | `/api/lessons/:id/complete` | token | Mark a lesson complete; course progress auto-recomputes (idempotent). Includes `certificate {id, certificate_code}` when this completes the course |
| GET | `/api/certificates` | token | Your certificates of completion (id, certificate_code, course title, issued date), newest first |
| GET | `/api/certificates/verify/:code` | - | **Public** certificate check: `{valid: true, certificate_code, course_title, instructor, student_name, issued_at}` or 404 `{valid: false}` when the code does not exist. Only those fields are ever returned |
| GET | `/api/certificates/:id` | token | View your own certificate of completion (user name, course, code, issue date) |
| GET | `/api/my-courses` | token | Enrolled courses for the My Courses page |
| GET | `/api/wishlist` | token | Wishlist items (newest first), each embedding course `id/title/price/level/avg_rating` |
| POST | `/api/wishlist` | token | `{course_id}` → 201 on new add, 200 + `added:false` on re-add (idempotent); 404 if course missing |
| DELETE | `/api/wishlist/:courseId` | token | Remove from wishlist (user-scoped); 404 if not present |

### Admin API (instructor)

Admin endpoints are gated on the shared secret: pass it as `?key=<API_SECRET>`
(the same value as the backend's `API_SECRET` env var) or as the
`X-Admin-Key` header. The admin UI at [`admin.html`](admin.html) (also linked
in the footer) talks to these endpoints and keeps the key in
`sessionStorage`. It also has a **Platform stats** dashboard at the top of
the page: a "Load stats" button calls `GET /api/admin/stats` and renders
total users, courses and enrollments, revenue (orders + enrollment value),
and a table of the 5 most popular courses. It loads automatically when a key
is already saved for the tab, and shows a clear error when the key is missing
or invalid.

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/admin/courses` | `{title*, description?, category?, price? (≥ 0), instructor?, duration_hours?, level? (Beginner/Intermediate/Advanced), image_url?}` → 201 |
| PUT | `/api/admin/courses/:id` | Update course fields → 404 if missing |
| DELETE | `/api/admin/courses/:id` | 404 if missing; 409 if enrolments exist (history preserved); lessons cascade |
| POST | `/api/admin/courses/:id/lessons` | `{title*, content_url* (or body), duration_minutes?, order_index?}` → 201 |
| PUT | `/api/admin/lessons/:id` | Update lesson fields → 404 if missing |
| DELETE | `/api/admin/lessons/:id` | 404 if missing; learner progress rows cascade |
| GET | `/api/admin/stats` | User/course/enrolment counts, revenue (completed order totals + course price × enrolments), and the 5 most popular courses by enrolment count |

Example:

```bash
curl -X POST 'localhost:8000/api/admin/courses?key=learnhub-dev-secret' \
  -H 'Content-Type: application/json' \
  -d '{"title":"Intro to SQL","category":"Data Science","price":499,"level":"Beginner"}'
# {"ok": true, "course": {"id": 11, ...}}
```

Example:

```bash
curl -X POST localhost:8000/api/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"Siddartha","email":"sid@example.com","password":"secret123"}'
# {"ok": true, "token": "...", "user": {...}}

curl localhost:8000/api/courses | python3 -m json.tool | head -20
```

### Input validation

Every write endpoint validates its input and answers `400` with a plain
message when it is bad — the request never reaches the database:

- `course_id` bodies (cart, wishlist, reviews) must be positive integers —
  `"abc"`/`-1`/missing → `400`, unknown id → `404`.
- Register: email must look like an email (`400` otherwise); name ≤ 100
  chars; password 6–128 chars.
- Reviews: rating must be an int 1–5; comment ≤ 2000 chars.
- Course list: `?sort=` must be one of `rating`, `price_asc`, `price_desc`,
  `newest` (unknown value → `400`).
- Progress: `progress_percent` must be a finite number (NaN/±∞ → `400`);
  it is clamped to 0–100.
- Admin course fields: title ≤ 200 chars; description ≤ 10000;
  category ≤ 60; instructor ≤ 100; image_url ≤ 2000; price ≥ 0 (int);
  level ∈ Beginner/Intermediate/Advanced; duration_hours ≥ 0.
- Admin lesson fields: title ≤ 200 chars; content ≤ 20000 chars;
  duration_minutes ≥ 0 (int); order_index int; is_preview ∈ {0, 1}.

## Database schema (`backend/schema.sql`)

- **users** - `id, name, email (unique), password_hash, created_at`
- **courses** - `id, title, description, category, price (INR), instructor, duration_hours, level, image_url, created_at`
- **lessons** - `id, course_id, title, content_url, duration_minutes, order_index, is_preview` (1 = free preview lesson, viewable without enrolment; the first lesson of every course is a preview)
- **enrollments** - `id, user_id, course_id, enrolled_at, progress_percent` (unique user+course)
- **cart_items** - `id, user_id, course_id` (unique user+course)
- **orders** - `id, user_id, total (INR), status, created_at`
- **reviews** - `id, user_id, course_id, rating (1-5), comment, created_at` (unique user+course)
- **wishlist** - `id, user_id, course_id, added_at` (unique user+course; one entry per learner per course)
- **certificates** - `id, user_id, course_id, certificate_code, issued_at` (unique user+course; issued when progress hits 100%)
- **auth_tokens** - `token, user_id, created_at` (login sessions survive restarts)
- **lesson_content** - `lesson_id (PK), body (teachable HTML), flowchart_title, flowchart_json (nodes/edges), video_id, video_title`
- **quizzes** - `id, lesson_id, question, options_json (4 options), answer_index (0-3), explanation, order_index`
- **quiz_attempts** - `id, user_id, lesson_id, score, total, answers_json, taken_at`
- **tasks** - `id, lesson_id, type (predict | fix | fill | trace | project), title, prompt, code, expected, answer, hint, order_index`
- **task_completions** - `id, user_id, task_id, completed_at` (unique user+task)

Passwords are hashed with **SHA-256 + per-user random salt**
(`hashlib.sha256`, format `salt$digest`). Tokens are random SHA-256 values
stored server-side - never trust client data for auth. Sessions expire after
**30 days** (`user_from_token` rejects older tokens; expired rows are pruned
on each login).

Hot query paths are indexed (`CREATE INDEX IF NOT EXISTS`, applied on every
startup): lessons/course, enrolments by user / course / (user, course),
cart and wishlist by user and course, lesson_progress by user and lesson,
reviews by course and user, certificates by user, auth_tokens by token.

## Seeded catalogue

`backend/seed.py` inserts 12 realistic courses (INR pricing), each with 6
lessons: Web Development Bootcamp, JavaScript, Python Masterclass, Machine
Learning, Deep Learning, Data Science with SQL & Python, UI/UX Design,
React, Digital Marketing, Django Full-Stack, TypeScript, and Git & GitHub.

## Learning LMS — real courses, flowcharts, quizzes, tasks, tutor

`backend/seed.py` also loads `backend/content/*.json` (see
`backend/content/CONTENT_SPEC.md`) — full learning paths with real
explanations, code, flowcharts, MCQs, practice tasks and free videos.
The loader is idempotent: re-running the seed on an existing database
updates the content without wiping enrolments or progress
(`python3 backend/seed_content.py` runs the loader on its own).

| Course | Lessons | MCQs | Tasks | Flowcharts |
|---|---|---|---|---|
| Python Programming Masterclass (extended) | 10 | 50 | 40 | 10 |
| C Programming from Zero to Hero | 10 | 50 | 31 | 7 |
| Data Structures & Algorithms | 10 | 50 | 40 | 9 |
| Java Programming Masterclass | 8 | 48 | 31 | 7 |
| SQL Essentials: Queries to Databases | 8 | 48 | 31 | 7 |
| **Total learning content** | **46** | **246** | **173** | **40** |

- **Lesson page** — `lesson.html?id=<lesson_id>` (linked from every lesson
  row on `course-details.html`): explanation with code examples and key
  points, a free YouTube tutorial video (every embedded video ID was
  verified via YouTube oEmbed — see `backend/content/VERIFIED_VIDEOS.md`),
  the lesson flowchart rendered as inline SVG by `js/flowchart.js`
  (no dependency, works offline), the per-lesson MCQ quiz, and the practice
  tasks (predict-the-output, fix-the-bug, fill-in-the-blank, trace-the-code,
  plus one mini-project per course). Quiz scores and task completions are
  stored per user; `GET /api/courses/:id/learn-progress` summarises them.
- **Tutor chatbot** — the "💬 Ask Tutor" widget on course and lesson pages
  (`js/tutor.js` + `POST /api/tutor`) is rule-based: it explains topics in
  simple steps, walks through a lesson's flowchart step by step, quizzes
  the learner inside the chat (reply A/B/C/D), and gives hints for tasks.
  Every answer comes from the seeded course content — the tutor never
  invents anything and says so when a topic is not in the material.
  No AI API, no external calls, no cost.
- **Deploy note** — after pulling this on the live server, run
  `python3 backend/seed.py` once so the new courses/content land in the
  live database, then reload the web app. `init_db` creates the new tables
  on server start (`CREATE TABLE IF NOT EXISTS`).

### Lesson progress in the frontend

`course-details.html` loads the course's lessons from the backend and renders
a "Mark as complete" button per lesson (plus a progress bar fed by the
enrolment's `progress_percent`, refreshed after each completion; completing
the last lesson surfaces the certificate link). `my-courses.html` tries the
backend first (`GET /api/my-courses`) and renders real progress bars per
enrolment, falling back to the old localStorage rendering when offline or
signed out, so neither page breaks without the backend.

## Frontend integration

See **[INTEGRATION.md](INTEGRATION.md)** for the exact `<script>` tags to add
per page. Summary:

1. Add `<script src="/js/api.js"></script>` before `script.js` on every page
   (+ `<script src="/js/auth.js"></script>` on login/register).
2. Wire the forms: `LearnHubAuth.wireLoginForm("registerForm", "index.html")`.
3. Replace localStorage reads with `LearnHubAPI` calls - `api.js` already
   falls back to localStorage when the backend is offline, so pages never break.

## Tech stack (resume-aligned)

Python · JavaScript · SQL (SQLite) · HTML5/CSS3 - everything in this repo is
built from these, with zero third-party dependencies.

## Test results

See [TEST_RESULTS.md](TEST_RESULTS.md) for the verified local test run
(health, courses, register → login → cart → checkout → progress).
