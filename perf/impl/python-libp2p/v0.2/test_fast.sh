#!/bin/bash
# Fast testing script - no Docker rebuild needed!

echo "=== FAST TESTING: Copying script and running ==="

# Copy the current perf.py to the running container
docker cp perf.py python-perf-test:/usr/src/myapp/perf.py

# Run the test directly in the container
echo "Running: $@"
docker exec -e LIBP2P_DEBUG python-perf-test python3 perf.py "$@"
