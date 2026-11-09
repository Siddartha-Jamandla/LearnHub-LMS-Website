/* =========================================================
   LEARNHUB LMS - tutor chatbot widget
   Rule-based tutor: every answer comes from the course content
   via POST /api/tutor. No AI API, no external calls.
   Include on course/lesson pages and call:
       LearnHubTutor.init({ courseId: 3, lessonId: 12 })
   ========================================================= */

(function () {
    "use strict";

    var state = { courseId: null, lessonId: null, taskId: null, context: {} };
    var panel, logEl, inputEl, fabEl;
    var idleTimer = null;
    var IDLE_CLOSE_MS = 60000; /* close after 60s with no use */

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function addMsg(text, who) {
        var div = document.createElement("div");
        div.className = "tutor-msg tutor-" + who;
        div.innerHTML = esc(text).replace(/\n/g, "<br>");
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
    }

    function isOpen() {
        return panel && !panel.hidden;
    }

    function openPanel() {
        panel.hidden = false;
        if (!logEl.children.length) {
            addMsg("Hi! I am your LearnHub tutor. Ask me to explain a " +
                "topic, walk you through a flowchart, quiz you, or give " +
                "you a hint for a task.", "bot");
        }
        inputEl.focus();
        pokeIdle();
    }

    function closePanel() {
        if (!panel) return;
        panel.hidden = true;
        stopIdle();
        if (fabEl) fabEl.focus();
    }

    /* Idle auto-close: while the chat is open and nobody uses it for
       60 seconds, close it. Any pointer/key/input inside the panel or
       on the button restarts the timer. Never closes while the tutor
       is still thinking up a reply. */
    function pokeIdle() {
        stopIdle();
        if (!isOpen()) return;
        idleTimer = setTimeout(function () {
            if (isOpen() && !panel.querySelector(".tutor-typing")) closePanel();
            else pokeIdle();
        }, IDLE_CLOSE_MS);
    }

    function stopIdle() {
        if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
    }

    async function ask(message) {
        if (!message.trim()) return;
        pokeIdle();
        addMsg(message, "user");
        inputEl.value = "";
        var typing = document.createElement("div");
        typing.className = "tutor-msg tutor-bot tutor-typing";
        typing.textContent = "Thinking…";
        logEl.appendChild(typing);
        try {
            var data = await LearnHubAPI.askTutor(message, {
                courseId: state.courseId,
                lessonId: state.lessonId,
                context: Object.assign({}, state.context,
                    state.taskId ? { task_id: state.taskId } : {}),
            });
            typing.remove();
            state.context = data.context || {};
            addMsg(data.reply, "bot");
            pokeIdle();
        } catch (e) {
            typing.remove();
            addMsg("Sorry, I could not reach the tutor right now. " +
                "Check your connection and try again.", "bot");
            pokeIdle();
        }
    }

    function chip(label, message) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "tutor-chip";
        b.textContent = label;
        b.addEventListener("click", function () { ask(message); });
        return b;
    }

    function build() {
        if (document.getElementById("tutorFab")) return;

        var fab = document.createElement("button");
        fab.id = "tutorFab";
        fab.type = "button";
        fab.className = "tutor-fab";
        fab.textContent = "Ask tutor";
        fab.setAttribute("aria-label", "Open the LearnHub tutor chat");
        fabEl = fab;

        panel = document.createElement("div");
        panel.id = "tutorPanel";
        panel.className = "tutor-panel";
        panel.hidden = true;
        panel.innerHTML =
            '<div class="tutor-head">' +
            '<strong>Tutor</strong>' +
            '<span class="tutor-sub">Answers from your course material only</span>' +
            '<button type="button" class="tutor-close" aria-label="Close chat">✕</button>' +
            '</div>' +
            '<div class="tutor-log" id="tutorLog"></div>' +
            '<div class="tutor-chips" id="tutorChips"></div>' +
            '<form class="tutor-form" id="tutorForm">' +
            '<input type="text" id="tutorInput" placeholder="Ask about this lesson…" ' +
            'autocomplete="off" maxlength="500">' +
            '<button type="submit" class="btn btn-primary">Send</button>' +
            '</form>';

        document.body.appendChild(fab);
        document.body.appendChild(panel);

        logEl = document.getElementById("tutorLog");
        inputEl = document.getElementById("tutorInput");
        var chipsEl = document.getElementById("tutorChips");
        chipsEl.appendChild(chip("Quiz me", "Quiz me"));
        chipsEl.appendChild(chip("Explain this lesson", "Explain this lesson"));
        chipsEl.appendChild(chip("Walk me through the flowchart", "Walk me through the flowchart"));
        chipsEl.appendChild(chip("Give me a hint", "Give me a hint"));

        fab.addEventListener("click", function (e) {
            e.stopPropagation();
            if (isOpen()) closePanel();
            else openPanel();
        });
        panel.querySelector(".tutor-close").addEventListener("click", function () {
            closePanel();
        });
        /* Close when the user clicks anywhere outside the chat box
           (and not on the "Ask tutor" button that opens it). */
        document.addEventListener("pointerdown", function (e) {
            if (!isOpen()) return;
            if (panel.contains(e.target)) return;
            if (fab.contains(e.target)) return;
            closePanel();
        });
        /* Escape closes it too. */
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && isOpen()) closePanel();
        });
        /* Any use of the chat restarts the idle timer. */
        ["pointerdown", "keydown", "input"].forEach(function (evt) {
            panel.addEventListener(evt, pokeIdle);
        });
        document.getElementById("tutorForm").addEventListener("submit", function (e) {
            e.preventDefault();
            ask(inputEl.value);
        });
    }

    window.LearnHubTutor = {
        init: function (opts) {
            opts = opts || {};
            state.courseId = opts.courseId || null;
            state.lessonId = opts.lessonId || null;
            state.taskId = opts.taskId || null;
            state.context = {};
            build();
        },
        // Call when the learner opens a task, so "give me a hint" knows
        // which task they mean.
        setTask: function (taskId) { state.taskId = taskId || null; },
        setLesson: function (lessonId, courseId) {
            state.lessonId = lessonId || null;
            if (courseId) state.courseId = courseId;
            state.context = {};
        },
    };
})();
