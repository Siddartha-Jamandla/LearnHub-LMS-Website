/* =========================================================
   LEARNHUB LMS - auth helpers (login / register / guards)
   Depends on js/api.js (window.LearnHubAPI). Loaded on
   login.html and register.html - see INTEGRATION.md.
   ========================================================= */

(function () {
    "use strict";

    function currentUser() {
        try { return JSON.parse(localStorage.getItem("lh_user")); }
        catch (e) { return null; }
    }

    function isSignedIn() {
        return !!localStorage.getItem("lh_token");
    }

    // Redirect to login.html if the user is not signed in.
    function requireAuth() {
        if (!isSignedIn()) {
            window.location.href = "login.html";
            return false;
        }
        return true;
    }

    function showAuthError(form, message) {
        let el = form.querySelector(".auth-error");
        if (!el) {
            el = document.createElement("p");
            el.className = "auth-error";
            el.style.color = "#e11d48";
            el.style.marginTop = "10px";
            form.appendChild(el);
        }
        el.textContent = message;
    }

    function showAuthNote(form, message) {
        let el = form.querySelector(".auth-note");
        if (!el) {
            el = document.createElement("p");
            el.className = "auth-note";
            el.style.color = "#16a34a";
            el.style.marginTop = "10px";
            form.appendChild(el);
        }
        el.textContent = message;
    }

    // Field pickers: match generic ids (#email, #password, #name, name="...")
    // and the site's own register-form ids (#registerEmail, etc.).
    function field(form, names) {
        for (const n of names) {
            const el = form.querySelector(`[name="${n}"], #${n}`);
            if (el) return el.value.trim();
        }
        return "";
    }

    // Wire a <form id="login-form"> with email + password fields.
    function wireLoginForm(formId, redirectTo) {
        const form = document.getElementById(formId);
        if (!form) return;
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const email = field(form, ["email", "loginEmail", "registerEmail"]);
            const password = form.querySelector('[name="password"], #password, #loginPassword, #registerPassword')?.value || "";
            if (!email || !password) {
                showAuthError(form, "Please enter your email and password.");
                return;
            }
            try {
                const d = await window.LearnHubAPI.login(email, password);
                if (d.otp_required) { showAuthNote(form, "Check your inbox/phone for the one-time code, then enter it to finish signing in."); return; }
                showAuthNote(form, `Welcome back, ${d.user ? d.user.name : ""}! Redirecting...`);
                setTimeout(() => { window.location.href = redirectTo || "index.html"; }, 800);
            } catch (err) {
                showAuthError(form, err.message);
            }
        });
    }

    // Wire a <form id="register-form"> with name + email + password fields.
    function wireRegisterForm(formId, redirectTo) {
        const form = document.getElementById(formId);
        if (!form) return;
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const name = field(form, ["name", "fullName", "registerName"]);
            const email = field(form, ["email", "registerEmail"]);
            const password = form.querySelector('[name="password"], #password, #registerPassword')?.value || "";
            if (!name || !email || !password) {
                showAuthError(form, "Please fill in all fields.");
                return;
            }
            try {
                const d = await window.LearnHubAPI.register(name, email, password);
                if (d.otp_required) { showAuthNote(form, "Account created — check your inbox/phone for the one-time code, then enter it to finish signing in."); return; }
                showAuthNote(form, `Account created for ${d.user ? d.user.name : ""}! Redirecting...`);
                setTimeout(() => { window.location.href = redirectTo || "index.html"; }, 800);
            } catch (err) {
                showAuthError(form, err.message);
            }
        });
    }

    // Show "Hi, <name>" / Sign out in a nav slot when signed in.
    function renderAuthSlot(slotId) {
        const slot = document.getElementById(slotId);
        if (!slot) return;
        const user = currentUser();
        if (user) {
            slot.innerHTML =
                `<span>Hi, ${user.name.split(" ")[0]}</span> ` +
                `<a href="#" id="lh-logout">Sign out</a>`;
            slot.querySelector("#lh-logout").addEventListener("click", async (e) => {
                e.preventDefault();
                await window.LearnHubAPI.logout();
                window.location.href = "index.html";
            });
        }
    }

    window.LearnHubAuth = {
        currentUser, isSignedIn, requireAuth,
        wireLoginForm, wireRegisterForm, renderAuthSlot,
    };
})();
