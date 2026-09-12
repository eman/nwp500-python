from typing import Any, cast

from pydantic import (
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .._base import NavienBaseModel
from ..enums import (
    DHW_OPERATION_SETTING_TEXT,
    DhwOperationSetting,
)
from ..unit_system import get_unit_system
from ._converters import reservation_param_to_preferred


def _decode_hex_reservation_field(data: Any) -> Any:
    """Decode a hex-encoded ``reservation`` string into an entry list.

    Device read-backs deliver the schedule as a hex string on the legacy
    response topic and as a JSON list on the ``/rd`` topic; both shapes are
    accepted. Used as a ``mode="before"`` validator by every schedule model.
    """
    if isinstance(data, dict):
        d = cast(dict[str, Any], data).copy()
        raw = d.get("reservation", "")
        if isinstance(raw, str):
            if raw:
                from ..encoding import decode_reservation_hex

                d["reservation"] = decode_reservation_hex(raw)
            else:
                d["reservation"] = []
        return d
    return data


class ReservationEntry(NavienBaseModel):
    """A single scheduled reservation entry.

    Wraps the raw 6-byte protocol fields and provides computed properties
    for display-ready values including unit-aware temperature conversion.

    The raw protocol fields are:
        - enable: 2=enabled, 1=disabled (device boolean)
        - week: bitfield of active days (Sun=bit7, Mon=bit6, ..., Sat=bit1)
        - hour: 0-23
        - min: 0-59
        - mode: DHW operation mode ID (1-6)
        - param: temperature in half-degrees Celsius

    Unit-aware note:
        The ``temperature`` and ``unit`` computed fields read the
        *process-wide* unit-system preference via
        :func:`nwp500.unit_system.get_unit_system` at access time, not at
        construction time. Changing the preference with
        :func:`nwp500.unit_system.set_unit_system` therefore affects values
        read from already-constructed instances, and the preference is shared
        across every async task and thread rather than being context-local
        (see issue #103).
    """

    enable: int = 2
    week: int = 0
    hour: int = 0
    min: int = 0
    mode: int = 1
    param: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether this reservation is active (device bool: 2=on, 1=off)."""
        return self.enable == 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def days(self) -> list[str]:
        """Weekday names for this reservation."""
        from ..encoding import decode_week_bitfield

        return decode_week_bitfield(self.week)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def time(self) -> str:
        """Formatted time string (HH:MM)."""
        return f"{self.hour:02d}:{self.min:02d}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def temperature(self) -> float:
        """Temperature in the user's preferred unit."""
        return reservation_param_to_preferred(self.param)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unit(self) -> str:
        """Temperature unit symbol."""
        return "°C" if get_unit_system() == "metric" else "°F"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mode_name(self) -> str:
        """Human-readable operation mode name."""
        try:
            return DHW_OPERATION_SETTING_TEXT.get(
                DhwOperationSetting(self.mode), f"Unknown ({self.mode})"
            )
        except ValueError:
            return f"Unknown ({self.mode})"

    def canonical_key(self) -> tuple[int, int, int, int, int, int]:
        """Raw protocol fields as a stable, hashable tuple.

        Used to compare a desired reservation entry against a device
        read-back without depending on field order or computed properties.
        """
        return (
            self.enable,
            self.week,
            self.hour,
            self.min,
            self.mode,
            self.param,
        )


class ReservationSchedule(NavienBaseModel):
    """Complete reservation schedule from the device.

    Can be constructed from raw MQTT response data. The ``reservation``
    field accepts either a hex string (from GET responses) or a list of
    dicts/ReservationEntry objects.
    """

    reservation_use: int = Field(default=0, alias="reservationUse")
    reservation: list[ReservationEntry] = Field(default_factory=list)

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

    @model_validator(mode="before")
    @classmethod
    def _decode_hex_reservation(cls, data: Any) -> Any:
        """Decode hex-encoded reservation string into entry list."""
        return _decode_hex_reservation_field(data)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether the reservation system is globally enabled.

        Device bool convention: 2=on, 1=off.
        """
        return self.reservation_use == 2

    def canonical(self) -> tuple[bool, tuple[tuple[int, ...], ...]]:
        """Normalized, order-independent representation of this schedule.

        Entry order in a device read-back is not guaranteed to match the
        order a program was written in, so entries are sorted by their raw
        field tuple. Two schedules holding the same reservations return
        equal (and equally hashable) results from this method regardless of
        entry order — the intended way to compare a desired program against
        a device read-back (see
        :func:`nwp500.reservations.update_reservations_confirmed`).
        """
        return (
            self.enabled,
            tuple(sorted(entry.canonical_key() for entry in self.reservation)),
        )


class RecirculationScheduleEntry(NavienBaseModel):
    """A single entry in the recirculation pump schedule.

    Used with the RECIR_RESERVATION command (33554440), published on
    ``ctrl/recirc-rsv/rd`` and read back with RECIRC_RESERVATION_READ
    (16777231) on ``st/recirc-rsv/rd``. The NaviLink app builds these
    entries with the same ``Reservation`` class as the temperature
    schedule, so the wire fields are identical to
    :class:`ReservationEntry`:

        - enable: 2=enabled, 1=disabled (device boolean)
        - week: bitfield of active days (Sun=bit7, Mon=bit6, ..., Sat=bit1)
        - hour: 0-23
        - min: 0-59
        - mode: in the app's schedule editor this is the on/off toggle for
          the entry (2=pump on, 1=pump off)
        - param: unused for recirculation; the app constructs entries
          with ``-1``. The hex read-back carries it as the byte ``0xFF``,
          which is normalized to ``-1`` so both read-back forms compare
          equal.

    The ``mode``/``param`` semantics are inferred from the app's shared
    schedule dialog and have not been confirmed against a unit with
    recirculation fitted.
    """

    # Strict: a bool or float must not be coerced into a protocol integer
    # and slip past write validation.
    enable: int = Field(default=2, strict=True)
    week: int = Field(default=0, strict=True)
    hour: int = Field(default=0, strict=True)
    min: int = Field(default=0, strict=True)
    mode: int = Field(default=2, strict=True)
    param: int = Field(default=-1, strict=True)

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

    @field_validator("param", mode="before")
    @classmethod
    def _unsigned_byte_param(cls, value: Any) -> Any:
        """Map the hex read-back's unsigned 0xFF to the app's ``-1``."""
        return -1 if value == 255 else value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether this entry is active (device bool: 2=on, 1=off)."""
        return self.enable == 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def days(self) -> list[str]:
        """Weekday names for this entry."""
        from ..encoding import decode_week_bitfield

        return decode_week_bitfield(self.week)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def time(self) -> str:
        """Formatted time string (HH:MM)."""
        return f"{self.hour:02d}:{self.min:02d}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pump_on(self) -> bool:
        """Whether the entry switches the pump on (mode 2) or off (mode 1)."""
        return self.mode == 2

    def canonical_key(self) -> tuple[int, int, int, int, int, int]:
        """Raw protocol fields as a stable, hashable tuple."""
        return (
            self.enable,
            self.week,
            self.hour,
            self.min,
            self.mode,
            self.param,
        )


class RecirculationSchedule(NavienBaseModel):
    """Complete recirculation pump schedule (RECIR_RESERVATION command).

    Written with command code 33554440 on ``ctrl/recirc-rsv/rd`` and read
    with 16777231 on ``st/recirc-rsv/rd``. Same envelope as
    :class:`ReservationSchedule`: ``reservationUse`` (2=on, 1=off) plus a
    ``reservation`` list. Read-backs arrive both as a JSON list and, on the
    legacy ``res/recirc-rsv`` topic, as a hex string; the model parses
    both, though the typed subscription listens on the ``/rd`` topic only.
    """

    reservation_use: int = Field(default=0, alias="reservationUse", strict=True)
    reservation: list[RecirculationScheduleEntry] = Field(default_factory=list)

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

    @model_validator(mode="before")
    @classmethod
    def _decode_hex_reservation(cls, data: Any) -> Any:
        """Decode hex-encoded reservation string into entry list."""
        return _decode_hex_reservation_field(data)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether the recirculation schedule is globally enabled."""
        return self.reservation_use == 2

    def canonical(self) -> tuple[bool, tuple[tuple[int, ...], ...]]:
        """Order-independent representation for read-back comparison."""
        return (
            self.enabled,
            tuple(sorted(entry.canonical_key() for entry in self.reservation)),
        )


class OtaCommitPayload(NavienBaseModel):
    """Payload for committing a firmware component update.

    Used with the OTA_COMMIT command (33554442). This command uses a
    special ``commitOta`` structure instead of the standard mode/param
    format.

    Args:
        sw_code: Software component code identifying which firmware to commit.
            1 = Controller, 2 = Panel, 4 = WiFi/communication module.
        sw_version: Version number to commit (as reported by the OTA check).
    """

    sw_code: int = Field(alias="swCode")
    sw_version: int = Field(alias="swVersion")

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
    )
