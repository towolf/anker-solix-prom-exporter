# Anker Solix Prometheus Exporter

A lightweight Prometheus exporter that authenticates to the Anker Solix Cloud and exposes device and energy metrics over
HTTP for scraping by Prometheus.

This project builds on top of the
excellent [Anker Solix API client library by thomluther](https://github.com/thomluther/anker-solix-api) (v3.1.1 in this
project)

It was further extended in an experimental vibe coding session in order to add more metrics and add MQTT support for more frequent updates.

You can find the docker image on the [Gitlab Container Registry](https://gitlab.com/oroessner/anker-solix-prom-exporter/container_registry) and on [Docker Hub](https://hub.docker.com/r/djbasster/anker-solix-prom-exporter).

## Usage

tl;dr:

```shell
docker run --rm -p "127.0.0.1:9123:9123" -e ANKERUSER=<user> -e ANKERPASSWORD=<password> -e ANKERCOUNTRY=<country> djbasster/anker-solix-prom-exporter
```

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

### Metrics

| Metric                                            | Type  | Description                                                                    |
|---------------------------------------------------|-------|--------------------------------------------------------------------------------|
| anker_site_home_load_power_watts                  | gauge | Current site home load power                                                   |
| anker_site_to_home_load_power_watts               | gauge | Power from Solarbank to home load                                              |
| anker_site_total_pv_power_watts                   | gauge | Total photovoltaic power of Solarbank(s)                                       |
| anker_site_total_output_power_watts               | gauge | Total AC output power of Solarbank(s)                                          |
| anker_site_total_charging_power_watts             | gauge | Total charging power to Solarbank batteries (can be negative when discharging) |
| anker_site_battery_discharge_power_watts          | gauge | Battery discharge power total (if provided)                                    |
| anker_site_solarbanks_cascaded                    | gauge | Whether multiple Solarbank generations are cascaded (1) or not (0)             |
| anker_site_smart_plugs_total_power_watts          | gauge | Total power of smart plugs in site                                             |
| anker_site_other_loads_power_watts                | gauge | Other loads (planned) power                                                    |
| anker_site_retain_load_preset_watts               | gauge | Site retain load preset (W)                                                    |
| anker_site_data_valid                             | gauge | Whether site data is valid (1) or not (0)                                      |
| anker_site_total_battery_soc_percent              | gauge | Total Solarbank state-of-charge (percent)                                      |
| anker_device_info                                 | gauge | Static info about the device (always 1)                                        |
| anker_device_battery_soc_percent                  | gauge | Device battery state-of-charge (percent)                                       |
| anker_device_battery_energy_wh                    | gauge | Device battery energy (Wh)                                                     |
| anker_device_input_power_watts                    | gauge | Device input (PV) power (W)                                                    |
| anker_device_output_power_watts                   | gauge | Device output (AC/home load) power (W)                                         |
| anker_device_battery_power_watts                  | gauge | Battery net power (W). Positive = discharge to AC, negative = charge           |
| anker_device_bat_charge_power_watts               | gauge | Battery charge power (W)                                                       |
| anker_device_ac_power_watts                       | gauge | Inverter AC generation power (W)                                               |
| anker_device_micro_inverter_power_watts           | gauge | Micro-inverter power (W)                                                       |
| anker_device_micro_inverter_power_limit_watts     | gauge | Micro-inverter power limit (W)                                                 |
| anker_device_grid_import_power_watts              | gauge | Grid import power to home (W)                                                  |
| anker_device_grid_export_power_watts              | gauge | Photovoltaic export power to grid (W)                                          |
| anker_device_plug_power_watts                     | gauge | Smart plug current power (W)                                                   |
| anker_device_energy_today_kwh                     | gauge | Device energy today (kWh)                                                      |
| anker_device_solar_power_1_watts                  | gauge | PV string 1 power (W)                                                          |
| anker_device_solar_power_2_watts                  | gauge | PV string 2 power (W)                                                          |
| anker_device_solar_power_3_watts                  | gauge | PV string 3 power (W)                                                          |
| anker_device_solar_power_4_watts                  | gauge | PV string 4 power (W)                                                          |
| anker_device_ac_port_power_watts                  | gauge | AC port output power (W)                                                       |
| anker_device_other_input_power_watts              | gauge | Other input power (W)                                                          |
| anker_device_micro_inverter_low_power_limit_watts | gauge | Micro-inverter low power limit (W)                                             |
| anker_device_grid_to_battery_power_watts          | gauge | Grid to battery power (W)                                                      |
| anker_device_pei_heating_power_watts              | gauge | PEI heating power (W)                                                          |
| anker_device_set_output_power_watts               | gauge | Device preset output power (W)                                                 |
| anker_device_set_system_output_power_watts        | gauge | System preset output power (W)                                                 |
| anker_device_wifi_signal_percent                  | gauge | WiFi signal strength (percent)                                                 |
| anker_device_wifi_rssi_dbm                        | gauge | WiFi RSSI (dBm)                                                                |
| anker_device_wifi_online                          | gauge | WiFi connectivity (1 online, 0 offline)                                        |
| anker_device_wired_connected                      | gauge | Wired connection present (1 yes, 0 no)                                         |
| anker_device_status_code                          | gauge | Device status code                                                             |
| anker_device_charging_status_code                 | gauge | Charging status code                                                           |
| anker_device_grid_status_code                     | gauge | Grid status code                                                               |
| anker_device_data_valid                           | gauge | Whether device data is valid (1) or not (0)                                    |
| anker_device_is_ota_update                        | gauge | OTA update available (1) or not (0)                                            |
| anker_device_auto_upgrade                         | gauge | Auto upgrade enabled (1) or disabled (0)                                       |
| anker_device_battery_capacity_wh                  | gauge | Battery capacity (Wh)                                                          |
| anker_device_sub_package_num                      | gauge | Sub package number                                                             |

## How it works / Credits

- API client: [anker-solix-api by thomluther (GitHub)](https://github.com/thomluther/anker-solix-api) — used for
  authentication and device data. The exporter depends on this library via a Git dependency pinned in pyproject.toml.
- HTTP client: aiohttp
- Metrics: prometheus-client
- Env loader: python-dotenv (loads .env automatically)

## Security notes

- Never commit your .env file or credentials.
