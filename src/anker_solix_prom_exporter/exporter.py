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
import getpass
import json
import logging
import os
from typing import Any, Dict
from datetime import datetime


from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientError
from dotenv import load_dotenv
from prometheus_client import Gauge, start_http_server

# Load .env before importing modules that read env at import time
load_dotenv()

from api import api, errors  # pylint: disable=no-name-in-module
from api.apitypes import ApiCategories, SolixDeviceType
from api.mqtt_factory import SolixMqttDeviceFactory

# Configure console logger formatting similar to the other scripts
CONSOLE: logging.Logger = logging.getLogger("AnkerSolixExporter")
CONSOLE.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
if os.environ.get("ANKER_EXPORTER_DEBUG") == "1":
    ch.setLevel(logging.DEBUG)
else:
    ch.setLevel(logging.INFO)
ch.setFormatter(
    logging.Formatter(
        fmt="%(levelname)s: %(message)s",
    )
)
CONSOLE.addHandler(ch)

# Add debug logs for the API usage
logging.getLogger("api").setLevel(logging.DEBUG)
logging.getLogger("api").addHandler(CONSOLE.handlers[0])

_CREDENTIALS = {
    "USER": os.getenv("ANKERUSER"),
    "PASSWORD": os.getenv("ANKERPASSWORD"),
    "COUNTRY": os.getenv("ANKERCOUNTRY"),
}


def user() -> str:
    """Get anker account user."""
    if usr := _CREDENTIALS.get("USER"):
        return str(usr)
    CONSOLE.info("\nEnter Anker Account credentials:")
    username = input("Username (email): ")
    while not username:
        username = input("Username (email): ")
    return username


def password() -> str:
    """Get anker account password."""
    if pwd := _CREDENTIALS.get("PASSWORD"):
        return str(pwd)
    pwd = getpass.getpass("Password: ")
    while not pwd:
        pwd = getpass.getpass("Password: ")
    return pwd


def country() -> str:
    """Get anker account country."""
    if ctry := _CREDENTIALS.get("COUNTRY"):
        return str(ctry)
    countrycode = input("Country ID (e.g. DE): ")
    while not countrycode:
        countrycode = input("Country ID (e.g. DE): ")
    return countrycode


# Site metrics - Gauge
anker_site_power_watts = Gauge(
    "anker_site_power_watts",
    "Site power metrics (W)",
    labelnames=["site_id", "site_name", "type"]
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

# Site metrics - Converted to Gauge
anker_site_updated_timestamp_seconds = Gauge(
    "anker_site_updated_timestamp_seconds_total",
    "Last update timestamp of Solarbank info as seconds since the epoch",
    labelnames=["site_id", "site_name"]
)
anker_site_energy_produced_kwh_total = Gauge(
    "anker_site_energy_produced_kwh_total",
    "Total energy produced by the site (kWh)",
    labelnames=["site_id", "site_name"]
)
anker_site_energy_today_kwh_total = Gauge(
    "anker_site_energy_today_kwh_total",
    "Energy values for today (kWh)",
    labelnames=["site_id", "site_name", "type"]
)
anker_site_energy_today_percent = Gauge(
    "anker_site_energy_today_percent",
    "Energy percentage values for today",
    labelnames=["site_id", "site_name", "type"]
)

# Site metrics - Gauge (continued)
anker_site_total_savings_money = Gauge(
    "anker_site_total_savings_money",
    "Total monetary savings/revenue for the site",
    labelnames=["site_id", "site_name"]
)
anker_site_price = Gauge(
    "anker_site_price",
    "Site energy price",
    labelnames=["site_id", "site_name", "price_type", "unit"]
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
anker_device_power_watts = Gauge(
    "anker_device_power_watts",
    "Device power metrics (W)",
    labelnames=["device_sn", "name", "type"]
)
anker_device_pv_power_watts = Gauge(
    "anker_device_pv_power_watts",
    "PV string power (W)",
    labelnames=["device_sn", "name", "pv"]
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
anker_device_charging_status = Gauge(
    "anker_device_charging_status",
    "Charging status code",
    labelnames=["device_sn", "name", "desc"]
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

# MQTT Metrics
anker_device_mqtt_power_watts = Gauge(
    "anker_device_mqtt_power_watts",
    "Device power metrics from MQTT (W)",
    labelnames=["device_sn", "name", "type"]
)
anker_device_mqtt_energy_total_kwh = Gauge(
    "anker_device_mqtt_energy_total_kwh",
    "Device energy metrics from MQTT (kWh)",
    labelnames=["device_sn", "name", "type"]
)
anker_device_mqtt_battery_soc_percent = Gauge(
    "anker_device_mqtt_battery_soc_percent",
    "Device battery SOC from MQTT (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_main_battery_soc_percent = Gauge(
    "anker_device_mqtt_main_battery_soc_percent",
    "Device main battery SOC from MQTT (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_temperature_celsius = Gauge(
    "anker_device_mqtt_temperature_celsius",
    "Device temperature from MQTT (Celsius)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_battery_efficiency_percent = Gauge(
    "anker_device_mqtt_battery_efficiency_percent",
    "Device battery efficiency from MQTT (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_device_efficiency_percent = Gauge(
    "anker_device_mqtt_device_efficiency_percent",
    "Device efficiency from MQTT (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_wifi_signal_percent = Gauge(
    "anker_device_mqtt_wifi_signal_percent",
    "Device WiFi signal from MQTT (percent)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_home_load_preset_watts = Gauge(
    "anker_device_mqtt_home_load_preset_watts",
    "Device home load preset from MQTT (W)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_max_load_watts = Gauge(
    "anker_device_mqtt_max_load_watts",
    "Device max load from MQTT (W)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_max_load_legal_watts = Gauge(
    "anker_device_mqtt_max_load_legal_watts",
    "Device max load legal from MQTT (W)",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_last_update_timestamp = Gauge(
    "anker_device_mqtt_last_update_timestamp",
    "Last update timestamp from MQTT",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_utc_timestamp = Gauge(
    "anker_device_mqtt_utc_timestamp",
    "UTC timestamp from MQTT",
    labelnames=["device_sn", "name"]
)
anker_device_mqtt_msg_timestamp = Gauge(
    "anker_device_mqtt_msg_timestamp",
    "Message timestamp from MQTT",
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


async def _poll_and_update_metrics(client: api.AnkerSolixApi, interval: int) -> None:
    """Continuously poll the API and update metrics."""
    # Site metrics labels: site_id, site_name
    # Device metrics labels: device_sn, site_id, type, name
    mqtt_devices = {}
    topics = set()
    trigger_devices = set()

    async def run_mqtt_loop():
        while True:
            try:
                # Export MQTT metrics
                for sn, dev in client.devices.items():
                    if sn in mqtt_devices:
                        d_labels = {
                            "device_sn": str(sn),
                            "name": str(dev.get("name") or dev.get("alias") or "noname"),
                        }
                        mqtt_data = mqtt_devices[sn].get_status() or {}

                        if mqtt_data:
                            # Log basic MQTT stats
                            if (
                                client.mqttsession 
                                and client.mqttsession.is_connected() 
                                and client.mqttsession.mqtt_stats
                            ):
                                CONSOLE.info(f"MQTT {client.mqttsession.mqtt_stats!s}")
                                try:
                                    CONSOLE.info(
                                        f"Received Messages : {json.dumps(client.mqttsession.mqtt_stats.dev_messages)}"
                                    )
                                except TypeError:
                                     # If dev_messages is not serializable (e.g. during tests with Mocks), log string representation
                                     CONSOLE.info(
                                        f"Received Messages : {client.mqttsession.mqtt_stats.dev_messages!s}"
                                    )

                            # Power metrics
                            mqtt_power_metrics = {
                                "photovoltaic": mqtt_data.get("photovoltaic_power"),
                                "output": mqtt_data.get("output_power"),
                                "battery_signed": mqtt_data.get("battery_power_signed"),
                                "ac_output_signed": mqtt_data.get("ac_output_power_signed"),
                                "grid_to_battery": mqtt_data.get("grid_to_battery_power"),
                                "grid_signed": mqtt_data.get("grid_power_signed"),
                                "home_demand": mqtt_data.get("home_demand"),
                                "pv_1": mqtt_data.get("pv_1_power"),
                                "pv_2": mqtt_data.get("pv_2_power"),
                                "pv_3": mqtt_data.get("pv_3_power"),
                                "pv_4": mqtt_data.get("pv_4_power"),
                                "pv_3rd_party": mqtt_data.get("pv_power_3rd_party"),
                                "grid_to_home": mqtt_data.get("grid_to_home_power"),
                                "pv_to_grid": mqtt_data.get("pv_to_grid_power"),
                                "heating": mqtt_data.get("heating_power"),
                            }
                            for p_type, p_val in mqtt_power_metrics.items():
                                if p_val is not None:
                                    p_labels = dict(d_labels)
                                    p_labels["type"] = p_type
                                    _set_gauge(anker_device_mqtt_power_watts, p_labels, p_val)

                            # Energy metrics
                            mqtt_energy_metrics = {
                                "charged": mqtt_data.get("charged_energy"),
                                "discharged": mqtt_data.get("discharged_energy"),
                                "grid_import": mqtt_data.get("grid_import_energy"),
                                "grid_export": mqtt_data.get("grid_export_energy"),
                                "home_consumption": mqtt_data.get("home_consumption"),
                                "pv_yield": mqtt_data.get("pv_yield"),
                                "output": mqtt_data.get("output_energy"),
                                "consumed": mqtt_data.get("consumed_energy"),
                            }
                            for e_type, e_val in mqtt_energy_metrics.items():
                                if e_val is not None:
                                    e_labels = dict(d_labels)
                                    e_labels["type"] = e_type
                                    _set_gauge(anker_device_mqtt_energy_total_kwh, e_labels, e_val)

                            _set_gauge(anker_device_mqtt_battery_soc_percent, d_labels, mqtt_data.get("battery_soc"))
                            _set_gauge(anker_device_mqtt_main_battery_soc_percent, d_labels, mqtt_data.get("main_battery_soc"))
                            _set_gauge(anker_device_mqtt_temperature_celsius, d_labels, mqtt_data.get("temperature"))
                            _set_gauge(anker_device_mqtt_battery_efficiency_percent, d_labels, mqtt_data.get("battery_efficiency"))
                            _set_gauge(anker_device_mqtt_device_efficiency_percent, d_labels, mqtt_data.get("device_efficiency"))
                            _set_gauge(anker_device_mqtt_wifi_signal_percent, d_labels, mqtt_data.get("wifi_signal"))
                            _set_gauge(anker_device_mqtt_home_load_preset_watts, d_labels, mqtt_data.get("home_load_preset"))
                            _set_gauge(anker_device_mqtt_max_load_watts, d_labels, mqtt_data.get("max_load"))
                            _set_gauge(anker_device_mqtt_max_load_legal_watts, d_labels, mqtt_data.get("max_load_legal"))
                            _set_gauge(anker_device_mqtt_utc_timestamp, d_labels, mqtt_data.get("utc_timestamp"))
                            _set_gauge(anker_device_mqtt_msg_timestamp, d_labels, mqtt_data.get("msg_timestamp"))

                            if mqtt_data.get("last_update"):
                                try:
                                    dt = datetime.strptime(mqtt_data["last_update"], "%Y-%m-%d %H:%M:%S")
                                    timestamp = dt.timestamp()
                                    _set_gauge(anker_device_mqtt_last_update_timestamp, d_labels, timestamp)
                                except Exception:
                                    pass
            except Exception as exc:
                CONSOLE.exception("MQTT loop error: %s", exc)
            await asyncio.sleep(15)

    # Start message poller to handle subscriptions and keepalives
    if client.mqttsession:
        asyncio.create_task(
            client.mqttsession.message_poller(topics=topics, trigger_devices=trigger_devices)
        )
    
    asyncio.create_task(run_mqtt_loop())

    while True:
        try:
            # Update caches
            await client.update_sites()
            await client.update_device_details(exclude={SolixDeviceType.VEHICLE.value, ApiCategories.device_auto_upgrade})
            await client.update_site_details(exclude={ApiCategories.account_info})
            await client.update_device_energy()

            # Update MQTT devices cache and poller sets
            for sn, dev in client.devices.items():
                if dev.get("mqtt_supported"):
                    if sn not in mqtt_devices:
                        if mdev := SolixMqttDeviceFactory(client, sn).create_device():
                            mqtt_devices[sn] = mdev
                    
                    # Add to poller sets
                    if client.mqttsession:
                        topic = f"{client.mqttsession.get_topic_prefix(dev)}#"
                        topics.add(topic)
                        trigger_devices.add(sn)

            # Export site metrics
            for site_id, site in client.sites.items():
                site_name = (
                    (site.get("site_info") or {}).get("site_name")
                ) or "Unknown"
                s_labels = {"site_id": str(site_id), "site_name": str(site_name)}

                sb_info = site.get("solarbank_info") or {}
                # sp_info = site.get("smart_plug_info") or {}

                # Combined site power metrics
                site_power_metrics = {
                    "home_load": site.get("home_load_power"),
                    "to_home_load": sb_info.get("to_home_load"),
                    "total_pv": sb_info.get("total_photovoltaic_power"),
                    "total_output": sb_info.get("total_output_power"),
                    "total_charging": sb_info.get("total_charging_power"),
                    "battery_discharge": sb_info.get("battery_discharge_power"),
                    # "smart_plugs_total": sp_info.get("total_power"),
                    "other_loads": site.get("other_loads_power"),
                    "retain_load_preset": site.get("retain_load"),
                }

                for p_type, p_val in site_power_metrics.items():
                    if p_val is not None:
                        p_labels = dict(s_labels)
                        p_labels["type"] = p_type
                        _set_gauge(anker_site_power_watts, p_labels, p_val)

                _set_gauge(anker_site_data_valid, s_labels, 1.0 if site.get("data_valid") else 0.0)

                total_battery_soc = sb_info.get("total_battery_power")
                if total_battery_soc is not None:
                    f = _as_float(total_battery_soc)
                    if f is not None:
                        _set_gauge(anker_site_total_battery_soc_percent, s_labels, f * 100.0)

                if sb_info.get("updated_time"):
                    try:
                        dt = datetime.strptime(sb_info["updated_time"], "%Y-%m-%d %H:%M:%S")
                        timestamp = dt.timestamp()
                        _set_gauge(anker_site_updated_timestamp_seconds, s_labels, timestamp)
                    except Exception:
                        pass

                for stat in site.get("statistics") or []:
                    if stat.get("type") == "1":
                        val = stat.get("total")
                        unit = str(stat.get("unit") or "").lower()
                        if val is not None:
                            f = _as_float(val)
                            if f is not None:
                                if unit == "wh":
                                    f = f / 1000.0
                                _set_gauge(anker_site_energy_produced_kwh_total, s_labels, f)
                    elif stat.get("type") == "3":
                        val = stat.get("total")
                        if val is not None:
                            f = _as_float(val)
                            if f is not None:
                                _set_gauge(anker_site_total_savings_money, s_labels, f)

                site_details = site.get("site_details") or {}
                if (price := site_details.get("price")) is not None:
                    price_labels = dict(s_labels)
                    price_labels.update(
                        {
                            "price_type": str(site_details.get("price_type") or "fixed"),
                            "unit": str(site_details.get("site_price_unit") or ""),
                        }
                    )
                    _set_gauge(anker_site_price, price_labels, price)

                energy_today = (site.get("energy_details") or {}).get("today") or {}
                for key, value in energy_today.items():
                    if key == "date" or "smartplug" in key:
                        continue
                    if value is not None:
                        f = _as_float(value)
                        if f is not None:
                            energy_labels = dict(s_labels)
                            energy_labels.update({"type": key})
                            if "percentage" in key:
                                _set_gauge(anker_site_energy_today_percent, energy_labels, f)
                            else:
                                _set_gauge(anker_site_energy_today_kwh_total, energy_labels, f)

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

                # Combined power metrics
                power_metrics = {
                    "input": dev.get("input_power"),
                    "output": dev.get("output_power"),
                    "charging": dev.get("charging_power"),
                    "battery_charge": dev.get("bat_charge_power"),
                    "generate": dev.get("generate_power"),
                    "micro_inverter": dev.get("micro_inverter_power"),
                    "micro_inverter_limit": dev.get("micro_inverter_power_limit") or dev.get("preset_inverter_limit"),
                    "grid_import": dev.get("grid_to_home_power"),
                    "grid_export": dev.get("photovoltaic_to_grid_power"),
                    "current": dev.get("current_power"),
                    "ac": dev.get("ac_power"),
                    "other_input": dev.get("other_input_power"),
                    "micro_inverter_low_limit": dev.get("micro_inverter_low_power_limit"),
                    "grid_to_battery": dev.get("grid_to_battery_power"),
                    "pei_heating": dev.get("pei_heating_power"),
                    "set_output": dev.get("set_output_power"),
                    "set_system_output": dev.get("set_system_output_power"),
                }

                for p_type, p_val in power_metrics.items():
                    if p_val is not None:
                        p_labels = dict(d_labels)
                        p_labels["type"] = p_type
                        _set_gauge(anker_device_power_watts, p_labels, p_val)

                pv_names = dev.get("pv_name") or {}
                for panel_idx in range(1, 5):
                    solar_key = f"solar_power_{panel_idx}"
                    if dev.get(solar_key) is not None:
                        panel_labels = dict(d_labels)

                        name_key = f"pv{panel_idx}_name"
                        pv_name = None
                        if isinstance(pv_names, dict):
                            pv_name = pv_names.get(name_key)
                        else:
                            pv_name = getattr(pv_names, name_key, None)

                        panel_labels["pv"] = pv_name or str(panel_idx)
                        _set_gauge(anker_device_pv_power_watts, panel_labels, dev.get(solar_key))

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

                charging_labels = dict(d_labels)
                charging_labels["desc"] = str(dev.get("charging_status_desc") or "")
                _set_gauge(anker_device_charging_status, charging_labels, dev.get("charging_status"))

                _set_gauge(anker_device_grid_status_code, d_labels, dev.get("grid_status"))
                _set_gauge(
                    anker_device_data_valid,
                    d_labels,
                    (1.0 if dev.get("data_valid") else 0.0) if dev.get("data_valid") is not None else None
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

    usr = user()
    pwd = password()
    ctry = country()

    async with ClientSession() as websession:
        CONSOLE.info("Authenticating to Anker Cloud for user %s...", usr)
        client = api.AnkerSolixApi(usr, pwd, ctry, websession, CONSOLE)
        try:
            if await client.async_authenticate():
                CONSOLE.info("Authentication: OK")
            else:
                CONSOLE.info("Authentication: CACHED (will validate on first call)")
        except (ClientError, errors.AnkerSolixError) as err:
            CONSOLE.error("Authentication failed: %s: %s", type(err), err)

        CONSOLE.info("Starting MQTT session...")
        await client.startMqttSession()

        await _poll_and_update_metrics(client, interval)


if __name__ == "__main__":
    try:
        asyncio.run(_run(), debug=False)
    except KeyboardInterrupt:
        CONSOLE.warning("Exporter aborted by user")
    except Exception as exc:  # noqa: BLE001
        CONSOLE.exception("%s: %s", type(exc), exc)
