from climate.ecobee.comforts import build_new_climate

TEMPLATE = {
    "name": "Comfort Cool", "climateRef": "smart1", "owner": "user", "type": "customActivity",
    "heatTemp": 690, "coolTemp": 740, "coolFan": "auto", "sensors": [{"id": "rs:1"}],
}
SLEEP = {"climateRef": "sleep", "sensors": [{"id": "rs:2"}, {"id": "ei:0"}]}


def test_drops_ref_and_sets_name_and_temps_in_tenths():
    new = build_new_climate(TEMPLATE, SLEEP, "Sleep Cool", 67, 72)
    assert "climateRef" not in new
    assert (new["name"], new["heatTemp"], new["coolTemp"]) == ("Sleep Cool", 670, 720)


def test_keeps_template_fields_and_takes_sensors_from_source():
    new = build_new_climate(TEMPLATE, SLEEP, "Sleep Cool", 67, 72)
    assert new["owner"] == "user" and new["coolFan"] == "auto"
    assert new["sensors"] == SLEEP["sensors"]


def test_does_not_mutate_inputs():
    build_new_climate(TEMPLATE, SLEEP, "Sleep Cool", 67, 72)
    assert TEMPLATE["climateRef"] == "smart1" and TEMPLATE["name"] == "Comfort Cool"
