#!/bin/bash
# Local testing script using venv

echo "=== LOCAL TESTING: Using venv ==="

# Activate venv and run
source venv_local/bin/activate
echo "Running: $@"
python3 perf.py "$@"
