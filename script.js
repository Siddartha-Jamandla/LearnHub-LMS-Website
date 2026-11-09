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
   CART
------------------------------ */

function addToCart(id) {

    const cart = getCart();

    if (!cart.includes(Number(id))) {
        cart.push(Number(id));
        saveCart(cart);
        alert("Course added to cart!");
    } else {
        alert("This course is already in your cart.");
    }

    updateCartCount();
}

function removeFromCart(id) {

    let cart = getCart();

    cart = cart.filter(courseId => courseId !== Number(id));

    saveCart(cart);

    if (typeof renderCart === "function") {
        renderCart();
    }

    updateCartCount();
}

function updateCartCount() {

    const cartCount = document.getElementById("cart-count");

    if (cartCount) {
        cartCount.textContent = getCart().length;
    }
}


/* -----------------------------
   WISHLIST
------------------------------ */

function addToWishlist(id) {

    const wishlist = getWishlist();

    if (!wishlist.includes(Number(id))) {
        wishlist.push(Number(id));
        saveWishlist(wishlist);
        alert("Course added to wishlist!");
    } else {
        alert("Course is already in your wishlist.");
    }
}

function removeFromWishlist(id) {

    let wishlist = getWishlist();

    wishlist = wishlist.filter(courseId => courseId !== Number(id));

    saveWishlist(wishlist);

    if (typeof renderWishlist === "function") {
        renderWishlist();
    }
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
   REGISTER
------------------------------ */

const registerForm = document.getElementById("registerForm");

if (registerForm) {

    registerForm.addEventListener("submit", function (event) {

        event.preventDefault();

        const name = document.getElementById("registerName").value.trim();
        const email = document.getElementById("registerEmail").value.trim();
        const password = document.getElementById("registerPassword").value;
        const confirmPassword =
            document.getElementById("confirmPassword").value;

        if (password !== confirmPassword) {
            alert("Passwords do not match.");
            return;
        }

        const user = {
            name: name,
            email: email,
            password: password
        };

        localStorage.setItem("registeredUser", JSON.stringify(user));

        alert("Registration successful!");

        window.location.href = "login.html";
    });
}


/* -----------------------------
   LOGIN
------------------------------ */

const loginForm = document.getElementById("loginForm");

if (loginForm) {

    loginForm.addEventListener("submit", function (event) {

        event.preventDefault();

        const email = document.getElementById("loginEmail").value.trim();
        const password = document.getElementById("loginPassword").value;

        const registeredUser =
            JSON.parse(localStorage.getItem("registeredUser"));

        if (!registeredUser) {
            alert("No account found. Please register first.");
            return;
        }

        if (
            email === registeredUser.email &&
            password === registeredUser.password
        ) {

            localStorage.setItem(
                "currentUser",
                JSON.stringify(registeredUser)
            );

            alert("Login successful!");

            window.location.href = "courses.html";

        } else {

            alert("Invalid email or password.");

        }
    });
}


/* -----------------------------
   LOGOUT
------------------------------ */

function logout() {

    localStorage.removeItem("currentUser");

    alert("Logged out successfully.");

    window.location.href = "index.html";
}


/* -----------------------------
   CHECKOUT
------------------------------ */

const checkoutForm = document.getElementById("checkoutForm");

if (checkoutForm) {

    checkoutForm.addEventListener("submit", function (event) {

        event.preventDefault();

        const user = getCurrentUser();

        if (!user) {
            alert("Please login before checkout.");
            window.location.href = "login.html";
            return;
        }

        window.location.href = "payment-success.html";
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

    const user = getCurrentUser();

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
