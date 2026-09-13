from pydantic import Field

from .._base import NavienBaseModel


class EnergyUsageBase(NavienBaseModel):
    """Base energy usage fields common to daily and total responses."""

    heat_pump_usage: int = Field(default=0, alias="hpUsage")
    heat_element_usage: int = Field(default=0, alias="heUsage")
    heat_pump_time: int = Field(default=0, alias="hpTime")
    heat_element_time: int = Field(default=0, alias="heTime")
    #: Declared in the NaviLink app's usage model; the NWP500 does not
    #: report it (raw int, semantics unknown).
    ep_usage: int = Field(default=0, alias="epUsage")
    #: Declared in the NaviLink app's usage model; the NWP500 does not
    #: report it (raw int, semantics unknown).
    water_usage: int = Field(default=0, alias="waterUsage")

    @property
    def total_usage(self) -> int:
        return self.heat_pump_usage + self.heat_element_usage


class EnergyUsageTotal(EnergyUsageBase):
    """Total energy usage data."""

    @property
    def heat_pump_percentage(self) -> float:
        return (
            (self.heat_pump_usage / self.total_usage * 100.0)
            if self.total_usage > 0
            else 0.0
        )

    @property
    def heat_element_percentage(self) -> float:
        return (
            (self.heat_element_usage / self.total_usage * 100.0)
            if self.total_usage > 0
            else 0.0
        )

    @property
    def total_time(self) -> int:
        return self.heat_pump_time + self.heat_element_time


class EnergyUsageDay(EnergyUsageBase):
    """Daily energy usage data."""

    pass


class MonthlyEnergyData(NavienBaseModel):
    """One ``usage`` entry of an energy response.

    The daily query returns one entry per requested month with ``month``
    set and one ``data`` item per day. The monthly query returns one entry
    per requested year with ``month`` absent and one ``data`` item per
    month (twelve). The app's model also declares ``day`` for the hourly
    query, which the NWP500 did not answer in testing.
    """

    year: int
    month: int | None = None
    day: int | None = None
    data: list[EnergyUsageDay]


class EnergyUsageResponse(NavienBaseModel):
    """Response for the daily, monthly and hourly energy usage queries."""

    #: Reported by the device alongside the usage list; observed value 1
    #: for both the daily and the monthly query.
    type_of_usage: int | None = None
    total: EnergyUsageTotal
    usage: list[MonthlyEnergyData]

    def get_year_data(self, year: int) -> MonthlyEnergyData | None:
        """Get the per-month entry for a year from a monthly query response.

        Args:
            year: Year (e.g., 2025)

        Returns:
            MonthlyEnergyData whose ``data`` holds one item per month, or
            None if not found
        """
        for entry in self.usage:
            if entry.year == year and entry.month is None:
                return entry
        return None

    def get_month_data(self, year: int, month: int) -> MonthlyEnergyData | None:
        """Get energy usage data for a specific month.

        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)

        Returns:
            MonthlyEnergyData for that month, or None if not found
        """
        for monthly_data in self.usage:
            if monthly_data.year == year and monthly_data.month == month:
                return monthly_data
        return None
