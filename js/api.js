/* =========================================================
   LEARNHUB LMS - API client
   Works against the Python backend when it is reachable,
   otherwise falls back to the page's existing localStorage
   behaviour so nothing breaks offline.
   ========================================================= */

(function () {
    "use strict";

    // The backend serves the frontend, so the API lives on the same
    // origin whenever the page is served over http(s) — local dev on any
    // port (8000, 8124, …) and the live PythonAnywhere site alike.
    // Only a file:// page (opened straight from disk) falls back to a
    // backend assumed on localhost:8000.
    // (The old check, location.port === "8000", sent every other hosted
    // page to localhost:8000, so lesson pages failed with "Failed to fetch".)
    const API_BASE = location.protocol === "file:"
        ? "http://localhost:8000"
        : `${location.protocol}//${location.host}`;

    let apiAvailable = null; // tri-state: null = unknown, true/false = checked

    async function checkApi() {
        if (apiAvailable !== null) return apiAvailable;
        try {
            const ctrl = new AbortController();
            const t = setTimeout(() => ctrl.abort(), 2500);
            const res = await fetch(`${API_BASE}/api/health`, { signal: ctrl.signal });
            clearTimeout(t);
            apiAvailable = res.ok;
        } catch (e) {
            apiAvailable = false;
        }
        return apiAvailable;
    }

    function getToken() {
        return localStorage.getItem("lh_token") || null;
    }

    async function request(method, path, body, auth) {
        const headers = { "Content-Type": "application/json" };
        // Attach the token whenever one is stored, so endpoints with
        // "preview = public, otherwise enrolled" rules (lesson quiz,
        // tasks, lesson detail) work for signed-in learners without
        // forcing auth on public preview access.
        const token = getToken();
        if (token) headers["Authorization"] = "Bearer " + token;
        else if (auth) throw new Error("Not signed in");
        const res = await fetch(API_BASE + path, {
            method,
            headers,
            body: body ? JSON.stringify(body) : undefined,
        });
        const data = await res.json().catch(() => ({}));
        if (!data.ok) {
            const err = new Error(data.error || `Request failed (${res.status})`);
            err.status = res.status; err.data = data;
            throw err;
        }
        return data;
    }

    /* ---------------- localStorage fallback (offline mode) ---------------- */
    const ls = {
        read(key, fallback) {
            try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
            catch (e) { return fallback; }
        },
        write(key, value) {
            localStorage.setItem(key, JSON.stringify(value));
        },
    };

    // The static site's original course list lives in script.js as `courses`.
    // The fallback reuses it when present.
    function legacyCourses() {
        return typeof courses !== "undefined" ? courses : [];
    }

    /* ---------------- public API ---------------- */
    const api = {
        base: API_BASE,
        checkApi,

        async getCourses(params = {}) {
            if (await checkApi()) {
                const qs = new URLSearchParams(params).toString();
                const d = await request("GET", "/api/courses" + (qs ? "?" + qs : ""));
                return d.courses;
            }
            return legacyCourses();
        },

        async getCourse(id) {
            if (await checkApi()) {
                const d = await request("GET", `/api/courses/${id}`);
                return d.course; // includes avg_rating + review_count
            }
            return legacyCourses().find((c) => String(c.id) === String(id)) || null;
        },

        async getReviews(courseId) {
            if (await checkApi()) {
                const d = await request("GET", `/api/courses/${courseId}/reviews`);
                return d.reviews;
            }
            return [];
        },

        async postReview(courseId, rating, comment = "") {
            // Token required; backend requires enrolment and enforces
            // rating 1-5 and one review per user per course.
            const d = await request("POST", "/api/reviews",
                { course_id: courseId, rating, comment }, true);
            return d;
        },

        async getLessons(courseId) {
            if (await checkApi()) {
                const d = await request("GET", `/api/courses/${courseId}/lessons`);
                return d.lessons;
            }
            return [];
        },

        async getLesson(id) {
            // Each lesson includes is_preview (1 = free preview, public).
            // Non-preview lessons need a token + enrolment (401/403 otherwise).
            const d = await request("GET", `/api/lessons/${id}`);
            return d.lesson;
        },

        async register(name, email, password) {
            // OTP flow: the backend now returns {ok, otp_required:true, email}
            // (no token yet). Only store a token when one is actually returned
            // (older backend). The OTP step in register.html completes sign-in.
            const d = await request("POST", "/api/register", { name, email, password });
            if (d.token) {
                localStorage.setItem("lh_token", d.token);
                if (d.user) localStorage.setItem("lh_user", JSON.stringify(d.user));
            }
            return d;
        },

        async login(email, password) {
            // OTP flow: the backend now returns {ok, otp_required:true, email}
            // (no token yet). Only store a token when one is actually returned.
            const d = await request("POST", "/api/login", { email, password });
            if (d.token) {
                localStorage.setItem("lh_token", d.token);
                if (d.user) localStorage.setItem("lh_user", JSON.stringify(d.user));
            }
            return d;
        },

        /* ---------------- OTP auth (2-step login / register) ---------------- */
        async requestOtp(email) {
            // Returns {ok, demo_otp, expires_in_seconds, note}. The demo OTP
            // is shown on screen in demo mode only; it is never console.logged.
            return request("POST", "/api/auth/request-otp", { email });
        },

        async verifyOtp(email, otp) {
            const d = await request("POST", "/api/auth/verify-otp", { email, otp });
            if (d.token) {
                localStorage.setItem("lh_token", d.token);
                if (d.user) localStorage.setItem("lh_user", JSON.stringify(d.user));
            }
            return d;
        },

        /* ---------------- personal notes (per-user, private) ---------------- */
        async getMyNotes(q) {
            const qs = q ? "?q=" + encodeURIComponent(q) : "";
            const d = await request("GET", "/api/me/notes" + qs, null, true);
            return d.notes || [];
        },
        async createMyNote(note) {
            const d = await request("POST", "/api/me/notes", note, true);
            return d.note;
        },
        async updateMyNote(id, fields) {
            const d = await request("PUT", `/api/me/notes/${id}`, fields, true);
            return d.note || d;
        },
        async deleteMyNote(id) {
            return request("DELETE", `/api/me/notes/${id}`, null, true);
        },

        /* ---------------- proctored assignments ---------------- */
        async getCourseAssignments(courseId) {
            const d = await request("GET", `/api/courses/${courseId}/assignments`);
            return d.assignments || [];
        },
        async getAssignment(id) {
            const d = await request("GET", `/api/assignments/${id}`);
            return d.assignment;
        },
        async startAssignment(id) {
            return request("POST", `/api/assignments/${id}/start`, {}, true);
        },
        async logAssignmentEvent(id, attemptId, type) {
            return request("POST", `/api/assignments/${id}/event`, { attempt_id: attemptId, type }, true);
        },
        async submitAssignment(id, attemptId, code) {
            return request("POST", `/api/assignments/${id}/submit`, { attempt_id: attemptId, code }, true);
        },

        /* ---------------- payments (Razorpay test mock) ---------------- */
        async verifyPayment(paymentId, signature) {
            return request("POST", `/api/payments/${paymentId}/verify`,
                { payment_id: paymentId, signature }, true);
        },
        async getMyPayments() {
            const d = await request("GET", "/api/payments/me", null, true);
            return d.payments || [];
        },

        /* ---------------- admin: security centre / audit / errors ---------------- */
        adminSecurity(key, limit) {
            return this._admin("GET", "/api/admin/security" + (limit ? "?limit=" + limit : "?limit=50"), key);
        },
        adminAuditLogs(key, limit) {
            return this._admin("GET", "/api/admin/audit-logs" + (limit ? "?limit=" + limit : "?limit=50"), key);
        },
        adminSecurityStats(key) {
            return this._admin("GET", "/api/admin/security/stats", key);
        },
        adminErrors(key) {
            return this._admin("GET", "/api/errors", key);
        },
        adminPayments(key) {
            return this._admin("GET", "/api/admin/payments", key);
        },
        adminAssignmentAttempts(key) {
            return this._admin("GET", "/api/admin/assignments/attempts", key);
        },

        async logout() {
            try { await request("POST", "/api/logout", null, true); } catch (e) { /* ignore */ }
            localStorage.removeItem("lh_token");
            localStorage.removeItem("lh_user");
            localStorage.removeItem("currentUser"); // legacy key
        },

        async getCart() {
            if (await checkApi()) {
                const d = await request("GET", "/api/cart", null, true);
                return d.items;
            }
            return ls.read("cart", []).map((c) => ({ cart_item_id: c.id, course: c }));
        },

        async addToCart(courseId) {
            if (await checkApi()) {
                return request("POST", "/api/cart", { course_id: courseId }, true);
            }
            const cart = ls.read("cart", []);
            const course = legacyCourses().find((c) => String(c.id) === String(courseId));
            if (course && !cart.some((c) => String(c.id) === String(courseId))) {
                cart.push(course);
                ls.write("cart", cart);
            }
            return { ok: true };
        },

        async removeFromCart(cartItemId) {
            if (await checkApi()) {
                return request("DELETE", `/api/cart/${cartItemId}`, null, true);
            }
            const cart = ls.read("cart", []).filter((c) => String(c.id) !== String(cartItemId));
            ls.write("cart", cart);
            return { ok: true };
        },

        async checkout() {
            // Test-mode Razorpay mock: returns {ok, payments:[{id, course_id,
            // amount, gateway_order_id, demo_signature}], total, currency,
            // gateway:"razorpay-test-mock", test_mode:true}. Enrolment only
            // happens after each payment is verified (see verifyPayment).
            return request("POST", "/api/checkout", null, true);
        },

        async getEnrollments() {
            const d = await request("GET", "/api/enrollments", null, true);
            return d.enrollments;
        },

        async unenroll(courseId) {
            // Removes your enrolment for a course (404 if not enrolled).
            // Your lesson progress for the course is deleted, so a later
            // re-enrolment starts fresh — but an already-earned
            // certificate is permanent and is kept.
            const d = await request("DELETE", `/api/enrollments/${courseId}`, null, true);
            return d;
        },

        async updateProgress(enrollmentId, percent) {
            const d = await request("PUT", `/api/enrollments/${enrollmentId}/progress`,
                { progress_percent: percent }, true);
            return d;
        },

        async completeLesson(lessonId) {
            // Marks one lesson complete; the backend recomputes the
            // course progress automatically (idempotent).
            const d = await request("POST", `/api/lessons/${lessonId}/complete`, null, true);
            return d;
        },

        async getCourseProgress(courseId) {
            // Token required; you must be enrolled (403 otherwise).
            // Returns {course_id, total_lessons, completed_lessons,
            // progress_percent, next_lesson_id, next_lesson_title,
            // certificate_code} — certificate_code is null until the
            // course is 100% complete and a certificate exists.
            const d = await request("GET", `/api/courses/${courseId}/progress`, null, true);
            return d;
        },

        async getCertificate(id) {
            // Token required; the backend only serves your own certificates.
            const d = await request("GET", `/api/certificates/${id}`, null, true);
            return d.certificate;
        },

        async getMyCertificates() {
            // Token required; lists only your own certificates, newest
            // first (id, certificate_code, course title, issued date).
            const d = await request("GET", "/api/certificates", null, true);
            return d.certificates;
        },

        async verifyCertificate(code) {
            // Public: no token needed. Returns {valid: true,
            // certificate_code, course_title, instructor, student_name,
            // issued_at} for a real code, or {valid: false} (404) when
            // the code does not exist.
            try {
                return await request("GET",
                    `/api/certificates/verify/${encodeURIComponent(code)}`);
            } catch (e) {
                return { ok: false, valid: false, error: e.message };
            }
        },

        async getMyCourses() {
            const d = await request("GET", "/api/my-courses", null, true);
            return d.courses;
        },

        /* ---------------- learning content: quiz / tasks / tutor ---------------- */
        async getLessonQuiz(lessonId) {
            // Questions only — answers stay on the server until submit.
            const d = await request("GET", `/api/lessons/${lessonId}/quiz`);
            return d.questions;
        },

        async submitQuiz(lessonId, answers) {
            // answers: {questionId: optionIndex}. Returns score + per-question
            // results with the correct option and the WHY explanation.
            const d = await request("POST", `/api/lessons/${lessonId}/quiz`,
                { answers }, true);
            return d;
        },

        async getLessonTasks(lessonId) {
            // Tasks without solutions; each carries a `completed` flag.
            const d = await request("GET", `/api/lessons/${lessonId}/tasks`);
            return d.tasks;
        },

        async completeTask(taskId, answer) {
            // predict/fill/trace are auto-checked; fix/project are
            // self-checked. Returns {correct, completed, expected, answer}.
            const d = await request("POST", `/api/tasks/${taskId}/complete`,
                { answer }, true);
            return d;
        },

        async getLearnProgress(courseId) {
            // Per-lesson quiz best score + tasks done/total (enrolled only).
            const d = await request("GET", `/api/courses/${courseId}/learn-progress`, null, true);
            return d.lessons;
        },

        async askTutor(message, opts = {}) {
            // Rule-based tutor: answers come only from the course content.
            // opts: {courseId, lessonId, context}.
            const d = await request("POST", "/api/tutor", {
                message,
                course_id: opts.courseId || null,
                lesson_id: opts.lessonId || null,
                context: opts.context || {},
            });
            return d;
        },

        /* ---------------- admin (instructor) ---------------- */
        // Admin endpoints accept EITHER the shared admin key (same value
        // as the backend's API_SECRET env var, passed as ?key=) OR a
        // signed-in admin user (the admin Gmail) - the stored lh_token
        // is sent as a Bearer token and the key is left out.
        async _admin(method, path, key, body) {
            const headers = { "Content-Type": "application/json" };
            const token = getToken();
            if (token) headers["Authorization"] = "Bearer " + token;
            let url = API_BASE + path;
            if (key) {
                const sep = path.includes("?") ? "&" : "?";
                url += sep + "key=" + encodeURIComponent(key);
            } else if (!token) {
                throw new Error("Sign in as admin or enter the admin key");
            }
            const res = await fetch(url, {
                method,
                headers,
                body: body ? JSON.stringify(body) : undefined,
            });
            const data = await res.json().catch(() => ({}));
            if (!data.ok) throw new Error(data.error || `Request failed (${res.status})`);
            return data;
        },

        adminCreateCourse(key, course) {
            return this._admin("POST", "/api/admin/courses", key, course);
        },

        adminUpdateCourse(key, id, fields) {
            return this._admin("PUT", `/api/admin/courses/${id}`, key, fields);
        },

        adminDeleteCourse(key, id) {
            return this._admin("DELETE", `/api/admin/courses/${id}`, key);
        },

        adminCreateLesson(key, courseId, lesson) {
            return this._admin("POST", `/api/admin/courses/${courseId}/lessons`, key, lesson);
        },

        adminUpdateLesson(key, id, fields) {
            return this._admin("PUT", `/api/admin/lessons/${id}`, key, fields);
        },

        adminDeleteLesson(key, id) {
            return this._admin("DELETE", `/api/admin/lessons/${id}`, key);
        },

        adminStats(key) {
            // Platform stats: user/course/enrolment counts, revenue
            // (orders + enrolment value) and the 5 most popular courses
            // by enrolment count.
            return this._admin("GET", "/api/admin/stats", key);
        },

        adminOverview(key) {
            // Dashboard overview: totals, popular courses, recent
            // enrolments and recently registered users.
            return this._admin("GET", "/api/admin/overview", key);
        },

        adminUsers(key, q, page) {
            const qs = new URLSearchParams();
            if (q) qs.set("q", q);
            if (page) qs.set("page", page);
            const s = qs.toString();
            return this._admin("GET", "/api/admin/users" + (s ? "?" + s : ""), key);
        },

        adminUser(key, id) {
            return this._admin("GET", `/api/admin/users/${id}`, key);
        },

        adminOrders(key, page) {
            const s = page ? "?page=" + page : "";
            return this._admin("GET", "/api/admin/orders" + s, key);
        },

        adminCertificates(key, q, page) {
            const qs = new URLSearchParams();
            if (q) qs.set("q", q);
            if (page) qs.set("page", page);
            const s = qs.toString();
            return this._admin("GET", "/api/admin/certificates" + (s ? "?" + s : ""), key);
        },

        adminAnalytics(key) {
            // Per-course learning analytics + weakest lessons.
            return this._admin("GET", "/api/admin/analytics", key);
        },

        adminLessonContent(key, lessonId) {
            // Full editable lesson content: body, flowchart, video,
            // quiz questions (with answers) and tasks (with solutions).
            return this._admin("GET", `/api/admin/lessons/${lessonId}/content`, key);
        },

        adminUpdateLessonContent(key, lessonId, fields) {
            return this._admin("PUT", `/api/admin/lessons/${lessonId}/content`, key, fields);
        },

        adminAddQuiz(key, lessonId, question) {
            return this._admin("POST", `/api/admin/lessons/${lessonId}/quiz`, key, question);
        },

        adminUpdateQuiz(key, id, fields) {
            return this._admin("PUT", `/api/admin/quiz/${id}`, key, fields);
        },

        adminDeleteQuiz(key, id) {
            return this._admin("DELETE", `/api/admin/quiz/${id}`, key);
        },

        adminAddTask(key, lessonId, task) {
            return this._admin("POST", `/api/admin/lessons/${lessonId}/tasks`, key, task);
        },

        adminUpdateTask(key, id, fields) {
            return this._admin("PUT", `/api/admin/tasks/${id}`, key, fields);
        },

        adminDeleteTask(key, id) {
            return this._admin("DELETE", `/api/admin/tasks/${id}`, key);
        },

        /* ---------------- professional LMS: dashboard / paths / social ---------------- */
        async getDashboard() {
            const d = await request("GET", "/api/me/dashboard", null, true);
            return d;
        },

        async getLeaderboard() {
            const d = await request("GET", "/api/leaderboard");
            return d.leaderboard;
        },

        async submitContact(name, email, subject, message) {
            // Public: no token needed. The message is stored for the admin.
            const d = await request("POST", "/api/contact",
                { name, email, subject, message });
            return d;
        },

        async adminContactMessages(key) {
            // Admin: newest contact-form messages first.
            return this._admin("GET", "/api/admin/contact-messages", key);
        },

        async getAnnouncements() {
            const d = await request("GET", "/api/announcements");
            return d.announcements;
        },

        async getLearningPaths() {
            const d = await request("GET", "/api/learning-paths");
            return d.paths;
        },

        async getNotes(lessonId) {
            const d = await request("GET", `/api/lessons/${lessonId}/notes`, null, true);
            return d.notes;
        },

        async addNote(lessonId, note) {
            const d = await request("POST", `/api/lessons/${lessonId}/notes`, { note }, true);
            return d;
        },

        async deleteNote(noteId) {
            return request("DELETE", `/api/notes/${noteId}`, null, true);
        },

        async bookmarkLesson(lessonId) {
            return request("POST", `/api/lessons/${lessonId}/bookmark`, null, true);
        },

        async unbookmarkLesson(lessonId) {
            return request("DELETE", `/api/lessons/${lessonId}/bookmark`, null, true);
        },

        async toggleBookmark(lessonId, currentlyBookmarked) {
            return currentlyBookmarked
                ? this.unbookmarkLesson(lessonId)
                : this.bookmarkLesson(lessonId);
        },

        async getBookmarks() {
            const d = await request("GET", "/api/me/bookmarks", null, true);
            return d.bookmarks;
        },

        async getDiscussions(lessonId) {
            const d = await request("GET", `/api/lessons/${lessonId}/discussions`);
            return d.discussions;
        },

        async postDiscussion(lessonId, body) {
            return request("POST", `/api/lessons/${lessonId}/discussions`, { body }, true);
        },

        async replyDiscussion(discussionId, body) {
            return request("POST", `/api/discussions/${discussionId}/reply`, { body }, true);
        },

        adminAnnouncements(key) {
            return this._admin("GET", "/api/admin/announcements", key);
        },

        adminCreateAnnouncement(key, announcement) {
            return this._admin("POST", "/api/admin/announcements", key, announcement);
        },

        adminDeleteAnnouncement(key, id) {
            return this._admin("DELETE", `/api/admin/announcements/${id}`, key);
        },

        adminDiscussions(key) {
            return this._admin("GET", "/api/admin/discussions", key);
        },

        adminDeleteDiscussion(key, id) {
            return this._admin("DELETE", `/api/admin/discussions/${id}`, key);
        },

        /* ---------------- Gmail-admin: status, roles, moderation, export ---------------- */
        async adminStatus() {
            // Signed-in user only (401 when signed out). Returns
            // {is_admin, email, name} as decided by the server —
            // the admin Gmail, or any user with is_admin set.
            // Token required; throws "Not signed in" without one.
            const d = await request("GET", "/api/me/admin-status", null, true);
            return d;
        },

        setUserRole(key, userId, isAdmin) {
            // Grant (1) or revoke (0) admin for one user. Admin-gated;
            // works with either the key or a signed-in admin session.
            // Returns {user: {id, name, email, is_admin}}.
            return this._admin("POST", `/api/admin/users/${userId}/role`,
                key, { is_admin: isAdmin ? 1 : 0 });
        },

        adminReviews(key, params = {}) {
            // All course reviews for moderation, paged (cap 50/page).
            // Each review carries id, rating, comment (or body),
            // created_at, course_title, user_name, user_email,
            // course_id, user_id — field names may vary slightly.
            const qs = new URLSearchParams();
            if (params.page) qs.set("page", params.page);
            if (params.per_page) qs.set("per_page", params.per_page);
            const s = qs.toString();
            return this._admin("GET", "/api/admin/reviews" + (s ? "?" + s : ""), key);
        },

        deleteAdminReview(key, id) {
            return this._admin("DELETE", `/api/admin/reviews/${id}`, key);
        },

        adminInstructors(key) {
            // Per-instructor totals: {name, courses, enrollments,
            // avg_rating, pending_qa}.
            return this._admin("GET", "/api/admin/instructors", key);
        },

        adminExportUrl(type, key) {
            // Download URL for a CSV export. In key mode the key rides
            // along as ?key= (same pattern as every admin call); in
            // session mode the Bearer token is sent by fetch instead.
            const qs = new URLSearchParams({ type });
            if (key) qs.set("key", key);
            return `${API_BASE}/api/admin/export?${qs.toString()}`;
        },

        async adminExport(type, key) {
            // Triggers a CSV download of /api/admin/export?type=...
            // Key mode: plain anchor (the key is in the URL, as with
            // every other key-mode admin call). Session mode: fetch
            // with the Bearer token and save the blob — the endpoint
            // returns text/csv, not JSON, so _admin() can't be used.
            if (key) {
                const a = document.createElement("a");
                a.href = this.adminExportUrl(type, key);
                a.download = `learnhub-${type}.csv`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                return { ok: true };
            }
            const token = getToken();
            if (!token) throw new Error("Sign in as admin or enter the admin key");
            const res = await fetch(this.adminExportUrl(type), {
                headers: { "Authorization": "Bearer " + token },
            });
            if (!res.ok) throw new Error(`Export failed (${res.status})`);
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `learnhub-${type}.csv`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            return { ok: true };
        },

        /* ---------------- wishlist ---------------- */
        async getWishlist() {
            // Backend when signed in; items embed course details
            // (id/title/price/level/avg_rating), newest first.
            const d = await request("GET", "/api/wishlist", null, true);
            return d.items;
        },

        async addToWishlist(courseId) {
            // Idempotent: 201 {added:true} on new add,
            // 200 {added:false} when already present.
            const d = await request("POST", "/api/wishlist",
                { course_id: courseId }, true);
            return d;
        },

        async removeFromWishlist(courseId) {
            return request("DELETE", `/api/wishlist/${courseId}`, null, true);
        },
    };

    window.LearnHubAPI = api;
})();

/* Theme fallback: pages that load js/api.js but not script.js (admin.html)
   still get the persisted theme + toggle wiring. Guarded so it never runs
   twice when script.js already handled it. */
(function () {
    if (window.__lhThemeInit) return;
    window.__lhThemeInit = true;
    try {
        var t = localStorage.getItem("lh_theme") || "dark";
        document.documentElement.setAttribute("data-theme", t);
    } catch (e) { document.documentElement.setAttribute("data-theme", "dark"); }
    function wire() {
        document.querySelectorAll(".theme-toggle").forEach(function (btn) {
            if (btn.dataset.lhWired) return;
            btn.dataset.lhWired = "1";
            btn.addEventListener("click", function () {
                var cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
                var next = cur === "light" ? "dark" : "light";
                document.documentElement.setAttribute("data-theme", next);
                try { localStorage.setItem("lh_theme", next); } catch (e) { /* ignore */ }
                document.querySelectorAll(".theme-toggle").forEach(function (b) { b.textContent = next === "light" ? "Dark" : "Light"; });
            });
        });
        var cur = document.documentElement.getAttribute("data-theme") || "dark";
        document.querySelectorAll(".theme-toggle").forEach(function (b) { b.textContent = cur === "light" ? "Dark" : "Light"; });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
    else wire();
})();
