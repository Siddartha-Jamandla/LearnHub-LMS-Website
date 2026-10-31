#!/usr/bin/env python3
"""
LearnHub LMS - database seed script.

Creates the SQLite database (from schema.sql) and fills it with
10 realistic courses, each with 4-6 lessons.

Run:  python3 backend/seed.py
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "learnhub.db"))

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
            ("End-to-End Analysis Project", 85),
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
            ("Portfolio Project", 75),
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
            ("Deploy a React App", 40),
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
            ("Google Analytics Basics", 45),
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
]


def main():
    fresh = not os.path.exists(DB_PATH)
    with open(os.path.join(BASE_DIR, "schema.sql")) as f:
        schema = f.read()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(schema)

    existing = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    if existing:
        print(f"[seed] database already has {existing} course(s) - skipping seed.")
        conn.close()
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
    conn.close()
    print(f"[seed] done: {len(COURSES)} courses, {total_lessons} lessons -> {DB_PATH} "
          f"({'new db' if fresh else 'existing db'})")


if __name__ == "__main__":
    main()
