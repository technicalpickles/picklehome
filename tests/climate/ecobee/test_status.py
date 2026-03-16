from climate.ecobee.status import (
    decode_temp,
    get_equipment_description,
    get_active_hold,
    extract_thermostat_status,
)


def test_decode_temp_converts_tenths():
    assert decode_temp(704) == 70.4
    assert decode_temp(679) == 67.9


def test_decode_temp_returns_none_for_sentinel():
    assert decode_temp(-5002) is None
    assert decode_temp(0) is None  # rawTemperature=0 means not available


def test_get_equipment_description_idle():
    assert get_equipment_description("") == "idle"


def test_get_equipment_description_running():
    assert get_equipment_description("heatPump") == "heatPump"
    assert get_equipment_description("compCool1,fan") == "compCool1,fan"


def test_get_active_hold_returns_none_when_no_events():
    assert get_active_hold([]) is None


def test_get_active_hold_returns_none_when_no_running_hold():
    events = [{"type": "hold", "running": False, "name": "hold"}]
    assert get_active_hold(events) is None


def test_get_active_hold_returns_running_hold():
    events = [
        {
            "type": "hold",
            "running": True,
            "name": "auto",
            "endDate": "2026-03-17",
            "endTime": "10:00:00",
            "isIndefinite": False,
            "coolHoldTemp": 740,
            "heatHoldTemp": 690,
        }
    ]
    hold = get_active_hold(events)
    assert hold is not None
    assert hold["end"] == "2026-03-17 10:00:00"
    assert hold["cool_temp"] == 74.0
    assert hold["heat_temp"] == 69.0


def test_get_active_hold_indefinite():
    events = [
        {
            "type": "hold",
            "running": True,
            "name": "hold",
            "endDate": "2028-12-29",
            "endTime": "08:51:45",
            "isIndefinite": True,
            "coolHoldTemp": 600,
            "heatHoldTemp": 550,
        }
    ]
    hold = get_active_hold(events)
    assert hold["end"] == "indefinite"


def test_extract_thermostat_status():
    thermostat = {
        "name": "Downstairs",
        "runtime": {
            "actualTemperature": 704,
            "actualHumidity": 58,
            "actualAQScore": 51,
            "actualVOC": 520,
            "actualCO2": 508,
        },
        "equipmentStatus": "",
        "settings": {"hvacMode": "heat"},
        "events": [],
        "program": {"currentClimateRef": "smart1"},
        "weather": {
            "forecasts": [
                {
                    "temperature": 614,
                    "condition": "Rain",
                    "relativeHumidity": 89,
                    "windSpeed": 13,
                    "windDirection": "SW",
                }
            ]
        },
    }
    status = extract_thermostat_status(thermostat)
    assert status["temp"] == 70.4
    assert status["humidity"] == 58
    assert status["equipment"] == "idle"
    assert status["hvac_mode"] == "heat"
    assert status["climate_ref"] == "smart1"
    assert status["hold"] is None
    assert status["aq_score"] == 51
    assert status["voc"] == 520
    assert status["co2"] == 508
