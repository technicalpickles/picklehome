import pytest
from climate.ecobee.thermostats import (
    get_managed_thermostats,
    get_thermostat_id,
)

REGISTRY = {
    "thermostats": {
        "downstairs": {"thermostat_id": "111", "managed": True},
        "upstairs": {"thermostat_id": "222", "managed": True},
        "cottage": {"thermostat_id": "333", "managed": False},
    }
}


def test_get_managed_thermostats_returns_only_managed():
    result = get_managed_thermostats(REGISTRY)
    names = [name for name, _ in result]
    assert "downstairs" in names
    assert "upstairs" in names
    assert "cottage" not in names


def test_get_managed_thermostats_returns_ids():
    result = get_managed_thermostats(REGISTRY)
    by_name = dict(result)
    assert by_name["downstairs"] == "111"
    assert by_name["upstairs"] == "222"


def test_get_thermostat_id_returns_id():
    assert get_thermostat_id(REGISTRY, "downstairs") == "111"


def test_get_thermostat_id_raises_for_unknown():
    with pytest.raises(KeyError):
        get_thermostat_id(REGISTRY, "nonexistent")
