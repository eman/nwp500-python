"""Shared Pydantic base model for all Navien data models.

Centralises the common configuration (camelCase aliases, extra="ignore",
enum serialization) so that both the authentication models and the device
protocol models share a single base class.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class NavienBaseModel(BaseModel):
    """Base model for all Navien models.

    Provides:
    - camelCase alias generation (``to_camel``) for JSON compatibility
    - ``populate_by_name=True`` so Python snake_case names work too
    - ``extra="ignore"`` to tolerate unknown protocol fields
    - ``use_enum_values=False`` to keep enum objects during validation
    - Custom ``model_dump`` that converts enums to their ``.name`` string
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        use_enum_values=False,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Dump model to dict with enums serialised as their name strings."""
        if "mode" not in kwargs:
            kwargs["mode"] = "python"
        result = super().model_dump(**kwargs)
        converted: dict[str, Any] = self._convert_enums_to_names(result)
        return converted

    def to_protocol_dict(self) -> dict[str, Any]:
        """Dump only the declared protocol fields, by alias.

        Excludes pydantic ``computed_field`` properties, which are
        display-oriented (formatted times, weekday names, unit-converted
        temperatures) and must never be sent to the device.
        """
        return self.model_dump(
            by_alias=True, include=set(type(self).model_fields)
        )

    @staticmethod
    def _convert_enums_to_names(
        data: Any, visited: set[int] | None = None
    ) -> Any:
        """Recursively convert Enum values to their ``.name`` strings.

        Args:
            data: The data structure to convert.
            visited: Set of object IDs already visited (cycle guard).
        """
        from enum import Enum

        if isinstance(data, Enum):
            return data.name
        if not isinstance(data, (dict, list, tuple)):
            return data

        visited = visited or set()
        if id(data) in visited:
            return data
        visited.add(id(data))

        if isinstance(data, dict):
            res: dict[Any, Any] | list[Any] | tuple[Any, ...] = {
                k: NavienBaseModel._convert_enums_to_names(v, visited)
                for k, v in data.items()
            }
        else:
            res = type(data)(
                [
                    NavienBaseModel._convert_enums_to_names(i, visited)
                    for i in data
                ]
            )

        visited.discard(id(data))
        return res
