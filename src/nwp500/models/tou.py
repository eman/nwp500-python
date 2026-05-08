from __future__ import annotations

from typing import Any, cast

from pydantic import ConfigDict, Field, computed_field, model_validator

from .._base import NavienBaseModel


class TOUSchedule(NavienBaseModel):
    """Time of Use schedule information."""

    season: int = 0
    intervals: list[dict[str, Any]] = Field(
        default_factory=list, alias="interval"
    )


class ConvertedTOUPlan(NavienBaseModel):
    """A rate plan converted by the Navien backend from OpenEI format.

    Returned by POST /device/tou/convert. Contains the utility name,
    plan name, and device-ready schedule with season/week bitfields
    and scaled pricing.
    """

    utility: str = ""
    name: str = ""
    schedule: list[TOUSchedule] = Field(default_factory=list)


class TOUInfo(NavienBaseModel):
    """Time of Use information."""

    register_path: str = ""
    source_type: str = ""
    controller_id: str = ""
    manufacture_id: str = ""
    name: str = ""
    utility: str = ""
    zip_code: int = 0
    schedule: list[TOUSchedule] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _extract_nested_tou_info(cls, data: Any) -> Any:
        # Handle nested structure where fields are in 'touInfo'
        if isinstance(data, dict):
            # Explicitly cast to dict[str, Any] for type safety
            d = cast(dict[str, Any], data).copy()
            if "touInfo" in d:
                tou_data = d.pop("touInfo")
                if isinstance(tou_data, dict):
                    d.update(tou_data)
            return d
        return data


class TOUPeriod(NavienBaseModel):
    """A single TOU pricing period from an MQTT ``tou/rd`` response.

    Each period defines a time window, active season/week bitfields,
    and the pricing range for that window.

    Fields use camelCase aliases to match the raw MQTT payload:
        - season: bitfield of active months (bit N-1 set for month N)
        - week: bitfield of active weekdays (Sun=bit7, …, Sat=bit1)
        - startHour / startMinute: start of the time window (0-23 / 0-59)
        - endHour / endMinute: end of the time window (0-23 / 0-59)
        - priceMin / priceMax: encoded integer prices (divide by
          10^decimalPoint)
        - decimalPoint: number of decimal places for price values
    """

    season: int = 0
    week: int = 0
    start_hour: int = Field(default=0, alias="startHour")
    start_minute: int = Field(default=0, alias="startMinute")
    end_hour: int = Field(default=0, alias="endHour")
    end_minute: int = Field(default=0, alias="endMinute")
    price_min: int = Field(default=0, alias="priceMin")
    price_max: int = Field(default=0, alias="priceMax")
    decimal_point: int = Field(default=5, alias="decimalPoint")

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def start_time(self) -> str:
        """Formatted start time (HH:MM)."""
        return f"{self.start_hour:02d}:{self.start_minute:02d}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def end_time(self) -> str:
        """Formatted end time (HH:MM)."""
        return f"{self.end_hour:02d}:{self.end_minute:02d}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decoded_price_min(self) -> float:
        """Minimum price decoded to a float (price_min / 10^decimal_point)."""
        divisor: float = 10.0**self.decimal_point
        return float(self.price_min) / divisor

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decoded_price_max(self) -> float:
        """Maximum price decoded to a float (price_max / 10^decimal_point)."""
        divisor: float = 10.0**self.decimal_point
        return float(self.price_max) / divisor


class TOUReservationSchedule(NavienBaseModel):
    """TOU schedule as returned by the MQTT ``tou/rd`` response topic.

    This model matches the raw MQTT payload for both
    :meth:`~nwp500.NavienMqttClient.request_tou_settings` read responses
    and :meth:`~nwp500.NavienMqttClient.configure_tou_schedule` write
    confirmations — both use ``CommandCode.TOU_RESERVATION`` and the
    ``tou/rd`` response topic.

    The payload structure is::

        {
            "reservationUse": 2,          # 1=disabled, 2=enabled
            "reservation": [              # list of TOU period dicts
                {
                    "season": 4095, "week": 254,
                    "startHour": 0, "startMinute": 0,
                    "endHour": 23, "endMinute": 59,
                    "priceMin": 10, "priceMax": 25,
                    "decimalPoint": 2
                },
                ...
            ]
        }
    """

    reservation_use: int = Field(default=0, alias="reservationUse")
    reservation: list[TOUPeriod] = Field(default_factory=list)

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enabled(self) -> bool:
        """Whether TOU scheduling is globally enabled.

        Device bool convention: 2=on, 1=off.
        """
        return self.reservation_use == 2
