"""Rich-enhanced output formatting with graceful fallback."""

import json
import logging
import os
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
