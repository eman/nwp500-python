from __future__ import annotations

from typing import Any, cast

from pydantic import Field, model_validator

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
