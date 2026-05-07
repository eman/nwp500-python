from __future__ import annotations

import warnings
from typing import Any
, cast

from pydantic import ConfigDict, Field, computed_field, model_validator

from .._base import NavienBaseModel
from ..enums import (
    DHW_OPERATION_SETTING_TEXT,
    DhwOperationSetting,
    RecirculationMode,
)
from ..unit_system import get_unit_system
from ._converters import reservation_param_to_preferred


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether the reservation system is globally enabled.

        Device bool convention: 2=on, 1=off.
        """
        return self.reservation_use == 2

    @classmethod
    )


class WeeklyReservationEntry(NavienBaseModel):
    """A single entry in a weekly temperature reservation schedule.

    Similar to :class:`ReservationEntry` but used with the RESERVATION_WEEKLY
    command (33554438), which configures a separate weekly temperature schedule
    independent of the timed reservation system.

    The raw protocol fields mirror the standard reservation format:
        - enable: 2=enabled, 1=disabled (device boolean)
        - week: bitfield of active days (Sun=bit7, Mon=bit6, ..., Sat=bit1)
        - hour: 0-23
        - min: 0-59
        - mode: DHW operation mode ID (1-6)
        - param: temperature in half-degrees Celsius
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


class WeeklyReservationSchedule(NavienBaseModel):
    """Complete weekly reservation schedule (RESERVATION_WEEKLY command).

    Used with command code 33554438 to configure a temperature schedule
    that repeats weekly. Accepts the same hex-encoded format as the
    standard reservation schedule.
    """

    reservation_use: int = Field(default=0, alias="reservationUse")
    reservation: list[WeeklyReservationEntry] = Field(default_factory=list)

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether the weekly reservation system is globally enabled.

        Device bool convention: 2=on, 1=off.
        """
        return self.reservation_use == 2

    @classmethod
    )


class RecirculationScheduleEntry(NavienBaseModel):
    """A single entry in a recirculation pump schedule.

    Used with the RECIR_RESERVATION command (33554444) to set timed
    recirculation cycles. Each entry defines a time window and pump mode.

    Fields:
        - enable: 2=enabled, 1=disabled (device boolean)
        - week: bitfield of active days (Sun=bit7, Mon=bit6, ..., Sat=bit1)
        - start_hour: 0-23
        - start_min: 0-59
        - end_hour: 0-23
        - end_min: 0-59
        - mode: recirculation mode
          (1=Constant, 2=Timer, 3=Temperature, 4=Sensor)
    """

    enable: int = 2
    week: int = 0
    start_hour: int = Field(default=0, alias="startHour")
    start_min: int = Field(default=0, alias="startMin")
    end_hour: int = Field(default=0, alias="endHour")
    end_min: int = Field(default=0, alias="endMin")
    mode: int = 1

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

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
    def start_time(self) -> str:
        """Formatted start time string (HH:MM)."""
        return f"{self.start_hour:02d}:{self.start_min:02d}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def end_time(self) -> str:
        """Formatted end time string (HH:MM)."""
        return f"{self.end_hour:02d}:{self.end_min:02d}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mode_name(self) -> str:
        """Human-readable recirculation mode name."""
        try:
            return RecirculationMode(self.mode).name.replace("_", " ").title()
        except ValueError:
            return f"Unknown ({self.mode})"


class RecirculationSchedule(NavienBaseModel):
    """Complete recirculation pump schedule (RECIR_RESERVATION command).

    Used with command code 33554444 to configure timed recirculation
    pump operation windows.
    """

    schedule: list[RecirculationScheduleEntry] = Field(default_factory=list)

    @classmethod
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
