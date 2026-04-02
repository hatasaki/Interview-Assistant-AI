#!/bin/bash
set -e

# Install Python dependencies
pip install --no-cache-dir -r requirements.txt

# Start the application
exec uvicorn app:app --host 0.0.0.0 --port 8000
