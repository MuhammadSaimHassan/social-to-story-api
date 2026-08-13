# --- Builder stage: install dependencies into a virtual environment ---
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps only where needed (kept minimal since our deps are pure-Python/wheel-friendly).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# --- Runtime stage: slim image with only the venv + app code ---
FROM python:3.11-slim AS runtime

# Create a non-root user to run the app.
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Bring in the pre-built virtual environment from the builder stage.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy application code.
COPY app ./app
COPY frontend ./frontend

# .env is intentionally NOT copied into the image — configuration should be
# injected at runtime via environment variables or a mounted/passed .env file.

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
