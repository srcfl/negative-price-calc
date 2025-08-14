# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies for pandas and other packages
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
RUN pip install uv

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies
RUN uv sync --frozen

# Copy application code
COPY . .

# Create data directory for SQLite database and cache
RUN mkdir -p data/cache

# Expose port 8080
EXPOSE 8080

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_ENV=production

# Run the web application
CMD ["uv", "run", "python", "run_webapp.py"]