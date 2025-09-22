FROM python:3.11-slim

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps (only if you truly need gcc/g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Add your code
COPY src/ ./src/


# (Optional) Copy env/creds only if they actually exist in build context.
# If they might be missing, comment these out to avoid COPY wildcards failing the build.
COPY .env* ./
COPY gcp-config.json* ./
COPY firebase-config.json* ./

# Ensure Python can import 'src' as a top-level package
ENV PYTHONPATH="/app:/app/src"

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Informational only
EXPOSE 8000

# Start server: bind to 0.0.0.0 and the Cloud Run PORT (fallback 8000 for local)
CMD ["sh", "-c", "exec python -m uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

