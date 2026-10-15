FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies and the app package (dev tools like pytest and locust are not installed).
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# Migrations run from here (`alembic upgrade head`).
COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
# $PORT is set by hosts like Render; WEB_CONCURRENCY (uvicorn's own convention) sets workers.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
