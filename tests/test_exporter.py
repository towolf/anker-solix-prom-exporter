import asyncio
import pytest
from anker_solix_prom_exporter import exporter

from api import api


class FakeClient(api.AnkerSolixApi):
    def __init__(self, mocker):
        super().__init__("fake@me.io", "pa$$w0rd", "DE")
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
        self.update_sites = mocker.AsyncMock(return_value={})
        self.update_device_details = mocker.AsyncMock(return_value={})
        self.update_site_details = mocker.AsyncMock(return_value={})


@pytest.fixture
def poll_ctx(mocker):
    fake = FakeClient(mocker)
    spy = mocker.patch.object(exporter, "_set_gauge", wraps=exporter._set_gauge)
    # Run one poll iteration
    try:
        asyncio.run(
            asyncio.wait_for(
                exporter._poll_and_update_metrics(fake, interval=0), timeout=0.02
            )
        )
    except asyncio.TimeoutError:
        pass
    return fake, spy


def _extract_metric_call(call):
    """Extract (gauge, labels, value) from a mock call to _set_gauge supporting positional/keyword args."""
    # Get args and kwargs, handling both call types
    args = getattr(call, "args", ())
    kwargs = getattr(call, "kwargs", {})

    # Extract gauge (always first positional)
    gauge = args[0] if args else None

    # Extract labels (keyword or 2nd positional)
    labels = kwargs.get("labels", args[1] if len(args) >= 2 else {})

    # Extract value (keyword or 3rd positional)
    value = kwargs.get("value", args[2] if len(args) >= 3 else None)

    return gauge, labels, value


def _any_metric(spy, metric_name, label_pred=None, value_pred=None):
    """Check if any metric call matches the given criteria."""
    for call in spy.mock_calls:
        gauge, labels, value = _extract_metric_call(call)

        if gauge is None or gauge._name != metric_name:
            continue

        if label_pred and not label_pred(labels):
            continue

        if value_pred:
            parsed_value = exporter._as_float(value)
            test_value = parsed_value if parsed_value is not None else value
            if not value_pred(test_value):
                continue

        return True
    return False


@pytest.mark.parametrize("value,expected", [(0, 0.0), (12, 12.0), (12.5, 12.5)])
def test_as_float_numbers_param(value, expected):
    assert exporter._as_float(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("100", 100.0),
        ("100 W", 100.0),
        ("  75%  ", 75.0),
        ("-5", -5.0),
    ],
)
def test_as_float_strings_and_units_param(value, expected):
    assert exporter._as_float(value) == expected


@pytest.mark.parametrize("value", [None, "", "-", "--", "---", "----"])
def test_as_float_placeholders_param(value):
    assert exporter._as_float(value) is None


@pytest.mark.parametrize("value", [object(), "abc"])
def test_as_float_invalid_param(value):
    assert exporter._as_float(value) is None


def test_set_gauge_sets_value_with_labels():
    # Use a metric that exists
    labels = {"site_id": "test", "site_name": "Test"}
    exporter._set_gauge(exporter.anker_site_home_load_power_watts, labels, "123 W")

    # Assert value through public labels() handle
    assert exporter.anker_site_home_load_power_watts.labels(**labels)._value.get() == 123.0


# The previous monolithic poll test is replaced by parametrized, single-assert tests below.


@pytest.mark.parametrize(
    "attr", ["update_sites", "update_device_details", "update_site_details"]
)
def test_poll_updates_called_param(poll_ctx, attr):
    fake, _ = poll_ctx
    assert getattr(fake, attr).await_count >= 1


_metric_cases = [
    # Site metrics
    (
        "anker_site_home_load_power_watts",
        lambda l: l.get("site_id") == "site123" and l.get("site_name") == "Home",
        None,
    ),
    (
        "anker_site_to_home_load_power_watts",
        lambda l: l.get("site_id") == "site123",
        None,
    ),
    ("anker_site_total_pv_power_watts", None, lambda v: float(v) == 300.0),
    ("anker_site_total_output_power_watts", None, lambda v: float(v) == 200.0),
    ("anker_site_total_charging_power_watts", None, lambda v: float(v) == -50.0),
    ("anker_site_battery_discharge_power_watts", None, lambda v: float(v) == 75.0),
    ("anker_site_smart_plugs_total_power_watts", None, lambda v: float(v) == 30.0),
    ("anker_site_other_loads_power_watts", None, lambda v: float(v) == 15.0),
    ("anker_site_retain_load_preset_watts", None, lambda v: float(v) == 350.0),
    ("anker_site_data_valid", None, lambda v: float(v) == 1.0),
    (
        "anker_site_total_battery_soc_percent",
        None,
        lambda v: abs(float(v) - 50.0) < 1e-6,
    ),
    # Device info
    (
        "anker_device_info",
        lambda l: l.get("device_sn") == "devA" and l.get("sw_version") == "1.2.3",
        None,
    ),
    # Device base power/energy metrics
    ("anker_device_battery_soc_percent", None, lambda v: float(v) == 80.0),
    ("anker_device_battery_energy_wh", None, lambda v: float(v) == 500.0),
    ("anker_device_input_power_watts", None, lambda v: float(v) == 100.0),
    ("anker_device_output_power_watts", None, lambda v: float(v) == 50.0),
    ("anker_device_battery_power_watts", None, lambda v: float(v) == -20.0),
    ("anker_device_bat_charge_power_watts", None, lambda v: float(v) == 20.0),
    # Inverter/micro-inverter
    ("anker_device_ac_power_watts", None, lambda v: float(v) == 200.0),
    ("anker_device_micro_inverter_power_watts", None, lambda v: float(v) == 180.0),
    (
        "anker_device_micro_inverter_power_limit_watts",
        None,
        lambda v: float(v) == 600.0,
    ),
    # Smart meter
    ("anker_device_grid_import_power_watts", None, lambda v: float(v) == 100.0),
    ("anker_device_grid_export_power_watts", None, lambda v: float(v) == 0.0),
    # Smart plug
    ("anker_device_plug_power_watts", None, None),
    ("anker_device_energy_today_kwh", None, lambda v: float(v) == 1.5),
    # PV strings and additional power metrics
    (
        "anker_device_solar_power_watts",
        lambda l: l.get("device_sn") == "devA" and l.get("panel") == "1",
        lambda v: float(v) == 50.0,
    ),
    (
        "anker_device_solar_power_watts",
        lambda l: l.get("device_sn") == "devA" and l.get("panel") == "2",
        lambda v: float(v) == 60.0,
    ),
    (
        "anker_device_solar_power_watts",
        lambda l: l.get("device_sn") == "devA" and l.get("panel") == "3",
        lambda v: float(v) == 70.0,
    ),
    (
        "anker_device_solar_power_watts",
        lambda l: l.get("device_sn") == "devA" and l.get("panel") == "4",
        lambda v: float(v) == 80.0,
    ),
    ("anker_device_ac_port_power_watts", None, lambda v: float(v) == 150.0),
    ("anker_device_other_input_power_watts", None, lambda v: float(v) == 10.0),
    (
        "anker_device_micro_inverter_low_power_limit_watts",
        None,
        lambda v: float(v) == 100.0,
    ),
    ("anker_device_grid_to_battery_power_watts", None, lambda v: float(v) == 25.0),
    ("anker_device_pei_heating_power_watts", None, lambda v: float(v) == 5.0),
    # Presets
    ("anker_device_set_output_power_watts", None, lambda v: float(v) == 400.0),
    ("anker_device_set_system_output_power_watts", None, lambda v: float(v) == 800.0),
    # Connectivity
    ("anker_device_wifi_signal_percent", None, lambda v: float(v) == 70.0),
    ("anker_device_wifi_rssi_dbm", None, lambda v: float(v) == -60.0),
    ("anker_device_wifi_online", None, lambda v: float(v) == 1.0),
    ("anker_device_wired_connected", None, lambda v: float(v) == 0.0),
    # Status/flags
    ("anker_device_status_code", None, None),
    ("anker_device_charging_status_code", None, None),
    ("anker_device_grid_status_code", None, None),
    ("anker_device_data_valid", None, lambda v: float(v) == 1.0),
    ("anker_device_is_ota_update", None, lambda v: float(v) == 0.0),
    ("anker_device_auto_upgrade", None, lambda v: float(v) == 1.0),
    # Capacity/counters
    ("anker_device_battery_capacity_wh", None, lambda v: float(v) == 1600.0),
    ("anker_device_sub_package_num", None, lambda v: float(v) == 2.0),
]


@pytest.mark.parametrize("metric_name,label_pred,value_pred", _metric_cases)
def test_metrics_emitted_param(poll_ctx, metric_name, label_pred, value_pred):
    _, spy = poll_ctx
    assert _any_metric(spy, metric_name, label_pred, value_pred)
