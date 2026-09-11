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