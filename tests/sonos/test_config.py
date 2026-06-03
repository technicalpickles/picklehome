import pytest

from sonos.roster import load_expected
from sonos.model import ExpectedSpeaker


def test_loads_speakers_with_and_without_uid(tmp_path):
    cfg = tmp_path / "speakers.yaml"
    cfg.write_text(
        "speakers:\n"
        "  - name: Kitchen\n"
        "    uid: RINCON_A\n"
        "  - name: Alex's Room\n"
    )

    expected = load_expected(cfg)

    assert expected == [
        ExpectedSpeaker(name="Kitchen", uid="RINCON_A"),
        ExpectedSpeaker(name="Alex's Room", uid=None),
    ]


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_expected(tmp_path / "nope.yaml")


def test_empty_speakers_returns_empty_list(tmp_path):
    cfg = tmp_path / "speakers.yaml"
    cfg.write_text("speakers: []\n")

    assert load_expected(cfg) == []


def test_entry_without_name_raises(tmp_path):
    cfg = tmp_path / "speakers.yaml"
    cfg.write_text("speakers:\n  - uid: RINCON_A\n")

    with pytest.raises(ValueError, match="name"):
        load_expected(cfg)
