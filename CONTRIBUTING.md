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
- `poetry run python exporter.py`
- Metrics available on http://127.0.0.1:${ANKER_EXPORTER_PORT:-9123}/metrics

Tests:
- `poetry run python -m unittest -v`

Docker (dev):
- `docker build -t anker-solix-prom-exporter .`
- `docker run --rm -p 9123:9123 --env-file .env anker-solix-prom-exporter`