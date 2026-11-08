#!/usr/bin/env python3
"""
LearnHub LMS - database seed script.

Creates the SQLite database (from schema.sql) and fills it with
12 realistic courses, each with 6 lessons.

Run:  python3 backend/seed.py
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "learnhub.db"))

ANNOUNCEMENTS = [
    ("Welcome to the new LearnHub dashboard",
     "Your learning is now in one place: XP, streaks, badges, your leaderboard rank and everything you are working on. Sign in and open your Dashboard to see your progress."),
    ("New: Python, C, DSA, Java & SQL learning paths are live",
     "Follow a guided path instead of picking courses one by one. Open Learning Paths from the menu and start with the path that matches your goal."),
    ("Certificates are now verifiable - share your LH- code with recruiters",
     "Every certificate has a unique LH- code. Anyone can verify it at certificate.html - share the code on your resume or LinkedIn."),
]


def _seed_announcements(conn):
    """Insert the 3 starter announcements once (idempotent)."""
    n = conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
    if n == 0:
        for title, body in ANNOUNCEMENTS:
            conn.execute("INSERT INTO announcements (title, body) VALUES (?, ?)",
                         (title, body))
        conn.commit()


COURSES = [
    {
        "title": "Complete Web Development Bootcamp",
        "description": "Learn HTML, CSS, JavaScript and modern web development from beginner to advanced level.",
        "category": "Development", "price": 999, "instructor": "John Smith",
        "duration_hours": 18, "level": "Beginner", "image_url": "assets/images/course1.svg",
        "lessons": [
            ("HTML Foundations", 45), ("CSS Styling & Layouts", 60),
            ("Responsive Design with Flexbox & Grid", 55), ("JavaScript Basics", 70),
            ("DOM Manipulation & Events", 50), ("Build a Portfolio Project", 90),
        ],
    },
    {
        "title": "JavaScript: From Beginner to Advanced",
        "description": "Master JavaScript fundamentals, DOM manipulation, events, APIs and modern JavaScript.",
        "category": "Programming", "price": 799, "instructor": "Sarah Williams",
        "duration_hours": 14, "level": "Intermediate", "image_url": "assets/images/course2.svg",
        "lessons": [
            ("Variables, Types & Operators", 40), ("Functions & Scope", 55),
            ("Arrays & Objects in Depth", 50), ("Async JavaScript & Fetch API", 65),
            ("ES6+ Modern Features", 45), ("Mini Project: Weather App", 80),
        ],
    },
    {
        "title": "Python Programming Masterclass",
        "description": "Go from zero to hero in Python - data structures, OOP, file handling and real projects.",
        "category": "Programming", "price": 899, "instructor": "Michael Brown",
        "duration_hours": 22, "level": "Beginner", "image_url": "assets/images/course3.svg",
        "lessons": [
            ("Python Setup & First Program", 30), ("Data Types & Control Flow", 55),
            ("Functions & Modules", 50), ("Object-Oriented Programming", 75),
            ("File Handling & Exceptions", 45), ("Capstone: Automation Script", 85),
        ],
    },
    {
        "title": "Machine Learning with Python",
        "description": "Practical ML with scikit-learn - regression, classification, clustering and model evaluation.",
        "category": "AI & ML", "price": 1499, "instructor": "Priya Sharma",
        "duration_hours": 20, "level": "Intermediate", "image_url": "assets/images/course4.svg",
        "lessons": [
            ("ML Concepts & Workflow", 45), ("Data Preprocessing with Pandas", 60),
            ("Regression Models", 55), ("Classification & Evaluation", 65),
            ("Clustering & Dimensionality Reduction", 50),
            ("Model Deployment Basics", 55),
        ],
    },
    {
        "title": "Deep Learning & Neural Networks",
        "description": "Build neural networks from scratch and with Keras - CNNs, RNNs and practical projects.",
        "category": "AI & ML", "price": 1799, "instructor": "Arjun Reddy",
        "duration_hours": 24, "level": "Advanced", "image_url": "assets/images/course5.svg",
        "lessons": [
            ("Neural Network Fundamentals", 60), ("Training & Backpropagation", 70),
            ("CNNs for Image Classification", 75), ("RNNs & Sequence Models", 65),
            ("Project: Image Classifier", 90),
            ("Transfer Learning & Fine-Tuning", 70),
        ],
    },
    {
        "title": "Data Science with SQL & Python",
        "description": "Analyse real datasets with SQL, Pandas and visualisation to drive business insights.",
        "category": "Data Science", "price": 1199, "instructor": "Kavya Nair",
        "duration_hours": 16, "level": "Intermediate", "image_url": "assets/images/course6.svg",
        "lessons": [
            ("SQL Joins & Aggregations", 55), ("Pandas DataFrames", 60),
            ("Data Cleaning Techniques", 50), ("Visualisation with Matplotlib", 45),
            ("End-to-End Analysis Project", 85), ("A/B Testing Fundamentals", 50),
        ],
    },
    {
        "title": "UI/UX Design Fundamentals",
        "description": "Design beautiful, user-friendly interfaces - wireframing, typography, colour and Figma basics.",
        "category": "Design", "price": 899, "instructor": "Riya Kapoor",
        "duration_hours": 12, "level": "Beginner", "image_url": "assets/images/course1.svg",
        "lessons": [
            ("Design Thinking Process", 40), ("Wireframing & Prototyping", 55),
            ("Typography & Colour Theory", 45), ("Figma Hands-On", 60),
            ("Portfolio Project", 75), ("Design Systems & Component Libraries", 55),
        ],
    },
    {
        "title": "React - Build Modern Web Apps",
        "description": "Master React hooks, routing, state management and deploy production-ready apps.",
        "category": "Development", "price": 1299, "instructor": "Vikram Singh",
        "duration_hours": 15, "level": "Intermediate", "image_url": "assets/images/course2.svg",
        "lessons": [
            ("Components & JSX", 50), ("Hooks: useState & useEffect", 60),
            ("React Router", 45), ("State Management Basics", 55),
            ("Deploy a React App", 40), ("Performance Optimisation in React", 50),
        ],
    },
    {
        "title": "Digital Marketing Masterclass",
        "description": "SEO, social media, email marketing and analytics - grow any business online.",
        "category": "Marketing", "price": 699, "instructor": "Neha Gupta",
        "duration_hours": 10, "level": "Beginner", "image_url": "assets/images/course3.svg",
        "lessons": [
            ("Marketing Fundamentals", 35), ("SEO Essentials", 50),
            ("Social Media Strategy", 45), ("Email Campaigns", 40),
            ("Google Analytics Basics", 45), ("Content Marketing & Copywriting", 45),
        ],
    },
    {
        "title": "Django Full-Stack Web Development",
        "description": "Build complete web apps with Django - models, auth, REST APIs and deployment.",
        "category": "Development", "price": 1399, "instructor": "Rahul Verma",
        "duration_hours": 19, "level": "Intermediate", "image_url": "assets/images/course4.svg",
        "lessons": [
            ("Django Setup & MTV Pattern", 45), ("Models & ORM", 60),
            ("Views, Templates & Forms", 65), ("User Authentication", 50),
            ("REST APIs with DRF", 70), ("Deploy to Production", 55),
        ],
    },
    {
        "title": "TypeScript: Static Typing for JavaScript",
        "description": "Add static types to your JavaScript - interfaces, generics, type-safe DOM code and Node.js projects.",
        "category": "Development", "price": 1099, "instructor": "Ananya Iyer",
        "duration_hours": 13, "level": "Intermediate", "image_url": "assets/images/course5.svg",
        "lessons": [
            ("Why TypeScript?", 35), ("Types & Interfaces", 55),
            ("Functions & Generics", 60), ("Type-Safe DOM Handling", 50),
            ("TypeScript with Node.js", 55), ("Project: Typed Task Manager", 75),
        ],
    },
    {
        "title": "Git & GitHub: Version Control Mastery",
        "description": "Master Git from first commit to open-source collaboration - branching, rebasing, pull requests and team workflows.",
        "category": "Development", "price": 599, "instructor": "Kiran Patel",
        "duration_hours": 8, "level": "Beginner", "image_url": "assets/images/course6.svg",
        "lessons": [
            ("Git Setup & First Commit", 30), ("Branching & Merging", 50),
            ("Resolving Merge Conflicts", 40), ("GitHub: Remotes & Pull Requests", 55),
            ("Stashing, Rebasing & Undo", 45), ("Capstone: Open-Source Contribution", 60),
        ],
    },
]


def main():
    fresh = not os.path.exists(DB_PATH)
    with open(os.path.join(BASE_DIR, "schema.sql")) as f:
        schema = f.read()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(schema)

    existing = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    if existing:
        print(f"[seed] database already has {existing} course(s) - skipping base seed.")
        _seed_announcements(conn)
        conn.close()
        _load_learning_content()
        return

    total_lessons = 0
    for c in COURSES:
        cur = conn.execute(
            """INSERT INTO courses (title, description, category, price, instructor,
                                    duration_hours, level, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (c["title"], c["description"], c["category"], c["price"], c["instructor"],
             c["duration_hours"], c["level"], c["image_url"]),
        )
        course_id = cur.lastrowid
        for idx, (title, mins) in enumerate(c["lessons"]):
            conn.execute(
                """INSERT INTO lessons (course_id, title, content_url, duration_minutes, order_index)
                   VALUES (?, ?, ?, ?, ?)""",
                (course_id, title, f"/courses/{course_id}/lessons/{idx + 1}", mins, idx + 1),
            )
            total_lessons += 1

    conn.commit()
    # Mark the first lesson (lowest id) of each course as a free preview.
    # Idempotent - only touches courses with no preview lesson yet.
    conn.execute(
        """UPDATE lessons SET is_preview = 1
           WHERE is_preview = 0 AND id IN (
               SELECT MIN(l2.id) FROM lessons l2
               WHERE NOT EXISTS (
                   SELECT 1 FROM lessons l3
                   WHERE l3.course_id = l2.course_id AND l3.is_preview = 1
               )
               GROUP BY l2.course_id
           )""")
    conn.commit()
    _seed_announcements(conn)
    conn.close()
    print(f"[seed] done: {len(COURSES)} courses, {total_lessons} lessons -> {DB_PATH} "
          f"({'new db' if fresh else 'existing db'})")
    _load_learning_content()


def _load_learning_content():
    """Load real lesson content (backend/content/*.json) if present.

    Runs after the base seed, and also when the base seed is skipped
    (existing DB) - so redeploying with new content files updates the
    live database without wiping enrolments or progress.
    """
    content_dir = os.path.join(BASE_DIR, "content")
    if not os.path.isdir(content_dir) or not os.listdir(content_dir):
        print("[seed] no learning content found - skipping.")
        return
    try:
        import seed_content
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(
            open(os.path.join(BASE_DIR, "schema.sql")).read())
        totals = seed_content.load_content(conn)
        conn.close()
        print(f"[seed] learning content: {totals['courses']} courses, "
              f"{totals['lessons']} lessons, {totals['mcqs']} MCQs, "
              f"{totals['tasks']} tasks, {totals['flowcharts']} flowcharts, "
              f"{totals['videos']} videos")
    except Exception as e:  # content is additive - never block the base seed
        print(f"[seed] learning content failed (base data is intact): {e!r}")


if __name__ == "__main__":
    main()
