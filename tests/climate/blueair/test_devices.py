import pytest
import yaml

from climate.blueair.devices import (
    DEFAULT_PURIFIERS_PATH,
    get_managed_purifiers,
    load_purifiers,
)


def test_default_path_points_to_config_dir():
    assert DEFAULT_PURIFIERS_PATH.name == "purifiers.yaml"
    assert DEFAULT_PURIFIERS_PATH.parent.name == "config"


def test_load_purifiers_reads_valid_yaml(tmp_path):
    p = tmp_path / "purifiers.yaml"
    data = {
        "purifiers": {
            "Living Room": {"uuid": "abc123", "managed": True},
            "Bedroom": {"uuid": "def456", "managed": False},
        }
    }
    p.write_text(yaml.dump(data))
    result = load_purifiers(p)
    assert result == data


def test_get_managed_purifiers_filters_correctly():
    data = {
        "purifiers": {
            "Living Room": {"uuid": "abc123", "managed": True},
            "Bedroom": {"uuid": "def456", "managed": False},
            "Office": {"uuid": "ghi789", "managed": True},
        }
    }
    result = get_managed_purifiers(data)
    assert result == [("Living Room", "abc123"), ("Office", "ghi789")]


def test_load_purifiers_exits_on_missing_file(tmp_path):
    p = tmp_path / "nonexistent.yaml"
    with pytest.raises(SystemExit):
        load_purifiers(p)


def test_load_purifiers_exits_on_empty_file(tmp_path):
    p = tmp_path / "purifiers.yaml"
    p.write_text("")
    with pytest.raises(SystemExit):
        load_purifiers(p)
