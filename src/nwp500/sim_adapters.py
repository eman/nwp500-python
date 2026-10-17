"""Building the simulator's inputs from the library's models.

``nwp500.sim`` imports nothing from the rest of the library; this
module is the bridge. Each function takes what a client already fetched
(a ``DeviceStatus``, a ``DeviceFeature``, a ``ReservationSchedule``, a
``TOUInfo``) and returns a scenario part. Nothing here does I/O.

Temperatures are read from the raw fields (``*_raw``), never the
converted properties, which follow the process-wide unit preference
(``nwp500.unit_system``): a reservation's setpoint stays in the device's
half-degrees Celsius, and every other temperature becomes °F, the
simulator's unit.

Example::

    from datetime import timedelta
    from nwp500 import sim, sim_adapters as sa

    scenario = sim.Scenario(
        start=now,
        horizon=timedelta(hours=24),
        tz="America/Los_Angeles",
        state=sa.heater_state(status),
        settings=sa.settings(status),
        schedules=sa.schedules(
            reservations=reservation_schedule,
            tou=tou_info,
            tou_enabled=status.tou_status,
        ),
        environment=sim.Environment(ambient_f=68.0),
    )
    result = sim.simulate(scenario, sa.params(feature))
"""

from collections.abc import Iterable, Mapping
from typing import Any

from nwp500.models import (
    DeviceFeature,
    DeviceStatus,
    ReservationSchedule,
    TOUInfo,
    TOUPeriod,
    TOUReservationSchedule,
)
from nwp500.sim import (
    HeaterParams,
    HeaterState,
    ReservationEntry,
    Schedules,
    Settings,
    TouPeriod,
    default_params,
)
from nwp500.temperature import DeciCelsius, HalfCelsius


def heater_state(status: DeviceStatus) -> HeaterState:
    """The tank and what is heating it: both thermistors (0.1 °C
    resolution), the compressor, and either element."""
    return HeaterState(
        upper_f=DeciCelsius(status.tank_upper_temperature_raw).to_fahrenheit(),
        lower_f=DeciCelsius(status.tank_lower_temperature_raw).to_fahrenheit(),
        compressor_running=bool(status.comp_use),
        element_running=bool(status.heat_upper_use)
        or bool(status.heat_lower_use),
    )


def settings(status: DeviceStatus) -> Settings:
    """The setpoint, the operation mode and the lower-zone start
    threshold."""
    return Settings(
        setpoint_f=HalfCelsius(
            status.dhw_temperature_setting_raw
        ).to_fahrenheit(),
        mode=int(status.dhw_operation_setting),
        hp_lower_on_f=HalfCelsius(
            status.hp_lower_on_temp_setting_raw
        ).to_fahrenheit(),
    )


def params(feature: DeviceFeature) -> HeaterParams:
    """The default parameters for the heater's tank size
    (``sim.default_params``)."""
    return default_params(int(feature.volume_code))


def reservation_entries(
    schedule: ReservationSchedule,
) -> tuple[ReservationEntry, ...]:
    """The schedule's entries, as the device stores them."""
    return tuple(
        ReservationEntry(
            enabled=e.enabled,
            week=e.week,
            hour=e.hour,
            minute=e.min,
            mode=e.mode,
            setpoint_half_c=e.param,
        )
        for e in schedule.reservation
    )


def _period(p: TOUPeriod, season: int | None = None) -> TouPeriod:
    return TouPeriod(
        season=p.season if season is None else season,
        week=p.week,
        start_hour=p.start_hour,
        start_minute=p.start_min,
        end_hour=p.end_hour,
        end_minute=p.end_min,
        price_min=p.price_min,
        price_max=p.price_max,
        decimal_point=p.decimal_point,
    )


def tou_periods(
    tou: TOUInfo | TOUReservationSchedule | Iterable[TOUPeriod],
) -> tuple[TouPeriod, ...]:
    """The TOU periods of a ``TOUInfo`` (the REST read), a
    ``TOUReservationSchedule`` (the MQTT write confirmation) or a list
    of ``TOUPeriod``."""
    if isinstance(tou, TOUInfo):
        out: list[TouPeriod] = []
        for season in tou.schedule:
            for raw in season.intervals:
                period = TOUPeriod.model_validate(
                    _with_season(raw, season.season)
                )
                out.append(_period(period))
        return tuple(out)
    if isinstance(tou, TOUReservationSchedule):
        return tuple(_period(p) for p in tou.reservation)
    return tuple(_period(p) for p in tou)


def _with_season(raw: Mapping[str, Any], season: int) -> dict[str, Any]:
    return {"season": season, **raw}


def schedules(
    *,
    reservations: ReservationSchedule | None = None,
    tou: TOUInfo | TOUReservationSchedule | Iterable[TOUPeriod] | None = None,
    tou_enabled: bool = False,
) -> Schedules:
    """The heater's schedules. ``tou_enabled`` is the device's TOU
    switch (``DeviceStatus.tou_status``); with a
    ``TOUReservationSchedule`` its own ``enabled`` is used instead."""
    if isinstance(tou, TOUReservationSchedule):
        tou_enabled = tou.enabled
    return Schedules(
        reservations=(
            () if reservations is None else reservation_entries(reservations)
        ),
        reservations_enabled=(
            True if reservations is None else reservations.enabled
        ),
        tou_periods=() if tou is None else tou_periods(tou),
        tou_enabled=tou_enabled,
    )
