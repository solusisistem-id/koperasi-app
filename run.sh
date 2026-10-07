#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=== Inisialisasi & Seeding Database Koperasi Core ==="
python3 scripts/seed_data.py
python3 scripts/generate_templates.py

echo "=== Menjalankan Koperasi Core Web Server di http://0.0.0.0:8000 ==="
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
