"""The heater's schedules laid out as instants (``nwp500.sim.schedules``)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from nwp500.encoding import encode_week_bitfield
from nwp500.sim.inputs import ReservationEntry, TouPeriod
from nwp500.sim.schedules import (
    half_c_to_f,
    month_bit,
    reservation_firings,
    tou_rules,
    tou_windows,
    week_bit,
)

LA = ZoneInfo("America/Los_Angeles")
ALL_MONTHS = 4095
EVERY_DAY = 254
WEEKDAYS = 124
WEEKEND = 130


def _local(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=LA)


def _period(
    start_h: int,
    end_h: int,
    price: int,
    season: int = ALL_MONTHS,
    week: int = EVERY_DAY,
) -> TouPeriod:
    """A period from ``start_h``:00 to ``end_h``:59."""
    return TouPeriod(
        season=season,
        week=week,
        start_hour=start_h,
        start_minute=0,
        end_hour=end_h,
        end_minute=59,
        price_max=price,
    )


class TestMasks:
    def test_the_week_bit_is_the_libraries_encoding(self):
        for offset, name in enumerate(
            (
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            )
        ):
            day = date(2026, 9, 21) + timedelta(days=offset)  # a Monday
            assert week_bit(day) == encode_week_bitfield([name]), name

    def test_weekdays_and_the_weekend(self):
        monday = date(2026, 9, 21)
        days = [monday + timedelta(days=i) for i in range(7)]
        assert sum(week_bit(d) for d in days[:5]) == WEEKDAYS
        assert sum(week_bit(d) for d in days[5:]) == WEEKEND

    def test_the_month_bit(self):
        assert month_bit(date(2026, 1, 5)) == 1
        assert month_bit(date(2026, 12, 5)) == 1 << 11


class TestTouWindows:
    def test_the_window_is_the_highest_priced_run(self):
        periods = [_period(0, 15, 1), _period(16, 20, 5), _period(21, 23, 1)]
        ((rule),) = tou_rules(periods)
        assert (rule.opens, rule.closes) == (time(16, 0), time(21, 0))

    def test_a_flat_schedule_has_no_window(self):
        assert tou_rules([_period(0, 23, 3)]) == ()

    def test_every_peak_is_a_window(self):
        periods = [
            _period(0, 5, 3),
            _period(6, 6, 5),
            _period(7, 16, 1),
            _period(17, 19, 5),
            _period(20, 23, 1),
        ]
        spans = sorted((r.opens, r.closes) for r in tou_rules(periods))
        assert spans == [(time(6, 0), time(7, 0)), (time(17, 0), time(20, 0))]

    def test_a_peak_across_midnight_is_one_window(self):
        periods = [_period(0, 5, 5), _period(6, 21, 1), _period(22, 23, 5)]
        w = tou_windows(
            periods, LA, _local(2026, 9, 22, 12), _local(2026, 9, 23, 12)
        )
        assert (
            _local(2026, 9, 22, 22).astimezone(UTC),
            _local(2026, 9, 23, 6).astimezone(UTC),
        ) in w

    def test_the_masks_select_the_day(self):
        sept = 1 << 8
        periods = [
            _period(0, 15, 1, season=sept, week=WEEKDAYS),
            _period(16, 20, 5, season=sept, week=WEEKDAYS),
        ]
        w = tou_windows(
            periods, LA, _local(2026, 9, 25, 0), _local(2026, 10, 2, 0)
        )
        opens = [o.astimezone(LA).date() for o, _ in w]
        # Fri 25th, Mon 28th to Wed 30th: no weekend, no October.
        assert opens == [
            date(2026, 9, 25),
            date(2026, 9, 28),
            date(2026, 9, 29),
            date(2026, 9, 30),
        ]

    def test_windows_are_utc_instants_across_days(self):
        periods = [_period(0, 15, 1), _period(16, 20, 5), _period(21, 23, 1)]
        w = tou_windows(
            periods, LA, _local(2026, 9, 21, 12), _local(2026, 9, 23, 12)
        )
        assert w == (
            (
                _local(2026, 9, 21, 16).astimezone(UTC),
                _local(2026, 9, 21, 21).astimezone(UTC),
            ),
            (
                _local(2026, 9, 22, 16).astimezone(UTC),
                _local(2026, 9, 22, 21).astimezone(UTC),
            ),
        )
        assert all(o.tzinfo is UTC for o, _ in w)

    def test_a_window_open_at_the_start_is_found(self):
        periods = [_period(0, 5, 5), _period(6, 21, 1), _period(22, 23, 5)]
        w = tou_windows(
            periods, LA, _local(2026, 9, 23, 3), _local(2026, 9, 23, 4)
        )
        assert w == (
            (
                _local(2026, 9, 22, 22).astimezone(UTC),
                _local(2026, 9, 23, 6).astimezone(UTC),
            ),
        )

    def test_the_day_the_clocks_go_back(self):
        # 2026-11-01: 01:00-02:00 repeats; a 00:00-04:59 peak is 6 h.
        periods = [_period(0, 4, 5), _period(5, 23, 1)]
        ((o, c),) = tou_windows(
            periods, LA, _local(2026, 11, 1, 0), _local(2026, 11, 1, 12)
        )
        assert c - o == timedelta(hours=6)


def _entry(
    week: int, hour: int, minute: int = 0, *, enabled: bool = True
) -> ReservationEntry:
    return ReservationEntry(
        enabled=enabled,
        week=week,
        hour=hour,
        minute=minute,
        mode=1,
        setpoint_half_c=121,
    )


class TestReservationFirings:
    def test_each_selected_day_fires_once(self):
        firings = reservation_firings(
            [_entry(WEEKDAYS, 6, 30)],
            LA,
            _local(2026, 9, 25, 0),  # a Friday
            _local(2026, 9, 29, 0),
        )
        assert [f.at for f in firings] == [
            _local(2026, 9, 25, 6, 30).astimezone(UTC),
            _local(2026, 9, 28, 6, 30).astimezone(UTC),
        ]

    def test_the_span_is_half_open(self):
        e = [_entry(EVERY_DAY, 6)]
        at = _local(2026, 9, 25, 6)
        assert [
            f.at for f in reservation_firings(e, LA, at, at + timedelta(1))
        ] == [at.astimezone(UTC)]
        assert reservation_firings(e, LA, at - timedelta(hours=1), at) == ()

    def test_a_disabled_entry_does_not_fire(self):
        e = [_entry(EVERY_DAY, 6, enabled=False)]
        assert (
            reservation_firings(e, LA, _local(2026, 9, 25), _local(2026, 9, 27))
            == ()
        )

    def test_firings_are_in_time_order_then_schedule_order(self):
        e = [_entry(EVERY_DAY, 9), _entry(EVERY_DAY, 6), _entry(EVERY_DAY, 6)]
        firings = reservation_firings(
            e, LA, _local(2026, 9, 25), _local(2026, 9, 26)
        )
        assert [(f.at.astimezone(LA).hour, f.index) for f in firings] == [
            (6, 1),
            (6, 2),
            (9, 0),
        ]

    def test_a_skipped_local_time_fires_at_its_standard_reading(self):
        # 2026-03-08: 02:00-03:00 does not exist in Los Angeles.
        (f,) = reservation_firings(
            [_entry(EVERY_DAY, 2, 30)],
            LA,
            _local(2026, 3, 8, 0),
            _local(2026, 3, 8, 12),
        )
        assert f.at == datetime(2026, 3, 8, 10, 30, tzinfo=UTC)

    def test_a_repeated_local_time_fires_once(self):
        firings = reservation_firings(
            [_entry(EVERY_DAY, 1, 30)],
            LA,
            _local(2026, 11, 1, 0),
            _local(2026, 11, 1, 12),
        )
        assert [f.at for f in firings] == [
            datetime(2026, 11, 1, 8, 30, tzinfo=UTC)  # 01:30 PDT
        ]


@pytest.mark.parametrize(
    ("half_c", "f"), [(121, 140.9), (124, 143.6), (117, 137.3), (100, 122.0)]
)
def test_a_half_celsius_setpoint_in_fahrenheit(half_c: int, f: float):
    assert half_c_to_f(half_c) == pytest.approx(f)


class TestTheReviewOfTheWindows:
    def test_prices_are_compared_decoded(self):
        """1000 at four places is 0.10; 20 at two is 0.20: the 0.20
        period is the peak, whatever the encoded integers say."""
        cheap = _period(0, 15, 1000).model_copy(update={"decimal_point": 4})
        dear = _period(16, 23, 20).model_copy(update={"decimal_point": 2})
        (w,) = tou_windows(
            [cheap, dear], LA, _local(2026, 10, 5, 12), _local(2026, 10, 5, 18)
        )
        assert w == (
            _local(2026, 10, 5, 16).astimezone(UTC),
            _local(2026, 10, 6, 0).astimezone(UTC),
        )

    def test_a_peak_across_midnight_joins_only_dates_the_masks_select(self):
        """Weekday peaks 00:00-05:59 and 22:00-23:59: Monday morning has
        its window, and Friday night's does not run into Saturday."""
        periods = [
            _period(0, 5, 5, week=WEEKDAYS),
            _period(6, 21, 1, week=WEEKDAYS),
            _period(22, 23, 5, week=WEEKDAYS),
            _period(0, 23, 1, week=WEEKEND),
        ]
        # Sunday 2026-10-04 to Monday 2026-10-12.
        got = tou_windows(
            periods, LA, _local(2026, 10, 4), _local(2026, 10, 12, 23)
        )
        local = [(a.astimezone(LA), b.astimezone(LA)) for a, b in got]
        assert local[0] == (_local(2026, 10, 5, 0), _local(2026, 10, 5, 6))
        assert (_local(2026, 10, 5, 22), _local(2026, 10, 6, 6)) in local
        assert (_local(2026, 10, 9, 22), _local(2026, 10, 10, 0)) in local
        assert not any(
            a.weekday() in (5, 6) or (b.weekday() == 5 and b.hour > 0)
            for a, b in local
        )
        assert (_local(2026, 10, 12, 0), _local(2026, 10, 12, 6)) in local
