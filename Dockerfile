FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend and frontend
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# SQLite data directory (ephemeral on free tier)
RUN mkdir -p /app/backend/data

ENV RYDE_DB_PATH=/app/backend/data/demo.sqlite
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
