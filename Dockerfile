# Stage 1: Build Stage
FROM --platform=$BUILDPLATFORM python:3.11-slim AS builder

WORKDIR /app

# Copy requirements first for better cache
COPY requirements.txt .

# Install build dependencies and Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && pip install --user --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/*

# Copy the application code
COPY . .

# Stage 2: Production Stage
FROM --platform=$TARGETPLATFORM python:3.11-alpine

WORKDIR /app

# Install required runtime packages
RUN apk add --no-cache libstdc++ libffi

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
