FROM ghcr.io/astral-sh/uv:0.12.21 AS uv
FROM python:3.13.16-slim-trixie

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev && useradd --uid 10001 --no-create-home app
COPY backend/ ./
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
