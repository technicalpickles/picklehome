from sonos.model import (
    ExpectedSpeaker,
    Health,
    Speaker,
    reconcile,
)


def _speaker(uid="RINCON_A", name="Kitchen", **kw):
    defaults = dict(ip="192.168.1.61", volume=40, muted=False)
    defaults.update(kw)
    return Speaker(uid=uid, name=name, **defaults)


def test_expected_speaker_not_discovered_is_offline():
    expected = [ExpectedSpeaker(name="Alex's Room", uid="RINCON_X")]
    report = reconcile(discovered=[], expected=expected)

    offline = report.offline
    assert len(offline) == 1
    assert offline[0].name == "Alex's Room"
    assert offline[0].health is Health.OFFLINE


def test_expected_speaker_matched_by_uid_is_online():
    kitchen = _speaker(uid="RINCON_A", name="Kitchen")
    expected = [ExpectedSpeaker(name="Kitchen", uid="RINCON_A")]

    report = reconcile(discovered=[kitchen], expected=expected)

    assert report.offline == []
    online = report.online
    assert len(online) == 1
    assert online[0].health is Health.ONLINE
    assert online[0].speaker is kitchen


def test_expected_without_uid_matches_by_name_case_insensitive():
    deck = _speaker(uid="RINCON_D", name="Deck")
    expected = [ExpectedSpeaker(name="deck")]  # no uid known yet

    report = reconcile(discovered=[deck], expected=expected)

    assert report.offline == []
    assert report.online[0].speaker is deck


def test_uid_match_wins_even_if_name_differs():
    # Speaker was renamed on the network but uid is stable.
    renamed = _speaker(uid="RINCON_A", name="Kitchen Speaker")
    expected = [ExpectedSpeaker(name="Kitchen", uid="RINCON_A")]

    report = reconcile(discovered=[renamed], expected=expected)

    assert report.online[0].speaker is renamed


def test_discovered_speaker_not_in_roster_is_unexpected():
    surprise = _speaker(uid="RINCON_NEW", name="Garage")
    report = reconcile(discovered=[surprise], expected=[])

    unexpected = report.unexpected
    assert len(unexpected) == 1
    assert unexpected[0].name == "Garage"
    assert unexpected[0].health is Health.UNEXPECTED
    assert unexpected[0].speaker is surprise


def test_unexpected_does_not_double_count_matched_speaker():
    kitchen = _speaker(uid="RINCON_A", name="Kitchen")
    expected = [ExpectedSpeaker(name="Kitchen", uid="RINCON_A")]

    report = reconcile(discovered=[kitchen], expected=expected)

    assert report.unexpected == []


def test_online_muted_speaker_is_flagged():
    muted = _speaker(uid="RINCON_A", name="Kitchen", muted=True)
    expected = [ExpectedSpeaker(name="Kitchen", uid="RINCON_A")]

    report = reconcile(discovered=[muted], expected=expected)

    status = report.online[0]
    assert "muted" in status.issues


def test_online_unmuted_speaker_has_no_issues():
    ok = _speaker(uid="RINCON_A", name="Kitchen", muted=False)
    expected = [ExpectedSpeaker(name="Kitchen", uid="RINCON_A")]

    report = reconcile(discovered=[ok], expected=expected)

    assert report.online[0].issues == ()
    assert report.healthy is True


def test_report_unhealthy_when_speaker_offline():
    expected = [ExpectedSpeaker(name="Alex's Room", uid="RINCON_X")]
    report = reconcile(discovered=[], expected=expected)

    assert report.healthy is False
