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

## Re-test — 2026-11-09 (IST)

Live `backend/app.py` on a scratch SQLite DB (seeded: 16 courses, 6 lessons
each where seeded), port 8143. **30 checks, all passing.** Covers the
endpoints added since the 31 Oct run — admin stats, public certificate
verification, course progress summary, unenroll, course sort,
my-certificates — plus the full register → enrol → complete → certificate
→ unenroll journey and the frontend wiring behind it (`my-courses.html`
Unenroll button + certificate link, `courses.html` Newest sort).

| Test | Expected | Result |
|---|---|---|
| `GET /api/health` | 200 | ✅ pass |
| `GET /api/courses?per_page=50` | 200, 16 courses, every row has `created_at` | ✅ pass |
| `GET /api/courses?sort=bad` | 400 | ✅ pass |
| `GET /api/courses?sort=newest` | 200, newest `created_at` first | ✅ pass |
| `GET /api/search?q=python` | 200, Python course found | ✅ pass |
| `POST /api/register` + `POST /api/login` | 201 / 200 + token | ✅ pass |
| `POST /api/cart` + `POST /api/checkout` | enrolled | ✅ pass |
| `GET /api/my-courses` | 1 enrolment | ✅ pass |
| `GET /api/courses/:id/lessons` | lessons listed | ✅ pass |
| `POST /api/lessons/:id/complete` (all lessons) | 200 each | ✅ pass |
| `GET /api/courses/:id/progress` | 100%, `certificate_code` present | ✅ pass |
| `GET /api/certificates` | 1 certificate | ✅ pass |
| `GET /api/certificates/verify/:code` | 200, `valid: true` | ✅ pass |
| `GET /api/certificates/verify/LH-DOESNOTEXIST` | 404, `valid: false` | ✅ pass |
| `POST /api/reviews` + `GET /api/courses/:id/reviews` | 201, listed | ✅ pass |
| `POST /api/wishlist` + `GET /api/wishlist` | 201, 1 item | ✅ pass |
| `GET /api/admin/stats` (admin key) | 200 | ✅ pass |
| `GET /api/admin/stats` (no key) | 403 | ✅ pass |
| `POST /api/contact` | 201 | ✅ pass |
| `DELETE /api/enrollments/:course_id` | 200 | ✅ pass |
| `GET /api/my-courses` after unenroll | 0 enrolments | ✅ pass |
| `GET /api/certificates` after unenroll | certificate kept (1) | ✅ pass |
| `GET /api/courses/:id/progress` after unenroll | 403 (must be enrolled) | ✅ pass |
| `DELETE /api/enrollments/:course_id` again | 404 | ✅ pass |

## Notes

- Test user `test09lh@example.com` was used for the auth/cart/checkout flow
  and lived only in the scratch DB, which was deleted after the run.
- Seeded courses all share one `created_at` second (same seed run), so the
  `sort=newest` check verifies non-increasing `created_at` order, not a
  strict date spread.
