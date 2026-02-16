"""Rich-enhanced output formatting with graceful fallback."""

import json
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
    from rich.tree import Tree

_rich_available = False

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
    from rich.tree import Tree

    _rich_available = True
except ImportError:
    Console = None  # type: ignore[assignment,misc]
    Markdown = None  # type: ignore[assignment,misc]
    Panel = None  # type: ignore[assignment,misc]
    Syntax = None  # type: ignore[assignment,misc]
    Table = None  # type: ignore[assignment,misc]
    Text = None  # type: ignore[assignment,misc]
    Tree = None  # type: ignore[assignment,misc]

_logger = logging.getLogger(__name__)


def _should_use_rich() -> bool:
    """Check if Rich should be used.

    Returns:
        True if Rich is available and enabled, False otherwise.
    """
    if not _rich_available:
        return False
    # Allow explicit override via environment variable
    return os.getenv("NWP500_NO_RICH", "0") != "1"


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
    for prev, curr in zip(items, items[1:], strict=False):
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
    """Unified output formatter with Rich enhancement support.

    Automatically detects Rich availability and routes output to the
    appropriate formatter. Falls back to plain text when Rich is
    unavailable or explicitly disabled.
    """

    def __init__(self) -> None:
        """Initialize the formatter."""
        self.use_rich = _should_use_rich()
        self.console: Any
        if self.use_rich:
            assert Console is not None
            self.console = Console()
        else:
            self.console = None

    def print_status_table(self, items: list[tuple[str, str, str]]) -> None:
        """Print status items as a formatted table.

        Args:
            items: List of (category, label, value) tuples
        """
        if not self.use_rich:
            self._print_status_plain(items)
        else:
            self._print_status_rich(items)

    def print_energy_table(self, months: list[dict[str, Any]]) -> None:
        """Print energy usage data as a formatted table.

        Args:
            months: List of monthly energy data dictionaries
        """
        if not self.use_rich:
            self._print_energy_plain(months)
        else:
            self._print_energy_rich(months)

    def print_daily_energy_table(
        self, days: list[dict[str, Any]], year: int, month: int
    ) -> None:
        """Print daily energy usage data as a formatted table.

        Args:
            days: List of daily energy data dictionaries
            year: Year for the data
            month: Month for the data
        """
        if not self.use_rich:
            self._print_daily_energy_plain(days, year, month)
        else:
            self._print_daily_energy_rich(days, year, month)

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
        if not self.use_rich:
            self._print_error_plain(message, title, details)
        else:
            self._print_error_rich(message, title, details)

    def print_success(self, message: str) -> None:
        """Print a success message.

        Args:
            message: Success message to display
        """
        if not self.use_rich:
            print(f"✓ {message}")
        else:
            self._print_success_rich(message)

    def print_info(self, message: str) -> None:
        """Print an info message.

        Args:
            message: Info message to display
        """
        if not self.use_rich:
            print(f"ℹ {message}")
        else:
            self._print_info_rich(message)

    def print_device_list(self, devices: list[dict[str, Any]]) -> None:
        """Print list of devices with status indicators.

        Args:
            devices: List of device dictionaries with status info
        """
        if not self.use_rich:
            self._print_device_list_plain(devices)
        else:
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
        if not self.use_rich:
            self._print_tou_plain(
                name,
                utility,
                zip_code,
                schedules,
                decode_season,
                decode_week,
                decode_price_fn,
            )
        else:
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
        if not self.use_rich:
            self._print_reservations_plain(reservations, enabled)
        else:
            self._print_reservations_rich(reservations, enabled)

    # Plain text implementations (fallback)

    def _print_status_plain(self, items: list[tuple[str, str, str]]) -> None:
        """Plain text status output (fallback)."""
        # Calculate widths
        max_label = max((len(label) for _, label, _ in items), default=20)
        max_value = max((len(str(value)) for _, _, value in items), default=20)
        width = max_label + max_value + 4

        # Print header
        print("=" * width)
        print("DEVICE STATUS")
        print("=" * width)

        # Print items grouped by category
        if items:
            current_category: str | None = None
            for category, label, value in items:
                if category != current_category:
                    if current_category is not None:
                        print()
                    print(category)
                    print("-" * width)
                    current_category = category
                print(f"  {label:<{max_label}}  {value}")

        print("=" * width)

    def _print_energy_plain(self, months: list[dict[str, Any]]) -> None:
        """Plain text energy output (fallback)."""
        # This is a simplified version - the actual rendering comes from
        # output_formatters.format_energy_usage()
        print("ENERGY USAGE REPORT")
        print("=" * 90)
        for month in months:
            print(f"{month}")

    def _print_device_list_plain(self, devices: list[dict[str, Any]]) -> None:
        """Plain text device list output (fallback)."""
        if not devices:
            print("No devices found")
            return

        print("DEVICES")
        print("-" * 80)
        for device in devices:
            name = device.get("name", "Unknown")
            status = device.get("status", "Unknown")
            temp = device.get("temperature", "N/A")
            print(f"  {name:<20} {status:<15} {temp}")
        print("-" * 80)

    def _print_tou_plain(
        self,
        name: str,
        utility: str,
        zip_code: int,
        schedules: Any,
        decode_season: Any,
        decode_week: Any,
        decode_price_fn: Any,
    ) -> None:
        """Plain text TOU schedule output."""
        print("TOU SCHEDULE")
        print("=" * 72)
        print(f"  Plan:    {name}")
        print(f"  Utility: {utility}")
        print(f"  ZIP:     {zip_code}")
        print("=" * 72)

        for sched in schedules:
            months = decode_season(sched.season)
            month_str = _format_months(months)
            print(f"\n  Season: {month_str}")
            print(
                f"  {'Days':<20} {'Time':>13}"
                f"  {'Min $/kWh':>10}  {'Max $/kWh':>10}"
            )
            print(f"  {'-' * 57}")
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
                print(
                    f"  {day_str:<20} {time_str:>13}"
                    f"  {p_min:>10.5f}  {p_max:>10.5f}"
                )

    def _print_reservations_plain(
        self, reservations: list[dict[str, Any]], enabled: bool = False
    ) -> None:
        """Plain text reservations output (fallback)."""
        status_str = "ENABLED" if enabled else "DISABLED"
        print(f"Reservations: {status_str}")
        print()

        if not reservations:
            print("No reservations configured")
            return

        print("RESERVATIONS")
        print("=" * 80)
        print(
            f"  {'#':<3} {'Enabled':<10} {'Days':<25} "
            f"{'Time':<8} {'Temp (°F)':<10}"
        )
        print("=" * 80)

        for res in reservations:
            num = res.get("number", "?")
            is_enabled = res.get("enabled", False)
            enabled_str = "Yes" if is_enabled else "No"
            days_str = _abbreviate_days(res.get("days", []))
            time_str = res.get("time", "??:??")
            temp = res.get("temperatureF", "?")
            print(
                f"  {num:<3} {enabled_str:<10} {days_str:<25} "
                f"{time_str:<8} {temp:<10}"
            )
        print("=" * 80)

    def _print_error_plain(
        self,
        message: str,
        title: str,
        details: list[str] | None = None,
    ) -> None:
        """Plain text error output (fallback)."""
        print(f"{title}: {message}")
        if details:
            for detail in details:
                print(f"  • {detail}")

    def _print_success_rich(self, message: str) -> None:
        """Rich-enhanced success output."""
        assert self.console is not None
        assert _rich_available
        panel = cast(Any, Panel)(
            f"[green]✓ {message}[/green]",
            border_style="green",
            padding=(0, 2),
        )
        self.console.print(panel)

    def _print_info_rich(self, message: str) -> None:
        """Rich-enhanced info output."""
        assert self.console is not None
        assert _rich_available
        panel = cast(Any, Panel)(
            f"[blue]ℹ {message}[/blue]",
            border_style="blue",
            padding=(0, 2),
        )
        self.console.print(panel)

    def _print_device_list_rich(self, devices: list[dict[str, Any]]) -> None:
        """Rich-enhanced device list output."""
        assert self.console is not None
        assert _rich_available

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
        assert _rich_available

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
        assert _rich_available

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
        table.add_column("Temp (°F)", style="green", width=10, justify="center")

        for res in reservations:
            num = str(res.get("number", "?"))
            enabled = res.get("enabled", False)
            status = "[green]✓[/green]" if enabled else "[dim]✗[/dim]"
            days_str = _abbreviate_days(res.get("days", []))
            time_str = res.get("time", "??:??")
            temp = str(res.get("temperatureF", "?"))
            table.add_row(num, status, days_str, time_str, temp)

        self.console.print(table)

    # Rich implementations

    def _print_status_rich(self, items: list[tuple[str, str, str]]) -> None:
        """Rich-enhanced status output."""
        assert self.console is not None
        assert _rich_available

        table = cast(Any, Table)(title="DEVICE STATUS", show_header=False)

        if not items:
            # If no items, just print the header using plain text
            # to match expected output
            self._print_status_plain(items)
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

    def _print_energy_rich(self, months: list[dict[str, Any]]) -> None:
        """Rich-enhanced energy output."""
        assert self.console is not None
        assert _rich_available

        table = cast(Any, Table)(title="ENERGY USAGE REPORT", show_header=True)
        table.add_column("Month", style="cyan", width=15)
        table.add_column(
            "Total kWh", style="magenta", justify="right", width=12
        )
        table.add_column("HP Usage", width=18)
        table.add_column("HE Usage", width=18)

        for month in months:
            month_str = month.get("month_str", "N/A")
            total_kwh = month.get("total_kwh", 0)
            hp_kwh = month.get("hp_kwh", 0)
            he_kwh = month.get("he_kwh", 0)
            hp_pct = month.get("hp_pct", 0)
            he_pct = month.get("he_pct", 0)

            # Create progress bar representations
            hp_bar = self._create_progress_bar(hp_pct, 10)
            he_bar = self._create_progress_bar(he_pct, 10)

            # Color code based on efficiency
            hp_color = (
                "green"
                if hp_pct >= 70
                else ("yellow" if hp_pct >= 50 else "red")
            )
            he_color = (
                "red"
                if he_pct >= 50
                else ("yellow" if he_pct >= 30 else "green")
            )

            hp_text = (
                f"{hp_kwh:.1f} kWh "
                f"[{hp_color}]{hp_pct:.0f}%[/{hp_color}]\n{hp_bar}"
            )
            he_text = (
                f"{he_kwh:.1f} kWh "
                f"[{he_color}]{he_pct:.0f}%[/{he_color}]\n{he_bar}"
            )

            table.add_row(month_str, f"{total_kwh:.1f}", hp_text, he_text)

        self.console.print(table)

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

    def _print_daily_energy_plain(
        self, days: list[dict[str, Any]], year: int, month: int
    ) -> None:
        """Plain text daily energy output (fallback)."""
        # This is a simplified version - the actual rendering comes from
        # output_formatters.format_daily_energy_usage()
        from calendar import month_name

        month_str = (
            f"{month_name[month]} {year}"
            if 1 <= month <= 12
            else f"Month {month} {year}"
        )
        print(f"DAILY ENERGY USAGE - {month_str}")
        print("=" * 100)
        for day in days:
            print(f"{day}")

    def _print_daily_energy_rich(
        self, days: list[dict[str, Any]], year: int, month: int
    ) -> None:
        """Rich-enhanced daily energy output."""
        from calendar import month_name

        assert self.console is not None
        assert _rich_available

        month_str = (
            f"{month_name[month]} {year}"
            if 1 <= month <= 12
            else f"Month {month} {year}"
        )
        table = cast(Any, Table)(
            title=f"DAILY ENERGY USAGE - {month_str}", show_header=True
        )
        table.add_column("Day", style="cyan", width=6)
        table.add_column(
            "Total kWh", style="magenta", justify="right", width=12
        )
        table.add_column("HP Usage", width=18)
        table.add_column("HE Usage", width=18)

        for day in days:
            day_num = day.get("day", "N/A")
            total_kwh = day.get("total_kwh", 0)
            hp_kwh = day.get("hp_kwh", 0)
            he_kwh = day.get("he_kwh", 0)
            hp_pct = day.get("hp_pct", 0)
            he_pct = day.get("he_pct", 0)

            # Create progress bar representations
            hp_bar = self._create_progress_bar(hp_pct, 10)
            he_bar = self._create_progress_bar(he_pct, 10)

            # Color code based on efficiency
            hp_color = (
                "green"
                if hp_pct >= 70
                else ("yellow" if hp_pct >= 50 else "red")
            )
            he_color = (
                "red"
                if he_pct >= 50
                else ("yellow" if he_pct >= 30 else "green")
            )

            hp_text = (
                f"{hp_kwh:.1f} kWh "
                f"[{hp_color}]{hp_pct:.0f}%[/{hp_color}]\n{hp_bar}"
            )
            he_text = (
                f"{he_kwh:.1f} kWh "
                f"[{he_color}]{he_pct:.0f}%[/{he_color}]\n{he_bar}"
            )

            table.add_row(str(day_num), f"{total_kwh:.1f}", hp_text, he_text)

        self.console.print(table)

    def _print_error_rich(
        self,
        message: str,
        title: str,
        details: list[str] | None = None,
    ) -> None:
        """Rich-enhanced error output."""
        assert self.console is not None
        assert _rich_available

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
        if not self.use_rich:
            print(json.dumps(data, indent=2, default=str))
        else:
            self._print_json_highlighted_rich(data)

    def print_device_tree(
        self, device_name: str, device_info: dict[str, Any]
    ) -> None:
        """Print device information as a tree structure.

        Args:
            device_name: Name of the device
            device_info: Dictionary of device information
        """
        if not self.use_rich:
            self._print_device_tree_plain(device_name, device_info)
        else:
            self._print_device_tree_rich(device_name, device_info)

    def print_markdown_report(self, markdown_content: str) -> None:
        """Print markdown-formatted content.

        Args:
            markdown_content: Markdown formatted string
        """
        if not self.use_rich:
            print(markdown_content)
        else:
            self._print_markdown_rich(markdown_content)

    # Plain text implementations (Phase 3 fallback)

    def _print_json_highlighted_plain(self, data: Any) -> None:
        """Plain text JSON output (fallback)."""
        print(json.dumps(data, indent=2, default=str))

    def _print_device_tree_plain(
        self, device_name: str, device_info: dict[str, Any]
    ) -> None:
        """Plain text tree output (fallback)."""
        print(f"Device: {device_name}")
        for key, value in device_info.items():
            print(f"  {key}: {value}")

    # Rich implementations (Phase 3)

    def _print_json_highlighted_rich(self, data: Any) -> None:
        """Rich-enhanced JSON output with syntax highlighting."""
        assert self.console is not None
        assert _rich_available

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
        assert _rich_available

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
        assert _rich_available

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
