"""Rich-based renderers for CLI human-readable output.

Rich is a hard requirement of the CLI; there is no plain-text fallback. This
module renders the presentation-neutral structures built in :mod:`.presentation`
(and JSON/tables) using Rich exclusively.
"""

import itertools
import json
import logging
from collections.abc import Callable
from typing import Any, cast

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .presentation import (
    DailyEnergyReport,
    EnergyPeriodRow,
    EnergyReport,
    EnergyTotals,
)

_logger = logging.getLogger(__name__)


_MONTH_ABBR = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

_DAY_ABBR: dict[str, str] = {
    "Sunday": "Sun",
    "Monday": "Mon",
    "Tuesday": "Tue",
    "Wednesday": "Wed",
    "Thursday": "Thu",
    "Friday": "Fri",
    "Saturday": "Sat",
}


def _format_months(month_nums: list[int]) -> str:
    """Format month numbers into a compact string.

    Collapses consecutive months into ranges
    (e.g. ``[6,7,8,9]`` → ``"Jun–Sep"``).
    """
    if len(month_nums) == 12:
        return "All year"
    return _collapse_ranges(
        month_nums,
        lambda m: _MONTH_ABBR[int(m)],
        cycle_size=12,
    )


# Canonical ordering used by _abbreviate_days
_DAY_ORDER = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]


def _abbreviate_days(day_names: list[str]) -> str:
    """Format day names into a compact string.

    Collapses consecutive days into ranges
    (e.g. ``['Tue','Wed','Thu','Fri','Sat']`` → ``"Tue–Sat"``).
    """
    if len(day_names) == 7:
        return "Every day"
    s = set(day_names)
    if s == {"Saturday", "Sunday"}:
        return "Sat–Sun"
    # Sort into canonical week order
    ordered = sorted(day_names, key=lambda d: _DAY_ORDER.index(d))
    return _collapse_ranges(
        ordered,
        lambda d: _DAY_ABBR.get(str(d), str(d)[:3]),
        cycle_size=7,
    )


def _collapse_ranges(
    items: list[Any],
    label_fn: Callable[[Any], str],
    cycle_size: int,
) -> str:
    """Collapse consecutive items into 'start–end' ranges.

    Works for both day names (given in canonical order) and
    month numbers (1-based ints).
    """
    if not items:
        return ""

    # Build groups of consecutive items
    groups: list[list[Any]] = [[items[0]]]
    for prev, curr in itertools.pairwise(items):
        if isinstance(prev, int):
            consecutive = (curr - prev) == 1 or (
                prev == cycle_size and curr == 1
            )
        else:
            pi = _DAY_ORDER.index(prev)
            ci = _DAY_ORDER.index(curr)
            consecutive = (ci - pi) == 1 or (pi == 6 and ci == 0)
        if consecutive:
            groups[-1].append(curr)
        else:
            groups.append([curr])

    parts: list[str] = []
    for group in groups:
        if len(group) >= 3:
            parts.append(f"{label_fn(group[0])}–{label_fn(group[-1])}")
        else:
            parts.extend(label_fn(g) for g in group)
    return ", ".join(parts)


class OutputFormatter:
    """Rich output formatter for CLI human-readable output.

    Rich is mandatory; this formatter always renders with Rich.
    """

    def __init__(self) -> None:
        """Initialize the formatter."""
        self.console = Console()

    def print_status_table(self, items: list[tuple[str, str, str]]) -> None:
        """Print status items as a formatted table.

        Args:
            items: List of (category, label, value) tuples
        """
        self._print_status_rich(items)

    def print_energy_table(self, report: EnergyReport) -> None:
        """Print an energy usage report (summary + monthly breakdown).

        Args:
            report: Neutral energy report from :mod:`.presentation`
        """
        self._print_energy_summary(report.totals, "ENERGY USAGE REPORT")
        if report.months:
            self._print_energy_rich(report.months)

    def print_daily_energy_table(self, report: DailyEnergyReport) -> None:
        """Print a daily energy usage report (summary + daily breakdown).

        Args:
            report: Neutral daily energy report from :mod:`.presentation`
        """
        from calendar import month_name

        year, month = report.year, report.month
        month_str = (
            f"{month_name[month]} {year}"
            if 1 <= month <= 12
            else f"Month {month} {year}"
        )
        self._print_energy_summary(
            report.totals, f"DAILY ENERGY USAGE - {month_str}"
        )
        self._print_daily_energy_rich(report.days)

    def print_error(
        self,
        message: str,
        title: str = "Error",
        details: list[str] | None = None,
    ) -> None:
        """Print an error message.

        Args:
            message: Main error message
            title: Panel title
            details: Optional list of detail lines
        """
        self._print_error_rich(message, title, details)

    def print_success(self, message: str) -> None:
        """Print a success message.

        Args:
            message: Success message to display
        """
        self._print_success_rich(message)

    def print_info(self, message: str) -> None:
        """Print an info message.

        Args:
            message: Info message to display
        """
        self._print_info_rich(message)

    def print_device_list(self, devices: list[dict[str, Any]]) -> None:
        """Print list of devices with status indicators.

        Args:
            devices: List of device dictionaries with status info
        """
        self._print_device_list_rich(devices)

    def print_tou_schedule(
        self,
        name: str,
        utility: str,
        zip_code: int,
        schedules: Any,
        decode_season: Any,
        decode_week: Any,
        decode_price_fn: Any,
    ) -> None:
        """Print TOU schedule as a human-readable table.

        Args:
            name: Rate plan name
            utility: Utility company name
            zip_code: Service ZIP code
            schedules: List of TOUSchedule objects
            decode_season: Function to decode season bitfield
            decode_week: Function to decode week bitfield
            decode_price_fn: Function to decode price values
        """
        self._print_tou_rich(
            name,
            utility,
            zip_code,
            schedules,
            decode_season,
            decode_week,
            decode_price_fn,
        )

    def print_reservations_table(
        self, reservations: list[dict[str, Any]], enabled: bool = False
    ) -> None:
        """Print reservations as a formatted table.

        Args:
            reservations: List of reservation dictionaries
            enabled: Whether reservations are enabled globally
        """
        self._print_reservations_rich(reservations, enabled)

    def _print_success_rich(self, message: str) -> None:
        """Rich-enhanced success output."""
        assert self.console is not None
        panel = cast(Any, Panel)(
            f"[green]✓ {message}[/green]",
            border_style="green",
            padding=(0, 2),
        )
        self.console.print(panel)

    def _print_info_rich(self, message: str) -> None:
        """Rich-enhanced info output."""
        assert self.console is not None
        panel = cast(Any, Panel)(
            f"[blue]ℹ {message}[/blue]",
            border_style="blue",
            padding=(0, 2),
        )
        self.console.print(panel)

    def _print_device_list_rich(self, devices: list[dict[str, Any]]) -> None:
        """Rich-enhanced device list output."""
        assert self.console is not None

        if not devices:
            panel = cast(Any, Panel)("No devices found", border_style="yellow")
            self.console.print(panel)
            return

        table = cast(Any, Table)(title="🏘️ Devices", show_header=True)
        table.add_column("Device Name", style="cyan", width=20)
        table.add_column("Status", width=15)
        table.add_column("Temperature", style="magenta", width=15)
        table.add_column("Power", width=12)
        table.add_column("Updated", style="dim", width=12)

        for device in devices:
            name = device.get("name", "Unknown")
            status = device.get("status", "unknown").lower()
            temp = device.get("temperature", "N/A")
            power = device.get("power", "N/A")
            updated = device.get("updated", "Never")

            # Status indicator
            if status == "online":
                status_indicator = "🟢 Online"
            elif status == "idle":
                status_indicator = "🟡 Idle"
            elif status == "offline":
                status_indicator = "🔴 Offline"
            else:
                status_indicator = f"⚪ {status}"

            table.add_row(
                name, status_indicator, str(temp), str(power), updated
            )

        self.console.print(table)

    def _print_tou_rich(
        self,
        name: str,
        utility: str,
        zip_code: int,
        schedules: Any,
        decode_season: Any,
        decode_week: Any,
        decode_price_fn: Any,
    ) -> None:
        """Rich-enhanced TOU schedule output."""
        assert self.console is not None

        self.console.print()
        self.console.print(
            cast(Any, Panel)(
                f"[bold]{name}[/bold]\n[dim]{utility}  •  ZIP {zip_code}[/dim]",
                title="⚡ TOU Schedule",
                border_style="cyan",
            )
        )

        for sched in schedules:
            months = decode_season(sched.season)
            month_str = _format_months(months)

            table = cast(Any, Table)(
                title=f"Season: {month_str}",
                show_header=True,
                title_style="bold yellow",
            )
            table.add_column("Days", style="cyan", width=20)
            table.add_column("Time", style="white", width=13, justify="right")
            table.add_column(
                "Min $/kWh",
                style="green",
                width=10,
                justify="right",
            )
            table.add_column(
                "Max $/kWh",
                style="green",
                width=10,
                justify="right",
            )

            for iv in sched.intervals:
                days = decode_week(iv.get("week", 0))
                dp = iv.get("decimalPoint", 5)
                p_min = decode_price_fn(iv.get("priceMin", 0), dp)
                p_max = decode_price_fn(iv.get("priceMax", 0), dp)
                time_str = (
                    f"{iv.get('startHour', 0):02d}:"
                    f"{iv.get('startMinute', 0):02d}"
                    f"–{iv.get('endHour', 0):02d}:"
                    f"{iv.get('endMinute', 0):02d}"
                )
                day_str = _abbreviate_days(days)
                table.add_row(
                    day_str,
                    time_str,
                    f"{p_min:.5f}",
                    f"{p_max:.5f}",
                )

            self.console.print(table)

    def _print_reservations_rich(
        self, reservations: list[dict[str, Any]], enabled: bool = False
    ) -> None:
        """Rich-enhanced reservations output."""
        assert self.console is not None

        status_color = "green" if enabled else "red"
        status_text = "ENABLED" if enabled else "DISABLED"
        panel = cast(Any, Panel)(
            f"[{status_color}]{status_text}[/{status_color}]",
            title="📋 Reservations Status",
            border_style=status_color,
        )
        self.console.print(panel)

        if not reservations:
            panel = cast(Any, Panel)("No reservations configured")
            self.console.print(panel)
            return

        table = cast(Any, Table)(
            title="💧 Reservations", show_header=True, highlight=True
        )
        table.add_column("#", style="cyan", width=3, justify="center")
        table.add_column("Status", style="magenta", width=10)
        table.add_column("Days", style="white", width=25)
        table.add_column("Time", style="yellow", width=8, justify="center")
        table.add_column("Mode", style="blue", width=18)
        table.add_column(
            "Temperature", style="green", width=12, justify="center"
        )

        for res in reservations:
            num = str(res.get("number", "?"))
            enabled = res.get("enabled", False)
            status = "[green]✓[/green]" if enabled else "[dim]✗[/dim]"
            days_str = _abbreviate_days(res.get("days", []))
            time_str = res.get("time", "??:??")
            mode = str(res.get("mode", "?"))
            temp = res.get("temperature", "?")
            unit = res.get("unit", "")
            temp_str = f"{temp}{unit}" if temp != "?" else "?"
            table.add_row(num, status, days_str, time_str, mode, temp_str)

        self.console.print(table)

    # Rich implementations

    def _print_status_rich(self, items: list[tuple[str, str, str]]) -> None:
        """Rich-enhanced status output."""
        assert self.console is not None

        table = cast(Any, Table)(title="DEVICE STATUS", show_header=False)

        if not items:
            # Preserve the previous empty-status header rendering.
            width = 44
            print("=" * width)
            print("DEVICE STATUS")
            print("=" * width)
            print("=" * width)
            return

        current_category: str | None = None
        for category, label, value in items:
            if category != current_category:
                # Add category row
                if current_category is not None:
                    table.add_row()
                table.add_row(
                    cast(Any, Text)(category, style="bold cyan"),
                )
                current_category = category

            # Add data row with styling
            table.add_row(
                cast(Any, Text)(f"  {label}", style="magenta"),
                cast(Any, Text)(str(value), style="green"),
            )

        self.console.print(table)

    def _print_energy_summary(self, totals: EnergyTotals, title: str) -> None:
        """Render the shared energy 'TOTAL SUMMARY' block as a Rich table."""
        assert self.console is not None

        table = cast(Any, Table)(title=title, show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")

        total_kwh = totals.total_usage_wh / 1000
        table.add_row(
            "Total Energy Used",
            f"{totals.total_usage_wh:,} Wh ({total_kwh:.2f} kWh)",
        )
        table.add_row(
            "  Heat Pump",
            f"{totals.heat_pump_usage_wh:,} Wh "
            f"({totals.heat_pump_percentage:.1f}%)",
        )
        table.add_row(
            "  Heat Element",
            f"{totals.heat_element_usage_wh:,} Wh "
            f"({totals.heat_element_percentage:.1f}%)",
        )
        table.add_row("Total Time Running", f"{totals.total_time_hours} hours")
        table.add_row("  Heat Pump", f"{totals.heat_pump_time_hours} hours")
        table.add_row(
            "  Heat Element", f"{totals.heat_element_time_hours} hours"
        )
        self.console.print(table)

    def _print_energy_rich(self, months: list[EnergyPeriodRow]) -> None:
        """Rich-enhanced monthly energy breakdown."""
        assert self.console is not None

        table = cast(Any, Table)(title="MONTHLY BREAKDOWN", show_header=True)
        table.add_column("Month", style="cyan", width=15)
        table.add_column(
            "Total kWh", style="magenta", justify="right", width=12
        )
        table.add_column("HP Usage", width=18)
        table.add_column("HE Usage", width=18)

        for month in months:
            total_kwh = month.total_wh / 1000
            hp_kwh = month.heat_pump_wh / 1000
            he_kwh = month.heat_element_wh / 1000
            hp_pct = month.heat_pump_percentage
            he_pct = month.heat_element_percentage

            hp_text, he_text = self._energy_usage_cells(
                hp_kwh, hp_pct, he_kwh, he_pct
            )
            table.add_row(month.label, f"{total_kwh:.1f}", hp_text, he_text)

        self.console.print(table)

    def _energy_usage_cells(
        self, hp_kwh: float, hp_pct: float, he_kwh: float, he_pct: float
    ) -> tuple[str, str]:
        """Build the HP/HE usage cell markup shared by energy tables."""
        hp_bar = self._create_progress_bar(hp_pct, 10)
        he_bar = self._create_progress_bar(he_pct, 10)
        hp_color = (
            "green" if hp_pct >= 70 else ("yellow" if hp_pct >= 50 else "red")
        )
        he_color = (
            "red" if he_pct >= 50 else ("yellow" if he_pct >= 30 else "green")
        )
        hp_text = (
            f"{hp_kwh:.1f} kWh [{hp_color}]{hp_pct:.0f}%[/{hp_color}]\n{hp_bar}"
        )
        he_text = (
            f"{he_kwh:.1f} kWh [{he_color}]{he_pct:.0f}%[/{he_color}]\n{he_bar}"
        )
        return hp_text, he_text

    def _create_progress_bar(self, percentage: float, width: int = 10) -> str:
        """Create a simple progress bar string.

        Args:
            percentage: Percentage value (0-100)
            width: Width of the bar in characters

        Returns:
            Progress bar string
        """
        filled = int((percentage / 100) * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"

    def _print_daily_energy_rich(self, days: list[EnergyPeriodRow]) -> None:
        """Rich-enhanced daily energy breakdown."""
        assert self.console is not None

        table = cast(Any, Table)(title="DAILY BREAKDOWN", show_header=True)
        table.add_column("Day", style="cyan", width=6)
        table.add_column(
            "Total kWh", style="magenta", justify="right", width=12
        )
        table.add_column("HP Usage", width=18)
        table.add_column("HE Usage", width=18)

        for day in days:
            total_kwh = day.total_wh / 1000
            hp_kwh = day.heat_pump_wh / 1000
            he_kwh = day.heat_element_wh / 1000
            hp_text, he_text = self._energy_usage_cells(
                hp_kwh,
                day.heat_pump_percentage,
                he_kwh,
                day.heat_element_percentage,
            )
            table.add_row(day.label, f"{total_kwh:.1f}", hp_text, he_text)

        self.console.print(table)

    def _print_error_rich(
        self,
        message: str,
        title: str,
        details: list[str] | None = None,
    ) -> None:
        """Rich-enhanced error output."""
        assert self.console is not None

        content = f"❌ {title}\n\n{message}"
        if details:
            content += "\n\nDetails:"
            for detail in details:
                content += f"\n  • {detail}"

        panel = cast(Any, Panel)(
            content,
            border_style="red",
            padding=(1, 2),
        )
        self.console.print(panel)

    # Phase 3: Advanced Features

    def print_json_highlighted(self, data: Any) -> None:
        """Print JSON with syntax highlighting.

        Args:
            data: Data to print as JSON
        """
        self._print_json_highlighted_rich(data)

    def print_device_tree(
        self, device_name: str, device_info: dict[str, Any]
    ) -> None:
        """Print device information as a tree structure.

        Args:
            device_name: Name of the device
            device_info: Dictionary of device information
        """
        self._print_device_tree_rich(device_name, device_info)

    def print_markdown_report(self, markdown_content: str) -> None:
        """Print markdown-formatted content.

        Args:
            markdown_content: Markdown formatted string
        """
        self._print_markdown_rich(markdown_content)

    # Rich implementations (Phase 3)

    def _print_json_highlighted_rich(self, data: Any) -> None:
        """Rich-enhanced JSON output with syntax highlighting."""
        assert self.console is not None

        json_str = json.dumps(data, indent=2, default=str)
        syntax = cast(Any, Syntax)(
            json_str, "json", theme="monokai", line_numbers=False
        )
        self.console.print(syntax)

    def _print_device_tree_rich(
        self, device_name: str, device_info: dict[str, Any]
    ) -> None:
        """Rich-enhanced tree output for device information."""
        assert self.console is not None

        tree = cast(Any, Tree)(f"📱 {device_name}", guide_style="bold cyan")

        # Organize info into categories
        categories = {
            "🆔 Identity": [
                "serial_number",
                "model_type",
                "country_code",
                "volume_code",
            ],
            "🔧 Firmware": [
                "controller_version",
                "panel_version",
                "wifi_version",
                "recirc_version",
            ],
            "⚙️ Configuration": [
                "temperature_unit",
                "dhw_temp_range",
                "freeze_protection_range",
            ],
            "✨ Features": [
                "power_control",
                "heat_pump_mode",
                "recirculation",
                "energy_usage",
            ],
        }

        for category, keys in categories.items():
            category_node = tree.add(category)
            for key in keys:
                if key in device_info:
                    value = device_info[key]
                    category_node.add(f"{key}: [green]{value}[/green]")

        self.console.print(tree)

    def _print_markdown_rich(self, content: str) -> None:
        """Rich-enhanced markdown rendering."""
        assert self.console is not None

        markdown = cast(Any, Markdown)(content)
        self.console.print(markdown)


# Global formatter instance
_formatter: OutputFormatter | None = None


def get_formatter() -> OutputFormatter:
    """Get the global formatter instance.

    Returns:
        OutputFormatter instance with Rich support if available.
    """
    global _formatter
    if _formatter is None:
        _formatter = OutputFormatter()
    return _formatter
