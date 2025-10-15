# Stage 1: Build Stage
FROM --platform=$TARGETPLATFORM python:3.11-alpine AS builder

WORKDIR /app

# Copy requirements first for better cache
COPY requirements.txt .

# Install build dependencies and Python packages
RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    rust \
    build-base \
    && pip install --user --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Stage 2: Production Stage
FROM --platform=$TARGETPLATFORM python:3.11-alpine

WORKDIR /app

# Install required runtime packages for cryptography and other dependencies
RUN apk add --no-cache \
    libstdc++ \
    libffi \
    libc6-compat \
    libgcc \
    linux-headers \
    build-base \
    python3-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    rust

# Copy installed dependencies from builder
COPY --from=builder /root/.local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy only necessary application files
COPY --from=builder /app/app.py /app/
COPY --from=builder /app/static /app/static
COPY --from=builder /app/templates /app/templates

# Create non-root user
RUN adduser -D appuser \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Create directory for SQLite database with correct permissions
RUN mkdir -p /app/data
VOLUME /app/data

# Environment variables
ENV AZURE_PANEL_PASSWORD=You22kme#12345 \
    PORT=5002 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose port
EXPOSE 5002

# Use gunicorn for better performance
CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:5002", "--workers", "2", "--threads", "2", "--worker-class", "gthread", "app:app"]
