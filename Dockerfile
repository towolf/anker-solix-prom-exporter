# syntax=docker/dockerfile:1

# Builder stage: install Poetry with pipx and resolve dependencies into in-project venv
FROM python:3.13-alpine AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/root/.local/bin:$PATH

WORKDIR /app

# Install pipx and Poetry
RUN python -m pip install --no-cache-dir pipx \
    && python -m pipx install poetry

# Copy dependency definitions and install only main dependencies
COPY pyproject.toml ./
# If you have a poetry.lock, uncomment the next line for better caching
COPY poetry.lock ./
RUN poetry config virtualenvs.in-project true \
    && poetry install --only main --no-interaction --no-ansi --no-root

# Final stage: copy only runtime files and the virtualenv
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv

# Copy the prepared virtualenv from builder
COPY --from=builder /app/.venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
# Copy only what is needed at runtime
#COPY api ./api
COPY common.py exporter.py ./

# Prometheus exporter default port
EXPOSE 9123

# Run exporter.py as entrypoint
ENTRYPOINT ["python", "-u", "exporter.py"]
