FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Stage the tracked data/models seeds outside the /app/data volume mount path
# so they survive Fly's persistent volume shadowing /app/data at boot.
# src/seed_models.py copies them into data/models on startup when absent.
RUN mkdir -p /app/seed && cp -r /app/data/models /app/seed/models

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --limit-concurrency ${LIMIT_CONCURRENCY:-24}"]
