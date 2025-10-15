# Stage 1: Build Stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies for Python packages with C extensions
# This provides gcc and Python development headers for compilation.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy only requirements to cache layer
COPY requirements.txt .

# Install dependencies using uv
RUN uv pip install -r requirements.txt --system --no-cache

# Copy the rest of the application code
COPY . .

# Stage 2: Production Stage
FROM python:3.11-slim

WORKDIR /app

# Copy installed dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Copy the application code
COPY --from=builder /app .

# Expose port (if your Flask app listens on a specific port, e.g., 5002)
EXPOSE 5002

# Run the application
CMD ["python", "app.py"]
