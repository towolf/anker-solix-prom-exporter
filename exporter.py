#!/usr/bin/env python3
"""Prometheus exporter for the Anker Solix API.

- Loads credentials from .env using python-dotenv (ANKERUSER, ANKERPASSWORD, ANKERCOUNTRY)
- Authenticates to Anker Solix cloud and periodically refreshes data
- Exposes selected device and site metrics on an HTTP endpoint

Environment variables:
- ANKERUSER:        Account e-mail
- ANKERPASSWORD:    Account password
- ANKERCOUNTRY:     Country code (e.g. DE)
- ANKER_EXPORTER_PORT:     Port for the exporter HTTP server (default: 9123)
- ANKER_SCRAPE_INTERVAL:   Polling interval in seconds (default: 30)

Run:
    python exporter.py
Then scrape: http://localhost:<port>/metrics
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, Tuple

from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientError
from dotenv import load_dotenv
from prometheus_client import Gauge, start_http_server

# Load .env before importing modules that read env at import time
load_dotenv()

from api import api, errors  # pylint: disable=no-name-in-module
import common

# Configure console logger formatting similar to the other scripts
CONSOLE: logging.Logger = common.CONSOLE
CONSOLE.name = "AnkerSolixExporter"
CONSOLE.handlers[0].setFormatter(
    logging.Formatter(
        fmt="%(levelname)s: %(message)s",
    )
)

# Cache of Gauge objects by (name, labelnames)
_GAUGES: Dict[Tuple[str, Tuple[str, ...]], Gauge] = {}


def _get_gauge(name: str, description: str, labelnames: Tuple[str, ...]) -> Gauge:
    key = (name, labelnames)
    g = _GAUGES.get(key)
    if g is None:
        g = Gauge(name, description, labelnames=labelnames)
        _GAUGES[key] = g
    return g


def _as_float(value: Any) -> float | None:
    """Convert values like '---' or None safely to float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        v = value.strip()
        if v in ("", "-", "--", "---", "----"):
            return None
        # strip possible units like ' W'
        v = v.replace("W", "").replace("%", "").strip()
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _set_metric(name: str, help_text: str, labels: Dict[str, str], value: Any) -> None:
    val = _as_float(value)
    if val is None:
        return
    gauge = _get_gauge(name, help_text, tuple(labels.keys()))
    gauge.labels(**labels).set(val)


async def _poll_and_update_metrics(client: api.AnkerSolixApi, interval: int) -> None:
    """Continuously poll the API and update metrics."""
    # Site metrics labels: site_id, site_name
    # Device metrics labels: device_sn, site_id, type, name
    while True:
        try:
            # Update caches
            await client.update_sites()
            await client.update_device_details()
            await client.update_site_details()

            # Export site metrics
            for site_id, site in client.sites.items():
                site_name = ((site.get("site_info") or {}).get("site_name")) or "Unknown"
                s_labels = {"site_id": str(site_id), "site_name": str(site_name)}

                _set_metric(
                    "anker_site_home_load_power_watts",
                    "Current site home load power",
                    labels=s_labels,
                    value=site.get("home_load_power"),
                )
                sb_info = site.get("solarbank_info") or {}
                _set_metric(
                    "anker_site_to_home_load_power_watts",
                    "Power from Solarbank to home load",
                    s_labels,
                    sb_info.get("to_home_load"),
                )
                # Site-level Solarbank totals if present
                _set_metric(
                    "anker_site_total_pv_power_watts",
                    "Total photovoltaic power of Solarbank(s)",
                    s_labels,
                    (sb_info.get("total_photovoltaic_power")),
                )
                _set_metric(
                    "anker_site_total_output_power_watts",
                    "Total AC output power of Solarbank(s)",
                    s_labels,
                    (sb_info.get("total_output_power")),
                )
                _set_metric(
                    "anker_site_total_charging_power_watts",
                    "Total charging power to Solarbank batteries (can be negative when discharging)",
                    s_labels,
                    (sb_info.get("total_charging_power")),
                )
                _set_metric(
                    "anker_site_battery_discharge_power_watts",
                    "Battery discharge power total (if provided)",
                    s_labels,
                    (sb_info.get("battery_discharge_power")),
                )
                # Cascaded Solarbank flag
                if sb_info.get("sb_cascaded") is not None:
                    _set_metric(
                        "anker_site_solarbanks_cascaded",
                        "Whether multiple Solarbank generations are cascaded (1) or not (0)",
                        s_labels,
                        1.0 if sb_info.get("sb_cascaded") else 0.0,
                    )
                sp_info = site.get("smart_plug_info") or {}
                _set_metric(
                    "anker_site_smart_plugs_total_power_watts",
                    "Total power of smart plugs in site",
                    s_labels,
                    sp_info.get("total_power"),
                )
                _set_metric(
                    "anker_site_other_loads_power_watts",
                    "Other loads (planned) power",
                    s_labels,
                    site.get("other_loads_power"),
                )
                # Retain load preset if present (strip unit via _as_float)
                _set_metric(
                    "anker_site_retain_load_preset_watts",
                    "Site retain load preset (W)",
                    s_labels,
                    site.get("retain_load"),
                )
                # Data validity as 0/1
                data_valid = 1.0 if site.get("data_valid") else 0.0
                _set_metric(
                    "anker_site_data_valid",
                    "Whether site data is valid (1) or not (0)",
                    s_labels,
                    data_valid,
                )
                # Total battery SOC (site-level) if provided as 0..1 fraction
                total_batt = sb_info.get("total_battery_power")
                if (f := _as_float(total_batt)) is not None:
                    _set_metric(
                        "anker_site_total_battery_soc_percent",
                        "Total Solarbank state-of-charge (percent)",
                        s_labels,
                        f * 100.0,
                    )

            # Export device metrics
            for sn, dev in client.devices.items():
                d_labels = {
                    "device_sn": str(sn),
                    "site_id": str(dev.get("site_id") or ""),
                    "type": str(dev.get("type") or "unknown"),
                    "name": str(dev.get("name") or dev.get("alias") or "noname"),
                }

                # info metric
                info_labels = dict(d_labels)
                info_labels.update(
                    {
                        "device_pn": str(dev.get("device_pn") or ""),
                        "generation": str(dev.get("generation") or ""),
                        "sw_version": str(dev.get("sw_version") or ""),
                    }
                )
                _set_metric(
                    "anker_device_info",
                    "Static info about the device (always 1)",
                    info_labels,
                    1,
                )

                # Common power-related metrics
                _set_metric(
                    "anker_device_battery_soc_percent",
                    "Device battery state-of-charge (percent)",
                    labels=d_labels,
                    value=dev.get("battery_soc"),
                )
                _set_metric(
                    "anker_device_battery_energy_wh",
                    "Device battery energy (Wh)",
                    d_labels,
                    dev.get("battery_energy"),
                )
                _set_metric(
                    "anker_device_input_power_watts",
                    "Device input (PV) power (W)",
                    d_labels,
                    dev.get("input_power"),
                )
                _set_metric(
                    "anker_device_output_power_watts",
                    "Device output (AC/home load) power (W)",
                    d_labels,
                    dev.get("output_power"),
                )
                _set_metric(
                    "anker_device_battery_power_watts",
                    "Battery net power (W). Positive = discharge to AC, negative = charge",
                    d_labels,
                    dev.get("charging_power"),
                )
                _set_metric(
                    "anker_device_bat_charge_power_watts",
                    "Battery charge power (W)",
                    d_labels,
                    dev.get("bat_charge_power"),
                )

                # Inverter values
                _set_metric(
                    "anker_device_ac_power_watts",
                    "Inverter AC generation power (W)",
                    d_labels,
                    dev.get("generate_power"),
                )
                _set_metric(
                    "anker_device_micro_inverter_power_watts",
                    "Micro-inverter power (W)",
                    d_labels,
                    dev.get("micro_inverter_power"),
                )
                _set_metric(
                    "anker_device_micro_inverter_power_limit_watts",
                    "Micro-inverter power limit (W)",
                    d_labels,
                    dev.get("micro_inverter_power_limit") or dev.get("preset_inverter_limit"),
                )

                # Smart meter values
                _set_metric(
                    "anker_device_grid_import_power_watts",
                    "Grid import power to home (W)",
                    d_labels,
                    dev.get("grid_to_home_power"),
                )
                _set_metric(
                    "anker_device_grid_export_power_watts",
                    "Photovoltaic export power to grid (W)",
                    d_labels,
                    dev.get("photovoltaic_to_grid_power"),
                )

                # Smart plug values
                _set_metric(
                    "anker_device_plug_power_watts",
                    "Smart plug current power (W)",
                    d_labels,
                    dev.get("current_power"),
                )
                _set_metric(
                    "anker_device_energy_today_kwh",
                    "Device energy today (kWh)",
                    d_labels,
                    dev.get("energy_today"),
                )

                # Additional Solarbank PV string powers and related metrics
                _set_metric(
                    "anker_device_solar_power_1_watts",
                    "PV string 1 power (W)",
                    d_labels,
                    dev.get("solar_power_1"),
                )
                _set_metric(
                    "anker_device_solar_power_2_watts",
                    "PV string 2 power (W)",
                    d_labels,
                    dev.get("solar_power_2"),
                )
                _set_metric(
                    "anker_device_solar_power_3_watts",
                    "PV string 3 power (W)",
                    d_labels,
                    dev.get("solar_power_3"),
                )
                _set_metric(
                    "anker_device_solar_power_4_watts",
                    "PV string 4 power (W)",
                    d_labels,
                    dev.get("solar_power_4"),
                )
                _set_metric(
                    "anker_device_ac_port_power_watts",
                    "AC port output power (W)",
                    d_labels,
                    dev.get("ac_power"),
                )
                _set_metric(
                    "anker_device_other_input_power_watts",
                    "Other input power (W)",
                    d_labels,
                    dev.get("other_input_power"),
                )
                _set_metric(
                    "anker_device_micro_inverter_low_power_limit_watts",
                    "Micro-inverter low power limit (W)",
                    d_labels,
                    dev.get("micro_inverter_low_power_limit"),
                )
                _set_metric(
                    "anker_device_grid_to_battery_power_watts",
                    "Grid to battery power (W)",
                    d_labels,
                    dev.get("grid_to_battery_power"),
                )
                _set_metric(
                    "anker_device_pei_heating_power_watts",
                    "PEI heating power (W)",
                    d_labels,
                    dev.get("pei_heating_power"),
                )
                _set_metric(
                    "anker_device_set_output_power_watts",
                    "Device preset output power (W)",
                    d_labels,
                    dev.get("set_output_power"),
                )
                _set_metric(
                    "anker_device_set_system_output_power_watts",
                    "System preset output power (W)",
                    d_labels,
                    dev.get("set_system_output_power"),
                )

                # Connectivity metrics
                _set_metric(
                    "anker_device_wifi_signal_percent",
                    "WiFi signal strength (percent)",
                    d_labels,
                    dev.get("wifi_signal"),
                )
                _set_metric(
                    "anker_device_wifi_rssi_dbm",
                    "WiFi RSSI (dBm)",
                    d_labels,
                    dev.get("rssi"),
                )
                if dev.get("wifi_online") is not None:
                    _set_metric(
                        "anker_device_wifi_online",
                        "WiFi connectivity (1 online, 0 offline)",
                        d_labels,
                        1.0 if dev.get("wifi_online") else 0.0,
                    )
                if dev.get("wired_connected") is not None:
                    _set_metric(
                        "anker_device_wired_connected",
                        "Wired connection present (1 yes, 0 no)",
                        d_labels,
                        1.0 if dev.get("wired_connected") else 0.0,
                    )

                # Status/flags
                _set_metric(
                    "anker_device_status_code",
                    "Device status code",
                    d_labels,
                    dev.get("status"),
                )
                _set_metric(
                    "anker_device_charging_status_code",
                    "Charging status code",
                    d_labels,
                    dev.get("charging_status"),
                )
                _set_metric(
                    "anker_device_grid_status_code",
                    "Grid status code",
                    d_labels,
                    dev.get("grid_status"),
                )
                if dev.get("data_valid") is not None:
                    _set_metric(
                        "anker_device_data_valid",
                        "Whether device data is valid (1) or not (0)",
                        d_labels,
                        1.0 if dev.get("data_valid") else 0.0,
                    )
                if dev.get("is_ota_update") is not None:
                    _set_metric(
                        "anker_device_is_ota_update",
                        "OTA update available (1) or not (0)",
                        d_labels,
                        1.0 if dev.get("is_ota_update") else 0.0,
                    )
                if dev.get("auto_upgrade") is not None:
                    _set_metric(
                        "anker_device_auto_upgrade",
                        "Auto upgrade enabled (1) or disabled (0)",
                        d_labels,
                        1.0 if dev.get("auto_upgrade") else 0.0,
                    )

                # Capacity/counters
                _set_metric(
                    "anker_device_battery_capacity_wh",
                    "Battery capacity (Wh)",
                    d_labels,
                    dev.get("battery_capacity"),
                )
                _set_metric(
                    "anker_device_sub_package_num",
                    "Sub package number",
                    d_labels,
                    dev.get("sub_package_num"),
                )

        except (ClientError, errors.AnkerSolixError) as err:
            CONSOLE.error("%s: %s", type(err), err)
        except Exception as exc:  # noqa: BLE001
            CONSOLE.exception("Unhandled error: %s", exc)
        finally:
            await asyncio.sleep(max(5, interval))


async def _run() -> None:
    # .env already loaded at import time
    port = int(os.getenv("ANKER_EXPORTER_PORT", "9123"))
    interval = int(os.getenv("ANKER_SCRAPE_INTERVAL", "30"))

    # Start HTTP server for Prometheus
    start_http_server(port)
    CONSOLE.info("Prometheus exporter listening on :%s/metrics", port)

    user = common.user()
    pwd = common.password()
    country = common.country()

    async with ClientSession() as websession:
        CONSOLE.info("Authenticating to Anker Cloud for user %s...", user)
        client = api.AnkerSolixApi(user, pwd, country, websession, CONSOLE)
        try:
            if await client.async_authenticate():
                CONSOLE.info("Authentication: OK")
            else:
                CONSOLE.info("Authentication: CACHED (will validate on first call)")
        except (ClientError, errors.AnkerSolixError) as err:
            CONSOLE.error("Authentication failed: %s: %s", type(err), err)

        await _poll_and_update_metrics(client, interval)


if __name__ == "__main__":
    try:
        asyncio.run(_run(), debug=False)
    except KeyboardInterrupt:
        CONSOLE.warning("Exporter aborted by user")
    except Exception as exc:  # noqa: BLE001
        CONSOLE.exception("%s: %s", type(exc), exc)
