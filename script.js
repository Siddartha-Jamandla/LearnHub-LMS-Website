/* =========================================================
   LEARN HUB — theme (lh_theme, default dark) + flagship tracks
   ========================================================= */
(function () {
    "use strict";
    if (!window.__lhThemeInit) {
        window.__lhThemeInit = true;
        try {
            document.documentElement.setAttribute("data-theme", localStorage.getItem("lh_theme") || "dark");
        } catch (e) { document.documentElement.setAttribute("data-theme", "dark"); }
    }
    function wireThemeToggles() {
        var cur = document.documentElement.getAttribute("data-theme") || "dark";
        document.querySelectorAll(".theme-toggle").forEach(function (btn) {
            btn.textContent = cur === "light" ? "☀️" : "🌙";
            if (btn.dataset.lhWired) return;
            btn.dataset.lhWired = "1";
            btn.addEventListener("click", function () {
                var next = (document.documentElement.getAttribute("data-theme") === "light") ? "dark" : "light";
                document.documentElement.setAttribute("data-theme", next);
                try { localStorage.setItem("lh_theme", next); } catch (e) { /* ignore */ }
                document.querySelectorAll(".theme-toggle").forEach(function (b) { b.textContent = next === "light" ? "☀️" : "🌙"; });
            });
        });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wireThemeToggles);
    else wireThemeToggles();
    window.lhWireThemeToggles = wireThemeToggles;
})();

/* Flagship tracks — the 5 flagship courses, in order, fetched live. */
var FLAGSHIP_TRACKS = [
    { id: 17, label: "C++" },
    { id: 14, label: "DSA" },
    { id: 3, label: "Python" },
    { id: 15, label: "Java" },
    { id: 1, label: "Web Development" },
];
async function renderFlagshipTracks(gridId) {
    var grid = document.getElementById(gridId || "flagshipGrid");
    if (!grid) return;
    try {
        var rows = window.LearnHubAPI
            ? await LearnHubAPI.getCourses({ per_page: 50 })
            : [];
        var byId = {};
        rows.forEach(function (c) { byId[c.id] = c; });
        var ordered = FLAGSHIP_TRACKS.map(function (t) { return { track: t, course: byId[t.id] }; })
            .filter(function (x) { return x.course; });
        if (!ordered.length) { grid.innerHTML = "<p>Flagship tracks are unavailable right now.</p>"; return; }
        grid.innerHTML = ordered.map(function (x) {
            var c = x.course;
            var card = (window.LearnHubUI && LearnHubUI.courseCard)
                ? LearnHubUI.courseCard(c, { badge: "Flagship" })
                : '<div class="course-card"><div class="course-content"><h3>' + c.title + '</h3><p>' + (c.description || "") + '</p><a class="btn btn-primary btn-small" href="course-details.html?id=' + c.id + '">View Course</a></div></div>';
            return '<div><span class="flagship-badge">★ Flagship · ' + x.track.label + '</span>' + card + "</div>";
        }).join("");
    } catch (e) {
        grid.innerHTML = "<p>Flagship tracks are unavailable right now.</p>";
    }
}

/* =========================================================
   LEARNHUB LMS - COMMON JAVASCRIPT
   ========================================================= */

/* -----------------------------
   COURSE DATA
------------------------------ */

const courses = [
    {
        id: 1,
        title: "Complete Web Development Bootcamp",
        category: "Development",
        instructor: "John Smith",
        price: 999,
        oldPrice: 2499,
        rating: 4.8,
        students: 2450,
        lessons: 42,
        hours: 18,
        image: "assets/images/course1.svg",
        description:
            "Learn HTML, CSS, JavaScript and modern web development from beginner to advanced level."
    },
    {
        id: 2,
        title: "JavaScript From Beginner to Advanced",
        category: "Programming",
        instructor: "Sarah Williams",
        price: 799,
        oldPrice: 1999,
        rating: 4.9,
        students: 1890,
        lessons: 35,
        hours: 14,
        image: "assets/images/course2.svg",
        description:
            "Master JavaScript fundamentals, DOM manipulation, events, APIs and modern JavaScript."
    },
    {
        id: 3,
        title: "Python Programming Masterclass",
        category: "Data Science",
        instructor: "Michael Brown",
        price: 899,
        oldPrice: 2299,
        rating: 4.7,
        students: 3120,
        lessons: 50,
        hours: 22,
        image: "assets/images/course3.svg",
        description:
            "Learn Python programming from scratch and build practical projects."
    },
    {
        id: 4,
        title: "UI/UX Design Complete Guide",
        category: "Design",
        instructor: "Emily Johnson",
        price: 699,
        oldPrice: 1799,
        rating: 4.8,
        students: 1540,
        lessons: 28,
        hours: 12,
        image: "assets/images/course4.svg",
        description:
            "Learn user interface and user experience design principles and workflows."
    },
    {
        id: 5,
        title: "React JS Complete Course",
        category: "Development",
        instructor: "David Wilson",
        price: 1099,
        oldPrice: 2799,
        rating: 4.8,
        students: 2100,
        lessons: 40,
        hours: 20,
        image: "assets/images/course5.svg",
        description:
            "Build modern interactive websites using React JS."
    },
    {
        id: 6,
        title: "Digital Marketing Masterclass",
        category: "Business",
        instructor: "Robert Davis",
        price: 599,
        oldPrice: 1499,
        rating: 4.6,
        students: 1200,
        lessons: 30,
        hours: 10,
        image: "assets/images/course6.svg",
        description:
            "Learn SEO, social media marketing, content marketing and digital strategy."
    },
    {
        id: 7,
        title: "Machine Learning Fundamentals",
        category: "Artificial Intelligence",
        instructor: "Daniel Miller",
        price: 1299,
        oldPrice: 2999,
        rating: 4.9,
        students: 980,
        lessons: 45,
        hours: 25,
        image: "assets/images/course7.svg",
        description:
            "Understand machine learning algorithms and build your first ML projects."
    },
    {
        id: 8,
        title: "SQL and Database Fundamentals",
        category: "Programming",
        instructor: "James Anderson",
        price: 499,
        oldPrice: 1199,
        rating: 4.7,
        students: 1600,
        lessons: 25,
        hours: 9,
        image: "assets/images/course8.svg",
        description:
            "Learn SQL queries, relational databases and database design."
    },
    {
        id: 13,
        title: "C Programming from Zero to Hero",
        category: "Programming",
        instructor: "Arjun Reddy",
        price: 899,
        oldPrice: 1999,
        rating: "New",
        students: 0,
        lessons: 10,
        hours: 20,
        image: "assets/images/course4.svg",
        description:
            "Learn C from scratch: setup, variables, loops, functions, pointers, structures and files, with MCQs, flowcharts, videos and hands-on tasks."
    },
    {
        id: 14,
        title: "Data Structures & Algorithms",
        category: "Programming",
        instructor: "Priya Sharma",
        price: 1299,
        oldPrice: 2999,
        rating: "New",
        students: 0,
        lessons: 10,
        hours: 24,
        image: "assets/images/course5.svg",
        description:
            "Learn the data structures and algorithms behind fast software: Big-O, arrays, linked lists, stacks, trees, graphs and sorting, with MCQs, flowcharts, videos and tasks."
    },
    {
        id: 15,
        title: "Java Programming Masterclass",
        category: "Programming",
        instructor: "Sarah Williams",
        price: 999,
        oldPrice: 2299,
        rating: "New",
        students: 0,
        lessons: 8,
        hours: 18,
        image: "assets/images/course2.svg",
        description:
            "Learn Java from scratch - setup, core syntax, object-oriented programming, collections, files and exceptions, with MCQs, flowcharts, videos and tasks."
    },
    {
        id: 16,
        title: "SQL Essentials: Queries to Databases",
        category: "Data Science",
        instructor: "Kavya Nair",
        price: 799,
        oldPrice: 1799,
        rating: "New",
        students: 0,
        lessons: 8,
        hours: 12,
        image: "assets/images/course6.svg",
        description:
            "Learn SQL from zero: query real tables, filter and sort data, join tables, aggregate results and design databases, with MCQs, flowcharts, videos and tasks."
    }
];


/* -----------------------------
   LOCAL STORAGE HELPERS
------------------------------ */

function getCart() {
    return JSON.parse(localStorage.getItem("cart")) || [];
}

function saveCart(cart) {
    localStorage.setItem("cart", JSON.stringify(cart));
}

function getWishlist() {
    return JSON.parse(localStorage.getItem("wishlist")) || [];
}

function saveWishlist(wishlist) {
    localStorage.setItem("wishlist", JSON.stringify(wishlist));
}

function getCurrentUser() {
    return JSON.parse(localStorage.getItem("currentUser"));
}


/* -----------------------------
   CART + WISHLIST (API-first)
   Signed-in users use the server cart/wishlist (POST /api/cart,
   /api/wishlist); signed-out users are sent to login instead of
   silently storing ids that the backend can never see.
------------------------------ */

function apiSignedIn() {
    return !!localStorage.getItem("lh_token");
}

function requireSignIn() {
    alert("Please sign in first.");
    window.location.href = "login.html";
    return false;
}

async function addToCart(id) {
    if (!window.LearnHubAPI) { alert("Cart is unavailable right now."); return; }
    if (!apiSignedIn()) return requireSignIn();
    try {
        await LearnHubAPI.addToCart(Number(id));
        alert("Course added to cart!");
    } catch (e) {
        alert(e.message || "Could not add to cart.");
    }
    updateCartCount();
}

async function removeFromCart(id) {
    if (!window.LearnHubAPI || !apiSignedIn()) {
        // Guest cart lives in localStorage only.
        saveCart(getCart().filter(function (cid) { return cid !== Number(id); }));
        if (typeof renderCart === "function") renderCart();
        updateCartCount();
        return;
    }
    try {
        // Backend delete takes the cart_item_id, not the course id:
        // resolve it from the current server cart first.
        var items = await LearnHubAPI.getCart();
        var item = items.find(function (it) {
            return Number(it.course ? it.course.id : it.course_id) === Number(id);
        });
        if (item) await LearnHubAPI.removeFromCart(item.cart_item_id);
    } catch (e) {
        alert(e.message || "Could not remove from cart.");
    }
    if (typeof renderCart === "function") renderCart();
    updateCartCount();
}

async function addToWishlist(id) {
    if (!window.LearnHubAPI) { alert("Wishlist is unavailable right now."); return; }
    if (!apiSignedIn()) return requireSignIn();
    try {
        var d = await LearnHubAPI.addToWishlist(Number(id));
        alert(d && d.added === false ? "Course is already in your wishlist." : "Course added to wishlist!");
    } catch (e) {
        alert(e.message || "Could not add to wishlist.");
    }
}

async function removeFromWishlist(id) {
    if (!window.LearnHubAPI || !apiSignedIn()) {
        // Guest wishlist lives in localStorage only.
        saveWishlist(getWishlist().filter(function (cid) { return cid !== Number(id); }));
        if (typeof renderWishlist === "function") renderWishlist();
        return;
    }
    try {
        await LearnHubAPI.removeFromWishlist(Number(id));
    } catch (e) {
        alert(e.message || "Could not remove from wishlist.");
    }
    if (typeof renderWishlist === "function") renderWishlist();
}

async function updateCartCount() {
    const cartCount = document.getElementById("cart-count");
    if (!cartCount) return;
    if (localStorage.getItem("lh_token") && window.LearnHubAPI) {
        try {
            const items = await LearnHubAPI.getCart();
            cartCount.textContent = items.length;
            return;
        } catch (e) { /* fall through to local count */ }
    }
    cartCount.textContent = getCart().length;
}

/* -----------------------------
   COURSE FINDER
------------------------------ */

function getCourseById(id) {
    return courses.find(course => course.id === Number(id));
}


/* -----------------------------
   CURRENCY
------------------------------ */

function formatPrice(price) {
    return "₹" + Number(price).toLocaleString("en-IN");
}


/* -----------------------------
   REGISTER / LOGIN
   Auth lives in js/api.js + js/auth.js and the login.html /
   register.html pages (server accounts, Bearer token in
   localStorage as lh_token). The old handlers below stored
   plaintext passwords in localStorage and never called the
   backend, so they were removed — do not re-add them.
------------------------------ */

/* -----------------------------
   LOGOUT
------------------------------ */


async function logout() {
    try { if (window.LearnHubAPI) await LearnHubAPI.logout(); } catch (e) { /* ignore */ }
    localStorage.removeItem("currentUser");
    localStorage.removeItem("registeredUser");
    window.location.href = "index.html";
}


/* -----------------------------
   CHECKOUT
------------------------------ */

const checkoutForm = document.getElementById("checkoutForm");

if (checkoutForm) {

    checkoutForm.addEventListener("submit", async function (event) {

        event.preventDefault();

        if (!localStorage.getItem("lh_token")) {
            alert("Please sign in before checkout.");
            window.location.href = "login.html";
            return;
        }

        var btn = checkoutForm.querySelector('[type="submit"]');
        if (btn) { btn.disabled = true; btn.textContent = "Processing…"; }
        try {
            var d = await LearnHubAPI.checkout();
            var payments = (d && d.payments) || [];
            var statusBox = document.getElementById("checkoutStatus");
            if (statusBox) {
                statusBox.hidden = false;
                statusBox.innerHTML = '<div class="test-mode-notice"><strong>🧪 TEST MODE — Razorpay test mock (razorpay-test-mock).</strong> No real money is charged. ' +
                    "Order total: <strong>" + formatPrice(d.total || 0) + " " + (d.currency || "INR") + "</strong>" +
                    (d.payments && d.payments.length ? "<br>Gateway order(s): " + d.payments.map(function (p) { return p.gateway_order_id; }).join(", ") : "") +
                    "<br>Verifying test payments…</div>";
            }
            var ids = [];
            for (var i = 0; i < payments.length; i++) {
                try {
                    var v = await LearnHubAPI.verifyPayment(payments[i].id, payments[i].demo_signature);
                    if (v && v.enrolled_course_ids) ids = ids.concat(v.enrolled_course_ids);
                } catch (verErr) { /* keep going; success page re-checks paid status */ }
            }
            var pidParam = payments.map(function (p) { return p.id; }).join(",");
            window.location.href = "payment-success.html" + (pidParam ? "?payment_ids=" + encodeURIComponent(pidParam) : "");
        } catch (e) {
            alert(e.message || "Checkout failed.");
            if (btn) { btn.disabled = false; btn.textContent = "Complete Enrolment"; }
        }
    });
}


/* -----------------------------
   PAGE INITIALIZATION
------------------------------ */

document.addEventListener("DOMContentLoaded", function () {

    updateCartCount();

    updateNavigation();

});


/* -----------------------------
   NAVIGATION USER STATE
------------------------------ */

function updateNavigation() {

    let user = null;
    try { user = JSON.parse(localStorage.getItem("lh_user")); } catch (e) { user = null; }
    if (!user) user = getCurrentUser();

    const loginLinks = document.querySelectorAll(
        'a[href="login.html"]'
    );

    if (user) {

        loginLinks.forEach(link => {
            if (link.classList.contains("btn")) {
                link.textContent = "Profile";
                link.href = "profile.html";
            }
        });
    }
}


/* =========================================================
   ULTIMATE LMS - shared frontend helpers
   (search, ratings, estimated minutes, notifications)
   ========================================================= */
(function () {
    "use strict";

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function isSignedIn() {
        return !!localStorage.getItem("lh_token");
    }

    // Minimal authenticated fetch against the same-origin API.
    // Throws an Error with .status (e.g. 404/409) on failure.
    async function lhApi(path, options) {
        options = options || {};
        var headers = { "Content-Type": "application/json" };
        var token = localStorage.getItem("lh_token");
        if (token) headers["Authorization"] = "Bearer " + token;
        var res = await fetch(path, {
            method: options.method || "GET",
            headers: headers,
            body: options.body ? JSON.stringify(options.body) : undefined,
        });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) {
            var err = new Error(data.error || ("Request failed (" + res.status + ")"));
            err.status = res.status;
            err.data = data;
            throw err;
        }
        return data;
    }

    // Star string for an average rating (0-5). Rounds to the nearest
    // whole star - honest, no fake precision.
    function stars(rating) {
        var r = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
        return "★".repeat(r) + "☆".repeat(5 - r);
    }

    function ratingOf(c) {
        var r = (c.avg_rating != null ? c.avg_rating : c.rating);
        return (r == null || isNaN(Number(r))) ? 0 : Number(r);
    }

    function reviewCountOf(c) {
        var n = (c.review_count != null ? c.review_count : c.reviews_count);
        return n == null ? 0 : Number(n) || 0;
    }

    // Estimated lesson minutes from the reading load + video:
    //   max(1, round(word_count(body) / 200)) + (video ? 5 : 0)
    // body is HTML - tags are stripped before counting words.
    function estimateMinutes(bodyHtml, hasVideo) {
        var text = String(bodyHtml || "").replace(/<[^>]*>/g, " ").replace(/&nbsp;/g, " ");
        var words = text.trim().split(/\s+/).filter(Boolean).length;
        return Math.max(1, Math.round(words / 200)) + (hasVideo ? 5 : 0);
    }

    // Search via the new /api/search endpoint; falls back to the
    // existing /api/courses list (client-side filter/sort) while the
    // new endpoint is still being rolled out.
    async function searchCourses(params) {
        params = params || {};
        var qs = new URLSearchParams();
        if (params.q) qs.set("q", params.q);
        if (params.category) qs.set("category", params.category);
        if (params.level) qs.set("level", params.level);
        if (params.max_price != null && params.max_price !== "") qs.set("max_price", params.max_price);
        if (params.sort) qs.set("sort", params.sort);
        try {
            var d = await lhApi("/api/search" + (qs.toString() ? "?" + qs.toString() : ""));
            return d.results || d.courses || [];  // contract says "results"; live backend returns "courses"
        } catch (e) {
            if (e.status !== 404) throw e;
        }
        // Fallback: /api/courses supports q/category/level + sort
        // rating|price_asc|price_desc|newest (not the /api/search names).
        var qs2 = new URLSearchParams();
        if (params.q) qs2.set("q", params.q);
        if (params.category) qs2.set("category", params.category);
        if (params.level) qs2.set("level", params.level);
        if (params.sort === "rating") qs2.set("sort", "rating");
        else if (params.sort === "newest") qs2.set("sort", "newest");
        else if (params.sort === "price") qs2.set("sort", "price_asc");
        qs2.set("per_page", "50");
        var list = await lhApi("/api/courses" + (qs2.toString() ? "?" + qs2.toString() : ""));
        var rows = (list.courses || []).filter(function (c) {
            if (params.max_price != null && params.max_price !== "" &&
                Number(c.price) > Number(params.max_price)) return false;
            return true;
        });
        if (params.sort === "price") {
            rows.sort(function (a, b) { return a.price - b.price; });
        } else if (params.sort === "rating") {
            rows.sort(function (a, b) { return ratingOf(b) - ratingOf(a); });
        }
        return rows;
    }

    // One course card, reusing the existing .course-card markup.
    // Works with both API shapes (avg_rating/review_count from the
    // new endpoints, rating/students from the legacy static data).
    function courseCard(c, opts) {
        opts = opts || {};
        var rating = ratingOf(c);
        var reviews = reviewCountOf(c);
        var ratingHtml = rating > 0
            ? esc(stars(rating)) + " " + rating.toFixed(1) +
              (reviews ? " <span>(" + reviews + " review" + (reviews === 1 ? "" : "s") + ")</span>" : " <span>(no reviews yet)</span>")
            : "No reviews yet";
        var learners = (c.enrolment_count != null ? c.enrolment_count : c.students);
        var img = c.image_url || c.image || "assets/images/course1.svg";
        var meta = [];
        if (c.duration_hours != null) meta.push("⏱ " + c.duration_hours + " Hours");
        if (c.level) meta.push(esc(c.level));
        if (learners != null) meta.push("👥 " + learners + " learners");
        var badge = opts.badge ? '<span class="course-badge-new">' + esc(opts.badge) + "</span>" : "";
        return '<div class="course-card">' +
            '<div class="course-image">' +
            '<img src="' + esc(img) + '" alt="' + esc(c.title) + '" onerror="this.style.display=\'none\';">' +
            '<span class="course-category">' + esc(c.category || "") + "</span>" + badge +
            '<button class="wishlist-btn" onclick="addToWishlist(' + c.id + ')" title="Add to Wishlist">♡</button>' +
            "</div>" +
            '<div class="course-content">' +
            '<div class="course-rating">' + ratingHtml + "</div>" +
            "<h3>" + esc(c.title) + "</h3>" +
            '<p class="instructor">By ' + esc(c.instructor || "LearnHub") + "</p>" +
            (meta.length ? '<div class="course-info">' + meta.map(function (m) { return "<span>" + m + "</span>"; }).join("") + "</div>" : "") +
            '<div class="course-footer"><div class="course-price">' + formatPrice(c.price) + "</div>" +
            '<a href="course-details.html?id=' + c.id + '" class="btn btn-small btn-primary">View Course</a>' +
            "</div></div></div>";
    }

    // Notification bell: shows the unread count for signed-in users,
    // stays hidden when signed out (or when the endpoint is absent).
    async function initNotifBell() {
        var bell = document.getElementById("notifBell");
        if (!bell) return;
        if (!isSignedIn()) { bell.hidden = true; return; }
        bell.hidden = false;
        var badge = document.getElementById("notifCount");
        try {
            var d = await lhApi("/api/me/notifications");
            var n = d.unread_count || 0;
            if (badge) { badge.textContent = n > 99 ? "99+" : String(n); badge.hidden = n === 0; }
        } catch (e) {
            if (badge) badge.hidden = true;
        }
    }

    window.LearnHubUI = {
        esc: esc, isSignedIn: isSignedIn, lhApi: lhApi,
        stars: stars, ratingOf: ratingOf, reviewCountOf: reviewCountOf,
        estimateMinutes: estimateMinutes, searchCourses: searchCourses,
        courseCard: courseCard, initNotifBell: initNotifBell,
    };
    document.addEventListener("DOMContentLoaded", initNotifBell);
})();
