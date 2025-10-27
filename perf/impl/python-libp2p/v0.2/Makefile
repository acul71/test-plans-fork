# Python libp2p perf implementation Makefile

DOCKER_IMAGE := python-libp2p-perf:latest

all: perf

perf: Dockerfile perf.py pyproject.toml
	docker build -t $(DOCKER_IMAGE) .
	echo '#!/bin/bash' > perf
	echo 'docker run --rm -e LIBP2P_DEBUG -v "$$(dirname $$0):/usr/src/myapp" -w /usr/src/myapp $(DOCKER_IMAGE) python3 perf.py "$$@"' >> perf
	chmod +x perf

clean:
	rm -f perf
	docker rmi $(DOCKER_IMAGE) 2>/dev/null || true

.PHONY: all clean