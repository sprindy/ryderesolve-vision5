#!/usr/bin/env bash
# RydeResolve — Cloud Studio one-click deploy
# Paste this into the Cloud Studio terminal after creating a workspace from GitHub.
set -euo pipefail

echo "=== RydeResolve Cloud Studio Deploy ==="

# Install dependencies
echo ">> Installing Python dependencies..."
pip install -r backend/requirements.txt

# Start the backend on 0.0.0.0:8080 (Cloud Studio's exposed port)
echo ">> Starting uvicorn on 0.0.0.0:8080..."
echo ">> Look for the Ports panel at the bottom of the IDE to get your public URL."
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8080
