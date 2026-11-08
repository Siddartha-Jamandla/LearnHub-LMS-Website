# LearnHub learning content — spec for `backend/content/*.json`

One JSON file per course. The seed loader (`backend/seed_content.py`)
reads these files and upserts courses, lessons, lesson content, quizzes
and tasks into SQLite. Keep this spec in sync with the loader.

## File shape

```json
{
  "course": {
    "match_title": "Python Programming Masterclass",
    "title": "Python Programming Masterclass",
    "description": "One or two sentences.",
    "category": "Programming",
    "price": 899,
    "instructor": "Michael Brown",
    "duration_hours": 22,
    "level": "Beginner",
    "image_url": "assets/images/course3.svg"
  },
  "lessons": [
    {
      "title": "Lesson title",
      "duration_minutes": 45,
      "is_preview": 0,
      "body": "<h3>...</h3><p>...</p><pre><code>...</code></pre><ul><li>Key point</li></ul>",
      "flowchart": {
        "title": "How an if-else decides",
        "nodes": [
          {"id": "n1", "label": "Start", "kind": "start"},
          {"id": "n2", "label": "Read marks", "kind": "input"},
          {"id": "n3", "label": "marks >= 40?", "kind": "decision"},
          {"id": "n4", "label": "Print Pass", "kind": "process"},
          {"id": "n5", "label": "Print Fail", "kind": "process"},
          {"id": "n6", "label": "End", "kind": "end"}
        ],
        "edges": [
          {"from": "n1", "to": "n2"},
          {"from": "n2", "to": "n3"},
          {"from": "n3", "to": "n4", "label": "Yes"},
          {"from": "n3", "to": "n5", "label": "No"},
          {"from": "n4", "to": "n6"},
          {"from": "n5", "to": "n6"}
        ]
      },
      "video": {"id": "rfscVS0vtbw", "title": "Learn Python - Full Course for Beginners [Tutorial]"},
      "mcqs": [
        {"q": "Question?", "options": ["a", "b", "c", "d"], "answer": 0,
         "why": "Short explanation of WHY the answer is correct."}
      ],
      "tasks": [
        {"type": "predict", "title": "Predict the output",
         "prompt": "What does this print?",
         "code": "print(2 + 3 * 4)",
         "expected": "14",
         "answer": "Multiplication runs before addition, so 3*4=12, +2=14.",
         "hint": "Remember operator precedence: * before +."}
      ]
    }
  ]
}
```

## Rules

- `match_title`: exact title of the EXISTING course to extend (Python only).
  For new courses use `null` — the course is inserted by `title`.
- `body`: HTML fragment only (no `<html>`, no `<script>`). Must be genuinely
  teachable: concept in simple steps, at least one correct code example,
  a "Key points" `<ul>` at the end. Code must be valid in the lesson's
  language — double-check syntax before writing.
- `flowchart`: required for key lessons (at least 6 per course). Node kinds:
  `start`, `end`, `process`, `decision`, `input`, `output`. Decision nodes
  MUST have Yes/No labelled edges. 4–10 nodes. The flowchart must match
  the lesson's actual logic. `null` when the lesson has no flowchart.
- `video`: ONLY the verified YouTube IDs in `VERIFIED_VIDEOS.md`.
  No `start` offsets (timestamps would be guesses). Title must be the
  exact verified title.
- `mcqs`: at least 5 per lesson. Exactly 4 options, exactly one correct
  (`answer` = 0–3 index), `why` explains WHY. Every answer must be
  factually correct.
- `tasks`: at least 3 per lesson, mixing types `predict`, `fix`, `fill`,
  `trace`. Type `project` only in the course's final/capstone lesson
  (exactly 1 mini-project per course). Fields:
  - `predict`: `code` + `expected` = exact program output.
  - `fix`: `code` = buggy code, `expected` = corrected code,
    `answer` = what the bug was and why the fix works.
  - `fill`: `code` contains `___` blanks, `expected` = the missing code.
  - `trace`: `code` + `expected` = step-by-step trace (variable values),
    `answer` = walk-through using the lesson flowchart.
  - `project`: `prompt` = what to build, `expected` = deliverable
    checklist, `answer` = approach hints. `code` may be "".
- `hint`: a nudge, never the full answer.
- No placeholders, no lorem ipsum, no invented facts about real people.
- Validate before finishing: `python3 -m json.tool backend/content/<file>.json`
  must succeed, and report lesson / MCQ / task / flowchart counts.

## Courses

| file | course | lessons |
|------|--------|---------|
| python.json | Python Programming Masterclass (extend existing, keep its 6 lesson titles/order, add 4 more) | 10 |
| c.json | C Programming from Zero to Hero (new) | 10 |
| dsa.json | Data Structures & Algorithms (new) | 10 |
| java.json | Java Programming Masterclass (new) | 8 |
| sql.json | SQL Essentials: Queries to Databases (new) | 8 |
