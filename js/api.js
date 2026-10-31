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
                return d.course;
            }
            return legacyCourses().find((c) => String(c.id) === String(id)) || null;
        },

        async getLessons(courseId) {
            if (await checkApi()) {
                const d = await request("GET", `/api/courses/${courseId}/lessons`);
                return d.lessons;
            }
            return [];
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

        async getMyCourses() {
            const d = await request("GET", "/api/my-courses", null, true);
            return d.courses;
        },
    };

    window.LearnHubAPI = api;
})();
