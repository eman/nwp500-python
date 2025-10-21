"""Navien Water Heater Control Script - Backward Compatibility Wrapper.

This module maintains backward compatibility by importing from the
new modular cli package structure.
"""

# Main entry points
from nwp500.cli.__main__ import (
    async_main,
    get_authenticated_client,
    main,
    parse_args,
    run,
    setup_logging,
)

# Command handlers
from nwp500.cli.commands import (
    handle_device_feature_request,
    handle_device_info_request,
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

# Monitoring
from nwp500.cli.monitoring import handle_monitoring

# Output formatters
from nwp500.cli.output_formatters import (
    _json_default_serializer,
    format_json_output,
    print_json,
    write_status_to_csv,
)

# Token storage
from nwp500.cli.token_storage import TOKEN_FILE, load_tokens, save_tokens

__all__ = [
    "async_main",
    "get_authenticated_client",
    "handle_device_feature_request",
    "handle_device_info_request",
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
    "_json_default_serializer",
    "format_json_output",
    "main",
    "parse_args",
    "print_json",
    "run",
    "setup_logging",
    "TOKEN_FILE",
    "load_tokens",
    "save_tokens",
    "write_status_to_csv",
]

if __name__ == "__main__":
    run()
