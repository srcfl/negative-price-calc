# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies for pandas and other packages
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
RUN pip install uv

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies
RUN uv sync --frozen

# Copy application code
COPY . .

# Create data directory for SQLite database, cache and results
RUN mkdir -p data/cache data/results

# Expose port (Railway sets PORT env var)
EXPOSE 8080

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_ENV=production

# Default port (Railway overrides with PORT env var)
ENV PORT=8080

# Run with gunicorn for production (uses $PORT from environment)
CMD uv run gunicorn --bind "0.0.0.0:$PORT" --workers 2 --timeout 300 app:app