# Copy requirements first for better cache
COPY requirements.txt .

# Install dependencies directly with pip for better cross-platform compatibility
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Stage 2: Production Stage
FROM --platform=$TARGETPLATFORM python:3.11-slim

WORKDIR /app

# Copy installed dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy the application code
COPY --from=builder /app .

# Expose port
EXPOSE 5002

# Run the application
CMD ["python", "app.py"]
