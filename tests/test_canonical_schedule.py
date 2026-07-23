"""Golden-vector tests for canonical reservation/TOU schedule representations.

These cover the equality/hash helper requested in issue #111: a consumer
needs to compare a desired program against a device read-back without
hand-diffing raw fields, and without caring about the order entries were
sent/returned in.
"""

from nwp500.encoding import build_tou_period, decode_reservation_hex
from nwp500.models import (
    ReservationEntry,
    ReservationSchedule,
    TOUPeriod,
    TOUReservationSchedule,
)


class TestReservationEntryCanonicalKey:
    def test_matches_known_decoded_vector(self):
        """Golden vector from decode_reservation_hex's own docstring
        example: "013e061e0478" -> enable=1, week=62, hour=6, min=30,
        mode=4, param=120."""
        decoded = decode_reservation_hex("013e061e0478")[0]
        entry = ReservationEntry(**decoded)
        assert entry.canonical_key() == (1, 62, 6, 30, 4, 120)

    def test_key_is_hashable(self):
        entry = ReservationEntry(
            enable=2, week=84, hour=6, min=30, mode=3, param=120
        )
        assert hash(entry.canonical_key()) == hash((2, 84, 6, 30, 3, 120))


class TestReservationScheduleCanonical:
    def _entries(self) -> list[ReservationEntry]:
        return [
            ReservationEntry(
                enable=2, week=64, hour=6, min=0, mode=3, param=120
            ),
            ReservationEntry(
                enable=2, week=32, hour=18, min=30, mode=4, param=110
            ),
        ]

    def test_order_independent_equality(self):
        entries = self._entries()
        a = ReservationSchedule(reservationUse=2, reservation=entries)
        b = ReservationSchedule(
            reservationUse=2, reservation=list(reversed(entries))
        )
        assert a.canonical() == b.canonical()

    def test_hash_stable_and_order_independent(self):
        entries = self._entries()
        a = ReservationSchedule(reservationUse=2, reservation=entries)
        b = ReservationSchedule(
            reservationUse=2, reservation=list(reversed(entries))
        )
        assert hash(a.canonical()) == hash(b.canonical())

    def test_differing_programs_are_unequal(self):
        a = ReservationSchedule(
            reservationUse=2,
            reservation=[
                ReservationEntry(
                    enable=2, week=64, hour=6, min=0, mode=3, param=120
                )
            ],
        )
        b = ReservationSchedule(
            reservationUse=2,
            reservation=[
                ReservationEntry(
                    enable=2, week=64, hour=7, min=0, mode=3, param=120
                )
            ],
        )
        assert a.canonical() != b.canonical()

    def test_enabled_flag_is_part_of_canonical_form(self):
        entries = self._entries()
        enabled = ReservationSchedule(reservationUse=2, reservation=entries)
        disabled = ReservationSchedule(reservationUse=1, reservation=entries)
        assert enabled.canonical() != disabled.canonical()


class TestTOUPeriodCanonicalKey:
    def test_matches_built_period(self):
        period_dict = build_tou_period(
            season_months=[6, 7, 8],
            week_days=["MO", "TU", "WE", "TH", "FR"],
            start_hour=14,
            start_minute=0,
            end_hour=19,
            end_minute=0,
            price_min=10,
            price_max=25,
            decimal_point=2,
        )
        period = TOUPeriod(**period_dict)
        assert period.canonical_key() == (
            period_dict["season"],
            period_dict["week"],
            14,
            0,
            19,
            0,
            10,
            25,
            2,
        )


class TestTOUReservationScheduleCanonical:
    def _periods(self) -> list[TOUPeriod]:
        return [
            TOUPeriod(
                season=4095,
                week=254,
                startHour=0,
                startMinute=0,
                endHour=11,
                endMinute=59,
                priceMin=10,
                priceMax=15,
                decimalPoint=2,
            ),
            TOUPeriod(
                season=4095,
                week=254,
                startHour=12,
                startMinute=0,
                endHour=23,
                endMinute=59,
                priceMin=20,
                priceMax=25,
                decimalPoint=2,
            ),
        ]

    def test_order_independent_equality(self):
        periods = self._periods()
        a = TOUReservationSchedule(reservationUse=2, reservation=periods)
        b = TOUReservationSchedule(
            reservationUse=2, reservation=list(reversed(periods))
        )
        assert a.canonical() == b.canonical()

    def test_hash_stable_and_order_independent(self):
        periods = self._periods()
        a = TOUReservationSchedule(reservationUse=2, reservation=periods)
        b = TOUReservationSchedule(
            reservationUse=2, reservation=list(reversed(periods))
        )
        assert hash(a.canonical()) == hash(b.canonical())

    def test_differing_programs_are_unequal(self):
        periods = self._periods()
        a = TOUReservationSchedule(reservationUse=2, reservation=periods)
        b = TOUReservationSchedule(reservationUse=2, reservation=[periods[0]])
        assert a.canonical() != b.canonical()
