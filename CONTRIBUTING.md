## CONTRIBUTING

If you want to hack on the exporter locally instead of using the container:

Prerequisites:
- Python 3.13+
- Poetry for dependency management: https://python-poetry.org/

Setup:
- Clone the repo
- `cp .env.dist .env` and fill in credentials
- `poetry install`

Run:
- `poetry run python -m anker_solix_prom_exporter`
- Metrics available on <http://127.0.0.1:9123/metrics> (if you haven't changed the `ANKER_EXPORTER_PORT` variable!)

Tests:
- `poetry run pytest`

Before submitting a PR, please run `poetry run ruff check` and `poetry run ruff format` to format the code.

Docker (dev):
- `docker build -t anker-solix-prom-exporter .`
- `docker run --rm -p 9123:9123 --env-file .env anker-solix-prom-exporter`
