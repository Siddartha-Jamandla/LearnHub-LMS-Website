# LearnHub Full-Stack Upgrade - Test Results

**Date:** 2026-10-31 (IST)
**Backend:** Python 3.12 stdlib only (`http.server`, `sqlite3`, `json`, `hashlib`, ...)
**Command:** `python3 backend/app.py` → `http://localhost:8000`

## Seed
- `python3 backend/seed.py` → `[seed] done: 10 courses, 54 lessons` ✅
- Re-run is idempotent (skips when courses exist) ✅

## API endpoint tests (curl)

| Test | Expected | Result |
|---|---|---|
| `GET /api/health` | 200, `{"ok":true,"service":"learnhub",...}` | ✅ pass |
| `GET /api/courses` | 200, 10 courses | ✅ pass (first: "Complete Web Development Bootcamp", ₹999) |
| `GET /api/courses/1/lessons` | 200, 6 lessons | ✅ pass (first: "HTML Foundations") |
| `GET /api/courses/999` | 404 | ✅ pass |
| `GET /api/nope` | 404 | ✅ pass |
| `POST /api/register` | 201 + token | ✅ pass |
| `POST /api/register` (same email) | 409 | ✅ pass |
| `POST /api/login` (correct) | 200 + token | ✅ pass |
| `POST /api/login` (wrong password) | 401 | ✅ pass |
| `GET /api/cart` (no token) | 401 | ✅ pass |
| `POST /api/cart` {course_id:1} | 201, cart_item_id | ✅ pass |
| `POST /api/cart` {course_id:2} | 201 | ✅ pass |
| `POST /api/cart` (duplicate) | 409 | ✅ pass |
| `GET /api/cart` (auth) | 2 items with course details | ✅ pass |
| `POST /api/checkout` | 200, order_id=1, total ₹1798 (999+799), enrolled [1,2] | ✅ pass |
| `GET /api/cart` after checkout | 0 items (cart cleared) | ✅ pass |
| `GET /api/enrollments` | 2 enrolments, progress 0.0 | ✅ pass |
| `PUT /api/enrollments/1/progress` {45} | 200, progress_percent 45.0 | ✅ pass |
| `GET /api/my-courses` | 2 courses, progress 45.0, lesson_count 6 | ✅ pass |
| `DELETE /api/cart/:id` | 200 "Removed from cart" | ✅ pass |
| `POST /api/logout` then `GET /api/cart` | 200 then 401 (token invalidated) | ✅ pass |

## Static serving

| Test | Result |
|---|---|
| `GET /` → index.html (`<title>LearnHub - Learn. Grow. Succeed.</title>`) | ✅ pass |
| `GET /courses.html` | ✅ 200 |
| `GET /js/api.js` → integration script, `text/javascript` | ✅ pass |
| `OPTIONS /api/courses` (CORS preflight) | ✅ 204 + `Access-Control-Allow-Origin: *` |

## Frontend JS

- `node --check js/api.js` ✅
- `node --check js/auth.js` ✅

## Notes
- Test user `test@example.com` was used for the auth/cart/checkout flow and
  removed afterwards; the database was re-seeded fresh so it ships with only
  the 10 courses and 54 lessons.
- Password hashing verified indirectly: correct password logs in, wrong
  password gets 401; stored value is `salt$sha256(salt+password)`.
- The full user journey tested end-to-end: **register → login → browse
  courses → view lessons → add to cart → checkout (enrolled + order created)
  → track progress → my-courses → logout**.
