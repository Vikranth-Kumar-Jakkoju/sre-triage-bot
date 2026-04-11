FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    "openenv-core>=0.2.0" \
    "openai>=1.0.0" \
    "fastapi>=0.100.0" \
    "uvicorn[standard]>=0.20.0" \
    "pydantic>=2.0.0" \
    "requests>=2.28.0"

# Copy all project files into /app
COPY . .

# Make sure Python can find the root-level modules (models.py etc.)
ENV PYTHONPATH=/app

EXPOSE 7860

# Run from /app so both `server/` package and `models.py` are importable
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860", "--log-level", "info"]
