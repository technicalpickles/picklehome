import time
from unittest.mock import AsyncMock, patch
import pytest

from climate.ambient.client import (
    is_temp_plausible,
    is_data_fresh,
    get_data_age_minutes,
    get_outdoor_temp_from_stations,
    discover_stations_sync,
    load_weather_config,
    get_configured_macs,
)

# --- is_temp_plausible ---

def test_plausible_temp_passes():
    assert is_temp_plausible(45.0) is True

def test_implausible_low_temp():
    assert is_temp_plausible(-99.0) is False

def test_implausible_high_temp():
    assert is_temp_plausible(150.0) is False

def test_boundary_min_plausible():
    assert is_temp_plausible(-20.0) is True

def test_boundary_max_plausible():
    assert is_temp_plausible(120.0) is True

# --- is_data_fresh ---

def test_fresh_data():
    last_data = {"dateutc": int(time.time() * 1000) - 60_000}  # 1 minute ago
    assert is_data_fresh(last_data) is True

def test_stale_data():
    last_data = {"dateutc": int(time.time() * 1000) - 3_600_000}  # 1 hour ago
    assert is_data_fresh(last_data) is False

def test_missing_timestamp():
    assert is_data_fresh({}) is False

def test_custom_max_age():
    last_data = {"dateutc": int(time.time() * 1000) - 600_000}  # 10 minutes ago
    assert is_data_fresh(last_data, max_age_minutes=5) is False
    assert is_data_fresh(last_data, max_age_minutes=15) is True

# --- get_data_age_minutes ---

def test_get_data_age_minutes_recent():
    last_data = {"dateutc": int(time.time() * 1000) - 120_000}  # 2 minutes ago
    age = get_data_age_minutes(last_data)
    assert age is not None
    assert 1.5 < age < 2.5

def test_get_data_age_minutes_missing_timestamp():
    assert get_data_age_minutes({}) is None

def test_get_data_age_minutes_old():
    last_data = {"dateutc": int(time.time() * 1000) - 3_600_000}  # 1 hour ago
    age = get_data_age_minutes(last_data)
    assert age is not None
    assert age > 55

# --- get_outdoor_temp_from_stations ---

def test_get_outdoor_temp_returns_first_valid():
    # Returns (mac, temp, age) tuples; None for failures
    with patch("climate.ambient.client._fetch_all_temps",
               new=AsyncMock(return_value=[None, ("BB", 52.3, 4.0), ("CC", 48.0, 2.0)])):
        result = get_outdoor_temp_from_stations(["A", "B", "C"])
    assert result == ("BB", 52.3, 4.0)

def test_get_outdoor_temp_returns_none_when_all_fail():
    with patch("climate.ambient.client._fetch_all_temps",
               new=AsyncMock(return_value=[None, None])):
        result = get_outdoor_temp_from_stations(["A", "B"])
    assert result is None

def test_get_outdoor_temp_empty_macs():
    assert get_outdoor_temp_from_stations([]) is None

# --- discover_stations_sync ---

def test_discover_returns_outdoor_stations():
    outdoor = {"macAddress": "A", "info": {"indoor": False}, "lastData": {"tempf": 50.0}}
    with patch("climate.ambient.client._discover", new=AsyncMock(return_value=[outdoor])):
        result = discover_stations_sync(33.0, -84.0, 1.0)
    assert len(result) == 1
    assert result[0]["macAddress"] == "A"

# --- load_weather_config ---

def test_load_weather_config_valid(tmp_path):
    cfg = tmp_path / "weather.yaml"
    cfg.write_text("stations:\n  - mac: AA:BB\nthresholds:\n  heat_below: 60\n  cool_above: 65\n")
    result = load_weather_config(cfg)
    assert result["thresholds"]["heat_below"] == 60

def test_load_weather_config_empty(tmp_path):
    cfg = tmp_path / "weather.yaml"
    cfg.write_text("")
    assert load_weather_config(cfg) == {}

def test_load_weather_config_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        load_weather_config(tmp_path / "nonexistent.yaml")

# --- get_configured_macs ---

def test_get_configured_macs():
    config = {"stations": [{"mac": "AA:BB"}, {"name": "no-mac"}, {"mac": "CC:DD"}]}
    assert get_configured_macs(config) == ["AA:BB", "CC:DD"]

def test_get_configured_macs_empty():
    assert get_configured_macs({}) == []
