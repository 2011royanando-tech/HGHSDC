#!/bin/bash
cd "$(dirname "$0")"
export PYTHONPATH=.
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
