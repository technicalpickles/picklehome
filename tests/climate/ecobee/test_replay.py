from datetime import date, datetime, timedelta

import pytest

from climate.ecobee.replay import Band, label_days, outdoor_series, replay


def day_rows(day: date, temp: float, cool=0, heat=0, aux=0):
    start = datetime.combine(day, datetime.min.time())
    return [
        {"ts": start + timedelta(minutes=5 * i), "outdoor": temp, "cool": cool, "heat": heat, "aux": aux}
        for i in range(288)
    ]


def series_from(temps_by_day: dict[date, float]):
    rows = [r for d, t in temps_by_day.items() for r in day_rows(d, t)]
    return outdoor_series(rows)


D = date(2026, 10, 1)


def days(*temps):
    return {D + timedelta(days=i): t for i, t in enumerate(temps)}


def test_band_parse_roundtrip():
    assert Band.parse("60/65") == Band(60, 65)
    assert str(Band.parse("58.5/67")) == "58.5/67"


@pytest.mark.parametrize("bad", ["65/60", "60", "a/b", "60/65/70"])
def test_band_parse_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        Band.parse(bad)


def test_label_days_picks_dominant_direction_across_zones():
    day = date(2026, 3, 1)
    heating = day_rows(day, 50, heat=300)[:20]
    cooling = day_rows(day, 50, cool=300)[:5]
    assert label_days([heating, cooling]) == {day: "heat"}


def test_label_days_counts_aux_as_heat():
    day = date(2026, 3, 1)
    assert label_days([day_rows(day, 50, aux=300)[:20]]) == {day: "heat"}


def test_label_days_skips_days_with_no_demand():
    day = date(2026, 3, 1)
    assert label_days([day_rows(day, 60, cool=300)[:5]]) == {}


def test_outdoor_series_carries_last_reading_over_gaps():
    rows = day_rows(D, 55)[:3]
    rows[1]["outdoor"] = None
    assert [v for _, v in outdoor_series(rows)] == [55, 55, 55]


def day(n: int) -> date:
    return D + timedelta(days=n)


def test_replay_flips_when_mean_crosses_band():
    # The 7am mean is 17h of yesterday plus 7h of today, so a switch lags the weather by about a day.
    out = series_from(days(70, 70, 50, 50, 70, 70, 70))
    result = replay(out, {}, Band(60, 65))
    assert [(f.day, f.from_mode, f.to_mode) for f in result.flips] == [
        (day(3), "cool", "heat"),
        (day(5), "heat", "cool"),
    ]


def test_replay_holds_mode_inside_band():
    out = series_from(days(70, 70, 62, 62, 62, 50, 62, 62))
    modes = replay(out, {}, Band(60, 65)).modes
    assert [modes[day(i)] for i in range(1, 8)] == ["cool"] * 4 + ["heat"] * 3


def test_replay_scores_modes_against_labels():
    out = series_from(days(70, 70, 50, 50))
    labels = {day(1): "cool", day(2): "heat", day(3): "heat"}
    result = replay(out, labels, Band(60, 65))
    assert (result.agree, result.scored) == (2, 3)


def test_replay_skips_days_without_a_full_enough_window():
    out = series_from(days(70))
    assert replay(out, {}, Band(60, 65)).modes == {}
