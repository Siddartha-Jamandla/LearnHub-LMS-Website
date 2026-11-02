# LearnHub LMS - Full-Stack Edition

LearnHub is an online learning platform offering expert-led courses in web
development, programming, design, marketing, AI, and business - now rebuilt
as a **complete full-stack project**:

- **Frontend** - HTML, CSS, JavaScript (the original site, now API-powered)
- **Backend** - Python **standard library only** (`http.server`, `sqlite3`, `json`, `hashlib`)
- **Database** - SQLite with a clean relational schema

No Flask, no Django, no npm packages. Clone, run one command, and learn.

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
│   ├── seed.py         # seeds 10 courses + lessons (python3 backend/seed.py)
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
| GET | `/api/courses` | - | List courses. `?q=`/`?search=` (title/description), `?category=`, `?level=`; paginated via `?page=` & `?per_page=` (max 50). Returns `courses` + `total/page/per_page/pages` |
| GET | `/api/courses/:id` | - | One course (includes `avg_rating` + `review_count`) |
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
| PUT | `/api/enrollments/:id/progress` | token | `{progress_percent: 0-100}` |
| POST | `/api/lessons/:id/complete` | token | Mark a lesson complete; course progress auto-recomputes (idempotent). Includes `certificate {id, certificate_code}` when this completes the course |
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
`sessionStorage`.

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/admin/courses` | `{title*, description?, category?, price? (≥ 0), instructor?, duration_hours?, level? (Beginner/Intermediate/Advanced), image_url?}` → 201 |
| PUT | `/api/admin/courses/:id` | Update course fields → 404 if missing |
| DELETE | `/api/admin/courses/:id` | 404 if missing; 409 if enrolments exist (history preserved); lessons cascade |
| POST | `/api/admin/courses/:id/lessons` | `{title*, content_url* (or body), duration_minutes?, order_index?}` → 201 |
| PUT | `/api/admin/lessons/:id` | Update lesson fields → 404 if missing |
| DELETE | `/api/admin/lessons/:id` | 404 if missing; learner progress rows cascade |

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

## Database schema (`backend/schema.sql`)

- **users** - `id, name, email (unique), password_hash, created_at`
- **courses** - `id, title, description, category, price (INR), instructor, duration_hours, level, image_url, created_at`

- **enrollments** - `id, user_id, course_id, enrolled_at, progress_percent` (unique user+course)
- **cart_items** - `id, user_id, course_id` (unique user+course)
- **orders** - `id, user_id, total (INR), status, created_at`
- **reviews** - `id, user_id, course_id, rating (1-5), comment, created_at` (unique user+course)
- **wishlist** - `id, user_id, course_id, added_at` (unique user+course; one entry per learner per course)
- **certificates** - `id, user_id, course_id, certificate_code, issued_at` (unique user+course; issued when progress hits 100%)
- **auth_tokens** - `token, user_id, created_at` (login sessions survive restarts)

Passwords are hashed with **SHA-256 + per-user random salt**
(`hashlib.sha256`, format `salt$digest`). Tokens are random SHA-256 values
stored server-side - never trust client data for auth.

## Seeded catalogue

`backend/seed.py` inserts 10 realistic courses (INR pricing), each with 4-6
lessons: Web Development Bootcamp, JavaScript, Python Masterclass, Machine
Learning, Deep Learning, Data Science with SQL & Python, UI/UX Design,
React, Digital Marketing, and Django Full-Stack.

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
