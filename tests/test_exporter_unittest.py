import asyncio
import unittest
from unittest import mock

import exporter


def _extract_metric_call(call):
    """Extract (name, labels, value) from a mock call to _set_metric supporting positional/keyword args."""
    name = None
    labels = None
    value = None
    # name is always positional 0 in current code
    if call.args:
        name = call.args[0]
    # labels can be kw or 3rd positional (index 2)
    if "labels" in call.kwargs:
        labels = call.kwargs["labels"]
    elif len(call.args) >= 3:
        labels = call.args[2]
    # value can be kw or 4th positional (index 3)
    if "value" in call.kwargs:
        value = call.kwargs["value"]
    elif len(call.args) >= 4:
        value = call.args[3]
    return name, labels or {}, value


def _any_metric(spy, metric_name, label_pred=None, value_pred=None):
    for call in spy.mock_calls:
        if not isinstance(call, mock._Call):
            continue
        name, labels, value = _extract_metric_call(call)
        if name != metric_name:
            continue
        if label_pred and not label_pred(labels):
            continue
        if value_pred:
            parsed = exporter._as_float(value)
            vv = parsed if parsed is not None else value
            try:
                if not value_pred(vv):
                    continue
            except Exception:  # keep robust in tests
                continue
        return True
    return False


class TestAsFloat(unittest.TestCase):
    def test_as_float_with_numbers(self):
        self.assertEqual(exporter._as_float(0), 0.0)
        self.assertEqual(exporter._as_float(12), 12.0)
        self.assertEqual(exporter._as_float(12.5), 12.5)

    def test_as_float_with_strings_and_units(self):
        self.assertEqual(exporter._as_float("100"), 100.0)
        self.assertEqual(exporter._as_float("100 W"), 100.0)
        self.assertEqual(exporter._as_float("  75%  "), 75.0)
        self.assertEqual(exporter._as_float("-5"), -5.0)

    def test_as_float_with_placeholders(self):
        for v in (None, "", "-", "--", "---", "----"):
            self.assertIsNone(exporter._as_float(v))

    def test_as_float_with_invalid(self):
        self.assertIsNone(exporter._as_float(object()))
        self.assertIsNone(exporter._as_float("abc"))


class TestSetMetric(unittest.TestCase):
    def test_set_metric_sets_value_with_labels(self):
        # Use a unique metric name to avoid conflicts across test runs
        name = "test_exporter_metric_value_watts"
        labels = {"x": "a", "y": "b"}
        exporter._set_metric(name, "desc", labels, "123 W")

        # Retrieve gauge and assert value through public labels() handle
        gauge = exporter._get_gauge(name, "desc", tuple(labels.keys()))
        self.assertEqual(gauge.labels(**labels)._value.get(), 123.0)


class TestPollAndUpdateMetrics(unittest.IsolatedAsyncioTestCase):
    async def test_poll_updates_metrics_once(self):
        # Prepare a fake API client
        class FakeClient:
            def __init__(self):
                self.sites = {
                    "site123": {
                        "site_info": {"site_name": "Home"},
                        "home_load_power": "250 W",
                        "solarbank_info": {
                            "to_home_load": "120",
                            "total_battery_power": 0.5,
                            "total_photovoltaic_power": "300",
                            "total_output_power": "200",
                            "total_charging_power": "-50",
                            "battery_discharge_power": "75",
                            "sb_cascaded": True,
                        },
                        "smart_plug_info": {"total_power": 30},
                        "other_loads_power": "15",
                        "retain_load": "350 W",
                        "data_valid": True,
                    }
                }
                self.devices = {
                    "devA": {
                        "site_id": "site123",
                        "type": "solarbank",
                        "name": "SB2",
                        "device_pn": "A123",
                        "generation": 2,
                        "sw_version": "1.2.3",
                        "battery_soc": "80%",
                        "battery_energy": 500,
                        "input_power": "100 W",
                        "output_power": 50,
                        "charging_power": -20,
                        "bat_charge_power": 20,
                        "generate_power": 200,
                        "micro_inverter_power": 180,
                        "micro_inverter_power_limit": 600,
                        "solar_power_1": 50,
                        "solar_power_2": 60,
                        "solar_power_3": 70,
                        "solar_power_4": 80,
                        "ac_power": 150,
                        "other_input_power": 10,
                        "micro_inverter_low_power_limit": 100,
                        "grid_to_battery_power": 25,
                        "grid_to_home_power": 100,
                        "photovoltaic_to_grid_power": 0,
                        "pei_heating_power": 5,
                        "set_output_power": 400,
                        "set_system_output_power": 800,
                        "wifi_signal": "70",
                        "rssi": -60,
                        "wifi_online": True,
                        "wired_connected": False,
                        "status": "1",
                        "charging_status": "2",
                        "grid_status": "3",
                        "data_valid": True,
                        "is_ota_update": False,
                        "auto_upgrade": True,
                        "battery_capacity": 1600,
                        "sub_package_num": 2,
                        "current_power": "",
                        "energy_today": "1.5",
                    }
                }
                # Async methods that do nothing
                self.update_sites = mock.AsyncMock(return_value={})
                self.update_device_details = mock.AsyncMock(return_value={})
                self.update_site_details = mock.AsyncMock(return_value={})

        fake = FakeClient()

        # Spy on _set_metric while executing real function
        with mock.patch.object(exporter, "_set_metric", wraps=exporter._set_metric) as spy:
            # Run only one iteration by timing out during sleep
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(exporter._poll_and_update_metrics(fake, interval=0), timeout=0.02)

            # Ensure we called the update methods
            fake.update_sites.assert_awaited()
            fake.update_device_details.assert_awaited()
            fake.update_site_details.assert_awaited()

            # Site metrics
            self.assertTrue(
                _any_metric(
                    spy,
                    "anker_site_home_load_power_watts",
                    label_pred=lambda l: l.get("site_id") == "site123",
                )
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_to_home_load_power_watts", label_pred=lambda l: l.get("site_id") == "site123")
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_total_pv_power_watts", value_pred=lambda v: float(v) == 300.0)
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_total_output_power_watts", value_pred=lambda v: float(v) == 200.0)
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_total_charging_power_watts", value_pred=lambda v: float(v) == -50.0)
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_battery_discharge_power_watts", value_pred=lambda v: float(v) == 75.0)
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_solarbanks_cascaded", value_pred=lambda v: float(v) == 1.0)
            )
            self.assertTrue(
                _any_metric(spy, "anker_site_retain_load_preset_watts", value_pred=lambda v: float(v) == 350.0)
            )
            self.assertTrue(
                _any_metric(
                    spy,
                    "anker_site_total_battery_soc_percent",
                    value_pred=lambda v: abs(float(v) - 50.0) < 1e-6,
                )
            )

            # Device metrics: info with sw_version label
            self.assertTrue(
                _any_metric(
                    spy,
                    "anker_device_info",
                    label_pred=lambda l: l.get("device_sn") == "devA" and l.get("sw_version") == "1.2.3",
                )
            )

            # Device power/energy and PV strings
            for i, expected in enumerate([50, 60, 70, 80], start=1):
                self.assertTrue(
                    _any_metric(
                        spy,
                        f"anker_device_solar_power_{i}_watts",
                        label_pred=lambda l: l.get("device_sn") == "devA",
                        value_pred=lambda v, e=expected: float(v) == float(e),
                    )
                )
            self.assertTrue(_any_metric(spy, "anker_device_ac_port_power_watts", value_pred=lambda v: float(v) == 150.0))
            self.assertTrue(_any_metric(spy, "anker_device_other_input_power_watts", value_pred=lambda v: float(v) == 10.0))
            self.assertTrue(
                _any_metric(
                    spy, "anker_device_micro_inverter_low_power_limit_watts", value_pred=lambda v: float(v) == 100.0
                )
            )
            self.assertTrue(_any_metric(spy, "anker_device_grid_to_battery_power_watts", value_pred=lambda v: float(v) == 25.0))
            self.assertTrue(_any_metric(spy, "anker_device_pei_heating_power_watts", value_pred=lambda v: float(v) == 5.0))

            # Presets
            self.assertTrue(_any_metric(spy, "anker_device_set_output_power_watts", value_pred=lambda v: float(v) == 400.0))
            self.assertTrue(_any_metric(spy, "anker_device_set_system_output_power_watts", value_pred=lambda v: float(v) == 800.0))

            # Connectivity
            self.assertTrue(_any_metric(spy, "anker_device_wifi_signal_percent", value_pred=lambda v: float(v) == 70.0))
            self.assertTrue(_any_metric(spy, "anker_device_wifi_rssi_dbm", value_pred=lambda v: float(v) == -60.0))
            self.assertTrue(_any_metric(spy, "anker_device_wifi_online", value_pred=lambda v: float(v) == 1.0))
            self.assertTrue(_any_metric(spy, "anker_device_wired_connected", value_pred=lambda v: float(v) == 0.0))

            # Status/flags
            self.assertTrue(_any_metric(spy, "anker_device_status_code"))
            self.assertTrue(_any_metric(spy, "anker_device_charging_status_code"))
            self.assertTrue(_any_metric(spy, "anker_device_grid_status_code"))
            self.assertTrue(_any_metric(spy, "anker_device_data_valid", value_pred=lambda v: float(v) == 1.0))
            self.assertTrue(_any_metric(spy, "anker_device_is_ota_update", value_pred=lambda v: float(v) == 0.0))
            self.assertTrue(_any_metric(spy, "anker_device_auto_upgrade", value_pred=lambda v: float(v) == 1.0))

            # Capacity/counters
            self.assertTrue(_any_metric(spy, "anker_device_battery_capacity_wh", value_pred=lambda v: float(v) == 1600.0))
            self.assertTrue(_any_metric(spy, "anker_device_sub_package_num", value_pred=lambda v: float(v) == 2.0))


if __name__ == "__main__":
    unittest.main()
