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

---

## Learn Hub build — backend tests (9 Nov 2026, ~19:00 IST)

Tested locally only, against a throwaway DB (`DB_PATH=/tmp/lh-test/test.db`,
`PORT=8123`, seeded fresh with `backend/seed.py`). The committed
`backend/learnhub.db` was NOT touched (mtime still 8 Nov 18:02) and the live
site was not touched. `python3 -m py_compile backend/app.py` ✅.
Full curl log: `/tmp/lh-test/run_tests.sh` + `/tmp/lh-test/results.txt`
(temp files, not in the repo).

| Test | Result |
|---|---|
| `GET /api/health` | ✅ 200, `error_bot` healthy |
| `GET /api/courses?per_page=50` | ✅ 17 courses; C++ id 17, ₹999; flagships 1, 3, 14, 15, 17 present |
| `GET /api/courses/17/lessons` | ✅ 6 lessons (Setup, Variables, Control Flow, Functions, OOP, STL) |
| `POST /api/register` | ✅ 201, `otp_required: true`, NO token issued |
| `POST /api/login` (password correct, no OTP yet) | ✅ 200, `otp_required: true`, NO token |
| `POST /api/auth/request-otp` | ✅ 200, 6-digit `demo_otp` + demo-mode note; plain OTP never logged/stored (SHA256 hash only) |
| `POST /api/auth/verify-otp` wrong code | ✅ 401 "Incorrect OTP" |
| `POST /api/auth/verify-otp` correct code | ✅ 200, 64-char token, `email_verified` set, `lh_token` cookie set |
| OTP rate limit (6 requests/hour/email) | ✅ 6th request 429 |
| Notes CRUD (`POST/GET?q=/PUT/DELETE /api/me/notes`) | ✅ pass; 2nd user sees empty list (per-user isolation) |
| `GET /api/courses/17/assignments` | ✅ 1 assignment "Two Sum in C++"; 5 seeded total (C++ 17, DSA 14, Python 3, Java 15, Web Dev 1) |
| Assignment `start` without enrolment | ✅ 403 "Enrol in this course…" |
| `POST /api/checkout` | ✅ 200, `gateway: razorpay-test-mock`, `test_mode: true`, payment id 1, `order_id LH-3E74D515CB`, `gateway_order_id LH-TEST-…`, total ₹999; NO enrolment yet |
| `POST /api/payments/1/verify` wrong signature | ✅ 401 "Invalid payment signature" |
| `POST /api/payments/1/verify` correct demo signature | ✅ 200, enrolled in course 17, order row created, cart cleared |
| `GET /api/payments/me` | ✅ 1 payment, status `paid`, ₹999 |
| `GET /api/me/dashboard` | ✅ `purchase_history` (1 paid payment) + `resources` (C++, 6 lessons) |
| Assignment `start` after enrolment | ✅ 200, `attempt_id` 1, 30 min |
| Assignment `event` tab_switch x4 | ✅ counters 1→4, `flagged: true` after the 4th (>3); paste + rightclick counted |
| Assignment `submit` (keyword-matching code) | ✅ 200, score 100/100, `flagged: true` |
| Shield: SQLi `UNION SELECT` in query | ✅ 403 (after fix: first run scanned the encoded URL and missed it — fixed to scan the percent-decoded target; retested 403) |
| Shield: XSS `<script>` in query | ✅ 403 |
| Shield: encoded path traversal `%2e%2e%2f`, `DROP TABLE` | ✅ 403 each; events persisted in `security_events` |
| Shield: normal search / course fetch | ✅ 200 (no false positives) |
| Brute force: 5 bad logins then 6th | ✅ 401 x5, then 429 block; `brute_force` high-severity event logged |
| `GET /api/admin/security` as non-admin | ✅ 403 |
| Admin register (`siddarthajamandla@gmail.com`) + OTP | ✅ `is_admin: true` (Gmail-admin grant intact) |
| `GET /api/admin/security` as admin | ✅ counts `{total: 6, blocked: 1, brute_force: 1, failed_login: 5}` |
| `GET /api/admin/security/stats`, `/api/admin/audit-logs` | ✅ stats + real audit rows (register, otp_verified, payment_verified, assignment_*) |
| `GET /api/admin/payments` | ✅ `total_revenue: 999`, 1 payment |
| `GET /api/admin/assignments/attempts` | ✅ 1 attempt, flagged 1, score 100 |
| `GET /api/admin/stats` | ✅ `revenue_from_payments: 999` |
| `GET /api/errors` as admin | ✅ 200, `errors: []` (no runtime errors during tests) |
| `GET /super-admin.html` anonymous / non-admin / admin | ✅ 404 / 404 / 200 |
| Admin course CRUD (create → price update → delete) | ✅ instant reflection; `GET /api/courses/:id` sends `Cache-Control: no-store`; delete → 404 |
| `GET /api/me/notes` unauthenticated | ✅ 401 |

## Notes / known issues (backend)
- One pre-existing bug found, NOT introduced here: `GET /api/enrollments`
  returns the course object without its `id` (the `SELECT e.id, …, c.*`
  has two `id` columns and `dict(row)` keeps only one). Enrolment itself
  works — verified via dashboard `resources` + assignment start. Left
  unfixed as out of scope; worth a one-line fix in a follow-up.
- Checkout is now two-step (checkout → verify) by design: the old
  "checkout enrols immediately" behaviour is replaced by the mock-gateway
  flow. Old `TEST_RESULTS.md` checkout rows describe the previous behaviour.
- Unverified users cannot obtain a token at all (tokens are issued only by
  `verify-otp`), so the checkout `email_verified` guard is defence-in-depth
  and is not reachable via the public API.
- Assignment scoring is a documented heuristic (share of expected keywords
  present in the submitted code), not code execution — the backend runs no
  untrusted code.
- Test users (`test@example.com`, `second@example.com`,
  `siddarthajamandla@gmail.com` as admin) exist only in the throwaway
  `/tmp/lh-test/test.db`, not in the repo DB.

---

## Learn Hub merge — re-test (9 Nov 2026, ~19:30 IST)

Merged branch `learn-hub` (69b0525, Learn Hub work built on dae737d) onto
origin/main c759063 (professional LMS live). Tested locally only: whole repo
copied to /tmp/lh-merge-test, fresh DB via `backend/seed.py`
(`DB_PATH=/tmp/lh-merge-test/test.db`, `PORT=8123`). The committed
`backend/learnhub.db` was NOT touched (mtime still 8 Nov 18:02) and the live
site was not touched. `python3 -m py_compile backend/app.py` ✅, no duplicate
handler definitions, all Learn Hub + professional routes present (93 routes).

First run: **42/45 checks passing.** The 3 "failures" were test-script
artefacts, all re-verified in a second run:

| Test | Result |
|---|---|
| `GET /api/health` | ✅ 200, error_bot healthy |
| `GET /api/courses?per_page=50` | ✅ 17 courses; C++ id 17, ₹999 |
| `POST /api/register` / `POST /api/login` | ✅ 201/200, `otp_required: true`, NO token issued |
| `POST /api/auth/request-otp` + `verify-otp` (wrong, then right) | ✅ 200, 6-digit demo OTP; wrong code 401; correct code → 64-char token, `email_verified` set |
| Notes CRUD `POST/GET/PUT/DELETE /api/me/notes` | ✅ pass; deleted note no longer listed |
| `GET /api/courses/17/assignments` | ✅ 1 assignment "Two Sum in C++" |
| Assignment `start` without enrolment | ✅ 403 "Enrol in this course…" |
| `POST /api/cart` + `POST /api/checkout` | ✅ 200, `gateway: razorpay-test-mock`, `test_mode: true`, pending payment, NO enrolment yet |
| `POST /api/payments/:id/verify` wrong / correct signature | ✅ 401 / 200, enrolled in course 17, cart cleared |
| `GET /api/payments/me`, `GET /api/me/dashboard` | ✅ 1 paid payment; `purchase_history` + `resources` present |
| Assignment `start` after enrolment | ✅ 200, `attempt_id` returned |
| Assignment `event` tab_switch x4 (with `attempt_id`) | ✅ counters 1→4, `flagged: true` after 4th (>3); paste counted too |
| Assignment `submit` (with `attempt_id`) | ✅ 200, score 50/100 — correct: submitted code matched 2 of 4 expected keywords (`unordered_map`, `return`; missing `target`, `nums`) |
| Shield: `UNION SELECT`, `<script>` in query | ✅ 403 each; normal search still 200 |
| Admin (`siddarthajamandla@gmail.com` + OTP) `is_admin: true` | ✅ Gmail-admin grant intact |
| `GET /api/admin/security`, `/api/admin/audit-logs`, `/api/admin/payments` as admin | ✅ 200; non-admin 403 |
| `GET /super-admin.html` anon / non-admin / admin | ✅ 404 / 404 / 200 |
| `GET /api/learning-paths` | ✅ 4 paths |
| `GET /api/search?q=python`, `GET /api/leaderboard` | ✅ 200 |
| `GET /api/courses?sort=newest` | ✅ 200 (Newest First restored in merge — Learn Hub had dropped it) |
| `GET /api/courses/3/final-exam` (enrolled) | ✅ 200, questions returned |
| `GET /api/me/notifications` | ✅ 200 |
| `dashboard.html`, `notes.html`, `exam.html` | ✅ 200 each |

## Merge notes / known gaps (carried over, not introduced by the merge)

- C++ flagship course (id 17) has lessons but **no quiz bank yet**, so
  `GET /api/courses/17/final-exam` returns "This course has no quiz
  questions yet" (correct behaviour; the endpoint works — verified on
  course 3). Follow-up: seed C++ quizzes.
- Threat shield scans the URL path + query for all methods (shared `_route`
  handler) but does NOT scan JSON request bodies (`_shield_scan_body` is
  mentioned in a comment only). Parameterised queries still protect the DB;
  body scanning is a follow-up hardening item.
- Pre-existing bug (found by the Learn Hub build, not the merge):
  `GET /api/enrollments` returns the course object without its `id`
  (two `id` columns in the SELECT, `dict(row)` keeps one). Enrolment itself
  works. Worth a one-line fix in a follow-up.
  **Fixed 2026-11-10** (`e.id AS enrollment_id`; see the 2026-11-10
  enrolments section below).
- Checkout is two-step by design (checkout → payment verify → enrolment):
  the old "checkout enrols immediately" behaviour is replaced by the
  mock-gateway flow. Old TEST_RESULTS rows describing the previous
  behaviour are historical.

---

## Daily upgrade — 2026-11-10 (IST): enrolments id fix

`GET /api/enrollments` returned the wrong `id`: the query
`SELECT e.id, ..., c.*` has two `id` columns and `dict(row)` kept the
course id, so the enrolment id was the course id and the nested course
had no `id` at all (the frontend `updateProgress(enrollmentId)` was
therefore calling the wrong id). Fixed by aliasing
`e.id AS enrollment_id`, mirroring `GET /api/my-courses`.

Tested on a scratch DB from this commit's `backend/app.py` (port 8141,
seeded fresh, OTP + test-mode checkout flow): **19 checks, all passing**.
Enrolled in course 2 first (enrolment row id 1, course id 2): the API
returned `id: 1` with `course.id: 2`, matching the `enrollments` table
row, and `PUT /api/enrollments/1/progress` worked with the returned id.
