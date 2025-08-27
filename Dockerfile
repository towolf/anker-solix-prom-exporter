# syntax=docker/dockerfile:1
# Builder stage: install Poetry with pipx and resolve dependencies into in-project venv
FROM python:3.13-alpine AS builder

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache \
    PATH=/root/.local/bin:$PATH

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN <<EOF
    python -m pip install --no-cache-dir --root-user-action pipx
    python -m pipx install poetry
    poetry install --only main --no-interaction --no-ansi --no-root
EOF

# Final stage: copy only runtime files and the virtualenv
FROM python:3.13-alpine AS runtime

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app /app
COPY ./src/anker_solix_prom_exporter /anker_solix_prom_exporter

EXPOSE 9123

ENTRYPOINT ["python", "-m", "anker_solix_prom_exporter.exporter"]
