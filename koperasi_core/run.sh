#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Ensure templates exist
python3 scripts/generate_templates.py

# Optional development seed only if DEV_SEED=true and APP_ENV=development
if [ "${DEV_SEED:-false}" = "true" ] && [ "${APP_ENV:-development}" = "development" ]; then
    echo "=== Running Development Seed Data ==="
    python3 scripts/seed_data.py
fi

echo "=== Menjalankan Koperasi Core Web Server di http://0.0.0.0:${PORT:-8000} ==="
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
