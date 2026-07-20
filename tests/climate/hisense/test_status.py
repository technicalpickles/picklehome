from climate.hisense.client import HisenseUnit
from climate.hisense.status import format_status


def _unit(**overrides):
    base = dict(
        puid="p1",
        name="Downstairs AC",
        room="Downstairs",
        offline_state=1,
        power=True,
        mode="cool",
        target_temp=72,
        current_temp=75,
        humidity=45,
        fan="auto",
        faults=[],
    )
    base.update(overrides)
    return HisenseUnit(**base)


def test_empty():
    assert format_status([]) == "No Hisense units found."


def test_online_unit_shows_mode_and_temps():
    out = format_status([_unit()])
    assert "Downstairs AC  [Downstairs]" in out
    assert "cool" in out
    assert "set 72°F" in out
    assert "current 75°F" in out
    assert "humidity 45%" in out
    # offlineState is not an availability signal, so it is never rendered.
    assert "Offline" not in out


def test_power_off_hides_mode():
    out = format_status([_unit(power=False)])
    assert "off" in out
    # setpoint still shown even when off
    assert "set 72°F" in out


def test_faults_rendered():
    out = format_status([_unit(faults=["waterfull", "inwifi"])])
    assert "Faults: waterfull, inwifi" in out


def test_missing_temp_renders_placeholder():
    out = format_status([_unit(target_temp=None, current_temp=None, humidity=None)])
    assert "set ?" in out
    assert "current" not in out
    assert "humidity" not in out
