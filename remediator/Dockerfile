FROM python:3.11-slim

# Install curl for the healthcheck and clean up apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements file first for layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source code
COPY . .

# Create a non-root user 'neuroops' (uid 1001)
RUN useradd -u 1001 -m neuroops && \
    chown -R neuroops:neuroops /app

# Set the active user to 'neuroops'
USER neuroops

EXPOSE 8003

# Healthcheck configuration using curl
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8003/health || exit 1

# Command to run the application
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8003"]
