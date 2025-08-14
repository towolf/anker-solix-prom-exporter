# Anker Solix Prometheus Exporter

A lightweight Prometheus exporter that authenticates to the Anker Solix Cloud and exposes device and energy metrics over
HTTP for scraping by Prometheus.

This project builds on top of the
excellent [Anker Solix API client library by thomluther](https://github.com/thomluther/anker-solix-api) (v3.1.1 in this
project)

## Usage

The exporter reads configuration from environment variables and serves metrics at `/metrics`. The easiest way to run it
is via Docker or Docker Compose.

### 1) Configure environment variables

Copy the template and fill in your Anker account credentials and country code.

- Using a local .env file (recommended):
    - Copy [.env.dist](./.env.dist) to .env
    - Fill in the values as described below

Environment variables (see .env.dist):

- `ANKERUSER`: Your Anker account email
- `ANKERPASSWORD`: Your Anker account password
- `ANKERCOUNTRY`: Your two-letter country code, e.g. `DE` for Germany
- `ANKER_EXPORTER_PORT`: (optional) Port to serve the metrics endpoint, default 9123
- `ANKER_SCRAPE_INTERVAL`: (optional) Polling interval (seconds) for refreshing metrics, default 30

Note: The exporter uses [python-dotenv](https://pypi.org/project/python-dotenv/) to automatically load a .env file when
present. Credentials from the environment are preferred!

### 2) Run with Docker Compose

This repository ships a ready-to-use [`compose.yaml`](./compose.yaml) that starts the exporter and a Prometheus instance
for local testing.

Steps:

1. `cp .env.dist .env` and fill in your credentials
2. `docker compose up -d`
3. Metrics endpoint: <http://127.0.0.1:9123/metrics>
4. Prometheus UI (from the included service): <http://127.0.0.1:9090>

### 3) Run with Docker (without Compose)

Build and run the image directly:

- Build: `docker build -t anker-solix-prom-exporter .`
- Run: `docker run --rm -p 9123:9123 --env-file .env anker-solix-prom-exporter`
- Then visit <http://127.0.0.1:9123/metrics>

You can also override settings on the command line:

- `docker run --rm -p 9000:9000 -e ANKER_EXPORTER_PORT=9000 --env-file .env anker-solix-prom-exporter`

## What it exports

The exporter polls the Anker Solix Cloud periodically and exposes gauges for:

- Device identity and firmware info
- Power/energy values (AC/DC power, battery SoC/capacity, PV generation, home load)
- Network status (WiFi RSSI/online, wired connection)
- Status/flags and various counters

Endpoint: `/metrics` (text format compatible with Prometheus)
Default port: `9123` (configurable via ANKER_EXPORTER_PORT)
Refresh interval: every 30s by default (ANKER_SCRAPE_INTERVAL)

## How it works / Credits

- API client: [anker-solix-api by thomluther (GitHub)](https://github.com/thomluther/anker-solix-api) — used for
  authentication and device data. The exporter depends on this library via a Git dependency pinned in pyproject.toml.
- HTTP client: aiohttp
- Metrics: prometheus-client
- Env loader: python-dotenv (loads .env automatically)

## Security notes

- Never commit your .env file or credentials.
