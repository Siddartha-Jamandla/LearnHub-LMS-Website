#!/usr/bin/env python3
"""
LearnHub LMS - learning-content seed loader.

Reads backend/content/*.json (one file per course: real lesson
explanations, flowcharts, verified YouTube videos, MCQs and practice
tasks) and loads them into SQLite.

Idempotent - safe to run on every deploy:
- courses are matched by match_title (existing) or title (new);
- lessons are matched by (course_id, order_index) so existing lesson
  ids - and therefore learner progress - are preserved;
- lesson_content is upserted by lesson_id;
- quizzes and tasks for the loaded lessons are replaced wholesale.

Run:  python3 backend/seed_content.py
  or: python3 backend/seed.py        (calls this loader at the end)
"""

import glob
import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(BASE_DIR, "content")
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "learnhub.db"))


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_content(conn):
    """Load every backend/content/*.json file into an open connection."""
    files = sorted(glob.glob(os.path.join(CONTENT_DIR, "*.json")))
    totals = {"courses": 0, "lessons": 0, "mcqs": 0, "tasks": 0,
              "flowcharts": 0, "videos": 0}
    for path in files:
        data = _load_json(path)
        course = data["course"]
        lessons = data["lessons"]

        # --- course: match existing by match_title, else by title ---
        match = course.get("match_title") or course["title"]
        row = conn.execute(
            "SELECT id FROM courses WHERE title = ?", (match,)).fetchone()
        if row:
            course_id = row[0]
            conn.execute(
                """UPDATE courses SET title = ?, description = ?,
                       category = ?, price = ?, instructor = ?,
                       duration_hours = ?, level = ?, image_url = ?
                   WHERE id = ?""",
                (course["title"], course["description"], course["category"],
                 course["price"], course["instructor"],
                 course["duration_hours"], course["level"],
                 course.get("image_url"), course_id))
        else:
            cur = conn.execute(
                """INSERT INTO courses (title, description, category, price,
                                        instructor, duration_hours, level,
                                        image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (course["title"], course["description"], course["category"],
                 course["price"], course["instructor"],
                 course["duration_hours"], course["level"],
                 course.get("image_url")))
            course_id = cur.lastrowid
        totals["courses"] += 1

        # --- lessons, matched by (course_id, order_index) ---
        for idx, lesson in enumerate(lessons, start=1):
            existing = conn.execute(
                "SELECT id FROM lessons WHERE course_id = ? AND order_index = ?",
                (course_id, idx)).fetchone()
            if existing:
                lesson_id = existing[0]
                conn.execute(
                    """UPDATE lessons SET title = ?, duration_minutes = ?,
                           is_preview = ? WHERE id = ?""",
                    (lesson["title"], lesson["duration_minutes"],
                     1 if lesson.get("is_preview") else 0, lesson_id))
            else:
                cur = conn.execute(
                    """INSERT INTO lessons (course_id, title, content_url,
                                            duration_minutes, order_index,
                                            is_preview)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (course_id, lesson["title"],
                     f"/courses/{course_id}/lessons/{idx}",
                     lesson["duration_minutes"], idx,
                     1 if lesson.get("is_preview") else 0))
                lesson_id = cur.lastrowid
            totals["lessons"] += 1

            # --- rich content ---
            fc = lesson.get("flowchart")
            video = lesson.get("video") or {}
            conn.execute(
                """INSERT INTO lesson_content
                       (lesson_id, body, flowchart_title, flowchart_json,
                        video_id, video_title)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(lesson_id) DO UPDATE SET
                       body = excluded.body,
                       flowchart_title = excluded.flowchart_title,
                       flowchart_json = excluded.flowchart_json,
                       video_id = excluded.video_id,
                       video_title = excluded.video_title""",
                (lesson_id, lesson.get("body", ""),
                 fc.get("title") if fc else None,
                 json.dumps(fc) if fc else None,
                 video.get("id"), video.get("title")))
            if fc:
                totals["flowcharts"] += 1
            if video.get("id"):
                totals["videos"] += 1

            # --- quizzes: replace wholesale for this lesson ---
            conn.execute("DELETE FROM quizzes WHERE lesson_id = ?", (lesson_id,))
            for q_idx, q in enumerate(lesson.get("mcqs", [])):
                conn.execute(
                    """INSERT INTO quizzes
                           (lesson_id, question, options_json, answer_index,
                            explanation, order_index)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (lesson_id, q["q"], json.dumps(q["options"]),
                     int(q["answer"]), q.get("why", ""), q_idx + 1))
                totals["mcqs"] += 1

            # --- tasks: replace wholesale for this lesson ---
            conn.execute("DELETE FROM tasks WHERE lesson_id = ?", (lesson_id,))
            for t_idx, t in enumerate(lesson.get("tasks", [])):
                conn.execute(
                    """INSERT INTO tasks
                           (lesson_id, type, title, prompt, code, expected,
                            answer, hint, order_index)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (lesson_id, t["type"], t["title"], t["prompt"],
                     t.get("code", ""), t.get("expected", ""),
                     t.get("answer", ""), t.get("hint", ""), t_idx + 1))
                totals["tasks"] += 1

    conn.commit()
    return totals


def main():
    with open(os.path.join(BASE_DIR, "schema.sql")) as f:
        schema = f.read()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(schema)
    totals = load_content(conn)
    conn.close()
    print(f"[seed-content] done: {totals['courses']} courses, "
          f"{totals['lessons']} lessons, {totals['mcqs']} MCQs, "
          f"{totals['tasks']} tasks, {totals['flowcharts']} flowcharts, "
          f"{totals['videos']} videos -> {DB_PATH}")


if __name__ == "__main__":
    main()
