FROM python:3.11-slim

LABEL maintainer="devops-team"
LABEL description="Sentiment Analysis REST API"

WORKDIR /app

# Install curl: serve sia per il HEALTHCHECK qui sotto, sia per gli smoke
# test che la pipeline Jenkins esegue dentro al container via `docker exec`.
# L'immagine python:3.11-slim è minimale e non include curl di default.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and model
COPY main.py .
COPY sentimentanalysismodel.pkl .

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
