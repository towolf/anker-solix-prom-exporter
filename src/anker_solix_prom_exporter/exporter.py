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
from typing import Any, Dict
from datetime import datetime

from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientError
from dotenv import load_dotenv
from prometheus_client import Gauge, start_http_server, Counter

# Load .env before importing modules that read env at import time
load_dotenv()

from api import api, errors  # pylint: disable=no-name-in-module
from anker_solix_prom_exporter import util

# Configure console logger formatting similar to the other scripts
CONSOLE: logging.Logger = util.CONSOLE
CONSOLE.name = "AnkerSolixExporter"
CONSOLE.handlers[0].setFormatter(
    logging.Formatter(
        fmt="%(levelname)s: %(message)s",
    )
)

# Site metrics - Gauge
anker_site_home_load_power_watts = Gauge(
    "anker_site_home_load_power_watts",
    "Current site home load power",
    labelnames=["site_id", "site_name"]
)
anker_site_to_home_load_power_watts = Gauge(
    "anker_site_to_home_load_power_watts",
    "Power from Solarbank to home load",
    labelnames=["site_id", "site_name"]
)
anker_site_total_pv_power_watts = Gauge(
    "anker_site_total_pv_power_watts",
    "Total photovoltaic power of Solarbank(s)",
    labelnames=["site_id", "site_name"]
)
anker_site_total_output_power_watts = Gauge(
    "anker_site_total_output_power_watts",
    "Total AC output power of Solarbank(s)",
    labelnames=["site_id", "site_name"]
)
anker_site_total_charging_power_watts = Gauge(
    "anker_site_total_charging_power_watts",
    "Total charging power to Solarbank batteries (can be negative when discharging)",
    labelnames=["site_id", "site_name"]
)
anker_site_battery_discharge_power_watts = Gauge(
    "anker_site_battery_discharge_power_watts",
    "Battery discharge power total (if provided)",
    labelnames=["site_id", "site_name"]
)
anker_site_smart_plugs_total_power_watts = Gauge(
    "anker_site_smart_plugs_total_power_watts",
    "Total power of smart plugs in site",
    labelnames=["site_id", "site_name"]
)
anker_site_other_loads_power_watts = Gauge(
    "anker_site_other_loads_power_watts",
    "Other loads (planned) power",
    labelnames=["site_id", "site_name"]
)
anker_site_retain_load_preset_watts = Gauge(
    "anker_site_retain_load_preset_watts",
    "Site retain load preset (W)",
    labelnames=["site_id", "site_name"]
)
anker_site_data_valid = Gauge(
    "anker_site_data_valid",
    "Whether site data is valid (1) or not (0)",
    labelnames=["site_id", "site_name"]
)
anker_site_total_battery_soc_percent = Gauge(
    "anker_site_total_battery_soc_percent",
    "Total Solarbank state-of-charge (percent)",
    labelnames=["site_id", "site_name"]
)

# Site metrics - Counter
anker_site_updated_timestamp_seconds = Counter(
    "anker_site_updated_timestamp_seconds",
    "Last update timestamp of Solarbank info as seconds since the epoch",
    labelnames=["site_id", "site_name"]
)
anker_site_energy_offset_check = Counter(
    "anker_site_energy_offset_check",
    "Last energy offset check timestamp as seconds since the epoch",
    labelnames=["site_id", "site_name"]
)

# Site metrics - Gauge (continued)
anker_site_energy_offset_seconds = Gauge(
    "anker_site_energy_offset_seconds",
    "Energy offset in seconds for the site",
    labelnames=["site_id", "site_name"]
)

# Device metrics - Gauge
anker_device_info = Gauge(
    "anker_device_info",
    "Static info about the device (always 1)",
    labelnames=["device_sn", "name", "device_pn", "generation", "sw_version"]
)
anker_device_battery_soc_percent = Gauge(
    "anker_device_battery_soc_percent",
    "Device battery state-of-charge (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_battery_energy_wh = Gauge(
    "anker_device_battery_energy_wh",
    "Device battery energy (Wh)",
    labelnames=["device_sn", "name"]
)
anker_device_input_power_watts = Gauge(
    "anker_device_input_power_watts",
    "Device input (PV) power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_output_power_watts = Gauge(
    "anker_device_output_power_watts",
    "Device output (AC/home load) power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_battery_power_watts = Gauge(
    "anker_device_battery_power_watts",
    "Battery net power (W). Positive = discharge to AC, negative = charge",
    labelnames=["device_sn", "name"]
)
anker_device_bat_charge_power_watts = Gauge(
    "anker_device_bat_charge_power_watts",
    "Battery charge power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_ac_power_watts = Gauge(
    "anker_device_ac_power_watts",
    "Inverter AC generation power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_micro_inverter_power_watts = Gauge(
    "anker_device_micro_inverter_power_watts",
    "Micro-inverter power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_micro_inverter_power_limit_watts = Gauge(
    "anker_device_micro_inverter_power_limit_watts",
    "Micro-inverter power limit (W)",
    labelnames=["device_sn", "name"]
)
anker_device_grid_import_power_watts = Gauge(
    "anker_device_grid_import_power_watts",
    "Grid import power to home (W)",
    labelnames=["device_sn", "name"]
)
anker_device_grid_export_power_watts = Gauge(
    "anker_device_grid_export_power_watts",
    "Photovoltaic export power to grid (W)",
    labelnames=["device_sn", "name"]
)
anker_device_plug_power_watts = Gauge(
    "anker_device_plug_power_watts",
    "Smart plug current power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_energy_today_kwh = Gauge(
    "anker_device_energy_today_kwh",
    "Device energy today (kWh)",
    labelnames=["device_sn", "name"]
)
anker_device_string_power_watts = Gauge(
    "anker_device_string_power_watts",
    "PV string power (W)",
    labelnames=["device_sn", "name", "string"]
)
anker_device_ac_port_power_watts = Gauge(
    "anker_device_ac_port_power_watts",
    "AC port output power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_other_input_power_watts = Gauge(
    "anker_device_other_input_power_watts",
    "Other input power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_micro_inverter_low_power_limit_watts = Gauge(
    "anker_device_micro_inverter_low_power_limit_watts",
    "Micro-inverter low power limit (W)",
    labelnames=["device_sn", "name"]
)
anker_device_grid_to_battery_power_watts = Gauge(
    "anker_device_grid_to_battery_power_watts",
    "Grid to battery power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_pei_heating_power_watts = Gauge(
    "anker_device_pei_heating_power_watts",
    "PEI heating power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_set_output_power_watts = Gauge(
    "anker_device_set_output_power_watts",
    "Device preset output power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_set_system_output_power_watts = Gauge(
    "anker_device_set_system_output_power_watts",
    "System preset output power (W)",
    labelnames=["device_sn", "name"]
)
anker_device_wifi_signal_percent = Gauge(
    "anker_device_wifi_signal_percent",
    "WiFi signal strength (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_wifi_rssi_dbm = Gauge(
    "anker_device_wifi_rssi_dbm",
    "WiFi RSSI (dBm)",
    labelnames=["device_sn", "name"]
)
anker_device_wifi_online = Gauge(
    "anker_device_wifi_online",
    "WiFi connectivity (1 online, 0 offline)",
    labelnames=["device_sn", "name"]
)
anker_device_wired_connected = Gauge(
    "anker_device_wired_connected",
    "Wired connection present (1 yes, 0 no)",
    labelnames=["device_sn", "name"]
)
anker_device_status_code = Gauge(
    "anker_device_status_code",
    "Device status code",
    labelnames=["device_sn", "name"]
)
anker_device_charging_status_code = Gauge(
    "anker_device_charging_status_code",
    "Charging status code",
    labelnames=["device_sn", "name"]
)
anker_device_grid_status_code = Gauge(
    "anker_device_grid_status_code",
    "Grid status code",
    labelnames=["device_sn", "name"]
)
anker_device_data_valid = Gauge(
    "anker_device_data_valid",
    "Whether device data is valid (1) or not (0)",
    labelnames=["device_sn", "name"]
)
anker_device_is_ota_update = Gauge(
    "anker_device_is_ota_update",
    "OTA update available (1) or not (0)",
    labelnames=["device_sn", "name"]
)
anker_device_auto_upgrade = Gauge(
    "anker_device_auto_upgrade",
    "Auto upgrade enabled (1) or disabled (0)",
    labelnames=["device_sn", "name"]
)
anker_device_battery_capacity_wh = Gauge(
    "anker_device_battery_capacity_wh",
    "Battery capacity (Wh)",
    labelnames=["device_sn", "name"]
)
anker_device_sub_package_num = Gauge(
    "anker_device_sub_package_num",
    "Sub package number",
    labelnames=["device_sn", "name"]
)


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


def _set_gauge(gauge: Gauge, labels: Dict[str, str], value: Any) -> None:
    val = _as_float(value)
    if val is None:
        return
    gauge.labels(**labels).set(val)


def _inc_counter(counter: Counter, labels: Dict[str, str], value: Any) -> None:
    val = _as_float(value)
    if val is None:
        return
    counter.labels(**labels).inc(val)


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
                site_name = (
                    (site.get("site_info") or {}).get("site_name")
                ) or "Unknown"
                s_labels = {"site_id": str(site_id), "site_name": str(site_name)}

                sb_info = site.get("solarbank_info") or {}
                sp_info = site.get("smart_plug_info") or {}

                _set_gauge(anker_site_home_load_power_watts, s_labels, site.get("home_load_power"))
                _set_gauge(anker_site_to_home_load_power_watts, s_labels, sb_info.get("to_home_load"))
                _set_gauge(anker_site_total_pv_power_watts, s_labels, sb_info.get("total_photovoltaic_power"))
                _set_gauge(anker_site_total_output_power_watts, s_labels, sb_info.get("total_output_power"))
                _set_gauge(anker_site_total_charging_power_watts, s_labels, sb_info.get("total_charging_power"))
                _set_gauge(anker_site_battery_discharge_power_watts, s_labels, sb_info.get("battery_discharge_power"))
                _set_gauge(anker_site_smart_plugs_total_power_watts, s_labels, sp_info.get("total_power"))
                _set_gauge(anker_site_other_loads_power_watts, s_labels, site.get("other_loads_power"))
                _set_gauge(anker_site_retain_load_preset_watts, s_labels, site.get("retain_load"))
                _set_gauge(anker_site_data_valid, s_labels, 1.0 if site.get("data_valid") else 0.0)
                
                total_battery_soc = sb_info.get("total_battery_power")
                if total_battery_soc is not None:
                    f = _as_float(total_battery_soc)
                    if f is not None:
                        _set_gauge(anker_site_total_battery_soc_percent, s_labels, f * 100.0)
                
                if sb_info.get("updated_time"):
                    try:
                        timestamp = datetime.strptime(sb_info["updated_time"], "%Y-%m-%d %H:%M:%S").timestamp()
                        _inc_counter(anker_site_updated_timestamp_seconds, s_labels, timestamp)
                    except Exception:
                        pass
                
                if site.get("energy_offset_seconds") is not None:
                    _inc_counter(anker_site_energy_offset_seconds, s_labels, site.get("energy_offset_seconds"))
                
                if site.get("energy_offset_check"):
                    try:
                        timestamp = datetime.strptime(site["energy_offset_check"], "%Y-%m-%d %H:%M:%S").timestamp()
                        _inc_counter(anker_site_energy_offset_check, s_labels, timestamp)
                    except Exception:
                        pass

            # Export device metrics
            for sn, dev in client.devices.items():
                d_labels = {
                    "device_sn": str(sn),
                    "name": str(dev.get("name") or dev.get("alias") or "noname"),
                }

                info_labels = dict(d_labels)
                info_labels.update(
                    {
                        "device_pn": str(dev.get("device_pn") or ""),
                        "generation": str(dev.get("generation") or ""),
                        "sw_version": str(dev.get("sw_version") or ""),
                    }
                )
                _set_gauge(anker_device_info, info_labels, 1)

                _set_gauge(anker_device_battery_soc_percent, d_labels, dev.get("battery_soc"))
                _set_gauge(anker_device_battery_energy_wh, d_labels, dev.get("battery_energy"))
                _set_gauge(anker_device_input_power_watts, d_labels, dev.get("input_power"))
                _set_gauge(anker_device_output_power_watts, d_labels, dev.get("output_power"))
                _set_gauge(anker_device_battery_power_watts, d_labels, dev.get("charging_power"))
                _set_gauge(anker_device_bat_charge_power_watts, d_labels, dev.get("bat_charge_power"))
                _set_gauge(anker_device_ac_power_watts, d_labels, dev.get("generate_power"))
                _set_gauge(anker_device_micro_inverter_power_watts, d_labels, dev.get("micro_inverter_power"))
                _set_gauge(
                    anker_device_micro_inverter_power_limit_watts,
                    d_labels,
                    dev.get("micro_inverter_power_limit") or dev.get("preset_inverter_limit")
                )
                _set_gauge(anker_device_grid_import_power_watts, d_labels, dev.get("grid_to_home_power"))
                _set_gauge(anker_device_grid_export_power_watts, d_labels, dev.get("photovoltaic_to_grid_power"))
                _set_gauge(anker_device_plug_power_watts, d_labels, dev.get("current_power"))
                _set_gauge(anker_device_energy_today_kwh, d_labels, dev.get("energy_today"))
                
                for panel_idx in range(1, 5):
                    solar_key = f"solar_power_{panel_idx}"
                    if dev.get(solar_key) is not None:
                        panel_labels = dict(d_labels)
                        panel_labels["string"] = str(panel_idx)
                        _set_gauge(anker_device_string_power_watts, panel_labels, dev.get(solar_key))
                
                _set_gauge(anker_device_ac_port_power_watts, d_labels, dev.get("ac_power"))
                _set_gauge(anker_device_other_input_power_watts, d_labels, dev.get("other_input_power"))
                _set_gauge(anker_device_micro_inverter_low_power_limit_watts, d_labels, dev.get("micro_inverter_low_power_limit"))
                _set_gauge(anker_device_grid_to_battery_power_watts, d_labels, dev.get("grid_to_battery_power"))
                _set_gauge(anker_device_pei_heating_power_watts, d_labels, dev.get("pei_heating_power"))
                _set_gauge(anker_device_set_output_power_watts, d_labels, dev.get("set_output_power"))
                _set_gauge(anker_device_set_system_output_power_watts, d_labels, dev.get("set_system_output_power"))

                _set_gauge(anker_device_wifi_signal_percent, d_labels, dev.get("wifi_signal"))
                _set_gauge(anker_device_wifi_rssi_dbm, d_labels, dev.get("rssi"))
                _set_gauge(
                    anker_device_wifi_online,
                    d_labels,
                    (1.0 if dev.get("wifi_online") else 0.0) if dev.get("wifi_online") is not None else None
                )
                _set_gauge(
                    anker_device_wired_connected,
                    d_labels,
                    (1.0 if dev.get("wired_connected") else 0.0) if dev.get("wired_connected") is not None else None
                )

                _set_gauge(anker_device_status_code, d_labels, dev.get("status"))
                _set_gauge(anker_device_charging_status_code, d_labels, dev.get("charging_status"))
                _set_gauge(anker_device_grid_status_code, d_labels, dev.get("grid_status"))
                _set_gauge(
                    anker_device_data_valid,
                    d_labels,
                    (1.0 if dev.get("data_valid") else 0.0) if dev.get("data_valid") is not None else None
                )
                _set_gauge(
                    anker_device_is_ota_update,
                    d_labels,
                    (1.0 if dev.get("is_ota_update") else 0.0) if dev.get("is_ota_update") is not None else None
                )
                _set_gauge(
                    anker_device_auto_upgrade,
                    d_labels,
                    (1.0 if dev.get("auto_upgrade") else 0.0) if dev.get("auto_upgrade") is not None else None
                )

                _set_gauge(anker_device_battery_capacity_wh, d_labels, dev.get("battery_capacity"))
                _set_gauge(anker_device_sub_package_num, d_labels, dev.get("sub_package_num"))

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

    user = util.user()
    pwd = util.password()
    country = util.country()

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
