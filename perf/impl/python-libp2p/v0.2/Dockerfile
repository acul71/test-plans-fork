FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /usr/src/myapp

# Copy project files
COPY pyproject.toml ./
COPY perf.py ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Set the default command
CMD ["python3", "perf.py"]
