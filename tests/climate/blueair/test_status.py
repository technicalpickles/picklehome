from climate.blueair.status import _c_to_f, format_status


def test_c_to_f_conversion():
    assert _c_to_f(22) == 72
    assert _c_to_f(0) == 32
    assert _c_to_f(None) is None


def test_format_status_basic():
    statuses = [
        {
            "name": "Living Room",
            "model": "Blueair Blue Pure 411i Max",
            "pm1": 5,
            "pm2_5": 8,
            "pm10": 12,
            "total_voc": 120,
            "voc": None,
            "temperature": 22,
            "humidity": 45,
            "fan_speed": 42,
            "fan_auto_mode": True,
            "standby": False,
            "night_mode": False,
            "germ_shield": None,
            "brightness": 0,
            "child_lock": False,
            "filter_usage_percentage": 78,
            "wifi_working": True,
        }
    ]
    output = format_status(statuses)
    assert "Living Room" in output
    assert "411i Max" in output
    assert "PM2.5 8" in output
    assert "PM1 5" in output
    assert "PM10 12" in output
    assert "VOC 120" in output
    assert "72°F" in output  # 22°C -> 72°F
    assert "45% humidity" in output
    assert "Auto" in output
    assert "speed 42%" in output
    assert "78% remaining" in output
    assert "LED: off" in output
    # child_lock is False, germ_shield is None, neither should appear
    assert "Child Lock" not in output
    assert "Germ Shield" not in output


def test_format_status_standby():
    statuses = [
        {
            "name": "Bedroom",
            "model": "Blueair Blue Pure 411i Max",
            "pm1": None,
            "pm2_5": None,
            "pm10": None,
            "total_voc": None,
            "voc": None,
            "temperature": None,
            "humidity": None,
            "fan_speed": 0,
            "fan_auto_mode": False,
            "standby": True,
            "night_mode": False,
            "germ_shield": None,
            "brightness": 0,
            "child_lock": False,
            "filter_usage_percentage": 50,
            "wifi_working": True,
        }
    ]
    output = format_status(statuses)
    assert "Bedroom" in output
    assert "Standby" in output
    # Standby should skip sensors and fan
    assert "Air Quality" not in output
    assert "Environment" not in output
    assert "Fan" not in output
    # Filter should still show
    assert "50% remaining" in output


def test_format_status_none_sensors_omitted():
    """Sensors that are None should not appear in output."""
    statuses = [
        {
            "name": "Test",
            "model": "Blueair Blue Pure 411i Max",
            "pm1": None,
            "pm2_5": 5,
            "pm10": None,
            "total_voc": None,
            "voc": None,
            "temperature": None,
            "humidity": None,
            "fan_speed": 50,
            "fan_auto_mode": False,
            "standby": False,
            "night_mode": False,
            "germ_shield": None,
            "brightness": 3,
            "child_lock": False,
            "filter_usage_percentage": 90,
            "wifi_working": True,
        }
    ]
    output = format_status(statuses)
    assert "PM2.5 5" in output
    assert "PM1" not in output
    assert "PM10" not in output
    assert "VOC" not in output
    assert "Environment" not in output  # no temp or humidity
    assert "LED: 3" in output
