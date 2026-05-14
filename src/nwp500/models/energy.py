from __future__ import annotations

from pydantic import Field

from .._base import NavienBaseModel


class EnergyUsageBase(NavienBaseModel):
    """Base energy usage fields common to daily and total responses."""

    heat_pump_usage: int = Field(default=0, alias="hpUsage")
    heat_element_usage: int = Field(default=0, alias="heUsage")
    heat_pump_time: int = Field(default=0, alias="hpTime")
    heat_element_time: int = Field(default=0, alias="heTime")

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
    """Monthly energy usage data grouping."""

    year: int
    month: int
    data: list[EnergyUsageDay]


class EnergyUsageResponse(NavienBaseModel):
    """Response for energy usage query."""

    total: EnergyUsageTotal
    usage: list[MonthlyEnergyData]

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
