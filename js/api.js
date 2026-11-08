/* =========================================================
   LEARNHUB LMS - API client
   Works against the Python backend when it is reachable,
   otherwise falls back to the page's existing localStorage
   behaviour so nothing breaks offline.
   ========================================================= */

(function () {
    "use strict";

    // If the page itself is served by the backend, talk to the same origin.
    // Otherwise assume the backend runs locally on port 8000.
    const SAME_ORIGIN_API = location.port === "8000" || location.protocol === "file:";
    const API_BASE = (SAME_ORIGIN_API && location.protocol !== "file:")
        ? `${location.protocol}//${location.host}`
        : "http://localhost:8000";

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
        if (auth) {
            const token = getToken();
            if (!token) throw new Error("Not signed in");
            headers["Authorization"] = "Bearer " + token;
        }
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
