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
        if (!data.ok) throw new Error(data.error || `Request failed (${res.status})`);
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
            const d = await request("POST", "/api/register", { name, email, password });
            localStorage.setItem("lh_token", d.token);
            localStorage.setItem("lh_user", JSON.stringify(d.user));
            return d;
        },

        async login(email, password) {
            const d = await request("POST", "/api/login", { email, password });
            localStorage.setItem("lh_token", d.token);
            localStorage.setItem("lh_user", JSON.stringify(d.user));
            return d;
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
            // Backend enrols the user in every cart course and clears the cart.
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
        // Admin endpoints need the shared admin key (same value as the
        // backend's API_SECRET env var), passed as ?key=.
        async _admin(method, path, key, body) {
            if (!key) throw new Error("Admin key is required");
            const res = await fetch(API_BASE + path + "?key=" + encodeURIComponent(key), {
                method,
                headers: { "Content-Type": "application/json" },
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
