"""CLI package for nwp500-python."""

from .__main__ import run
from .commands import (
    handle_device_feature_request,
    handle_device_info_request,
    handle_get_controller_serial_request,
    handle_get_energy_request,
    handle_get_reservations_request,
    handle_get_tou_request,
    handle_power_request,
    handle_set_dhw_temp_request,
    handle_set_mode_request,
    handle_set_tou_enabled_request,
    handle_status_raw_request,
    handle_status_request,
    handle_update_reservations_request,
)
from .monitoring import handle_monitoring
from .output_formatters import (
    format_json_output,
    print_json,
    write_status_to_csv,
)
from .token_storage import load_tokens, save_tokens

__all__ = [
    # Main entry point
    "run",
    # Command handlers
    "handle_device_feature_request",
    "handle_device_info_request",
    "handle_get_controller_serial_request",
    "handle_get_energy_request",
    "handle_get_reservations_request",
    "handle_get_tou_request",
    "handle_monitoring",
    "handle_power_request",
    "handle_set_dhw_temp_request",
    "handle_set_mode_request",
    "handle_set_tou_enabled_request",
    "handle_status_raw_request",
    "handle_status_request",
    "handle_update_reservations_request",
    # Output formatters
    "format_json_output",
    "print_json",
    "write_status_to_csv",
    # Token storage
    "load_tokens",
    "save_tokens",
]
