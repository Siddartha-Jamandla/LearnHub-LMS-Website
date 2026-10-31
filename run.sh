#!/usr/bin/env bash
# LearnHub LMS - one-command local dev setup (macOS / Linux)
set -e
cd "$(dirname "$0")"

echo "==> Seeding database..."
python3 backend/seed.py

echo "==> Starting LearnHub backend on http://localhost:8000"
python3 backend/app.py
