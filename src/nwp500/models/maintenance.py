"""Models for the REST maintenance-history endpoints.

``POST /device/filter/history`` and ``POST /device/cip/history`` return the
dates the owner recorded an air-filter or CIP (clean-in-place / descaling)
replacement through :meth:`~nwp500.NavienAPIClient.record_filter_change`
and :meth:`~nwp500.NavienAPIClient.record_cip_change`.
"""

from datetime import date

from .._base import NavienBaseModel


def format_maintenance_date(value: date) -> str:
    """Format a date as the cloud expects ``maintenanceDate``.

    The form is ``year-month-day`` with months and days **not**
    zero-padded (``2025-3-7``, not ``2025-03-07``).
    """
    return f"{value.year}-{value.month}-{value.day}"


class MaintenanceHistoryEntry(NavienBaseModel):
    """One recorded filter or CIP replacement."""

    #: The date the owner entered, as the cloud returns it.
    maintenance_date: str = ""
    #: When the record was created, as an integer; its unit is not
    #: documented.
    register_at: int | None = None
