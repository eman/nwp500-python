"""``nwp-cli --backend ble``: run device commands over Bluetooth LE.

Imported only when that backend is chosen, so the MQTT path never loads
:mod:`nwp500.ble`. The command handlers are unchanged: they receive a
:class:`~nwp500.ble.BleMqttAdapter` where they would receive a
:class:`~nwp500.NavienMqttClient`. Only the commands whose data the heater
sends over Bluetooth are accepted; the rest are refused before connecting.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import click

from nwp500.ble import (
    BleMqttAdapter,
    BleUnsupportedError,
    CrcMismatchError,
    NavienBleClient,
    device_feature_from_blocks,
    scan,
)
from nwp500.unit_system import set_unit_system

from .rich_output import get_formatter

_logger = logging.getLogger(__name__)
_formatter = get_formatter()

#: Top-level commands that work over Bluetooth.
SUPPORTED_COMMANDS = frozenset({"info", "serial"})

SCAN_SECONDS = 10.0


def check_supported(ctx: click.Context) -> None:
    """Refuse a command that has no Bluetooth equivalent.

    Raises:
        click.UsageError: The command is not in :data:`SUPPORTED_COMMANDS`.
    """
    path = ctx.command_path.split()[1:]
    if len(path) != 1 or path[0] not in SUPPORTED_COMMANDS:
        name = " ".join(path) or ctx.info_name or "this command"
        raise click.UsageError(
            f"'{name}' is not available over Bluetooth. With --backend ble "
            f"use: {', '.join(sorted(SUPPORTED_COMMANDS))}. The heater "
            "sends no live status over Bluetooth and accepts no writes."
        )


async def _find_address() -> str | None:
    found = await scan(SCAN_SECONDS)
    if not found:
        return None
    address, name, rssi = max(found, key=lambda t: t[2])
    _logger.info(f"Using {name} at {address} (rssi {rssi})")
    return address


async def run_with_ble(
    ctx: click.Context,
    command: Callable[[Any, Any], Awaitable[None]],
) -> int:
    """Connect over Bluetooth and run ``command`` with the adapter.

    The device argument is ``None``: there is no cloud device record
    without signing in, and the adapter ignores it. Returns the exit code.
    """
    check_supported(ctx)
    # As on the cloud path; there is no device report to detect the unit
    # from, so without --unit-system the models fall back to Fahrenheit.
    if ctx.obj.get("unit_system"):
        set_unit_system(ctx.obj["unit_system"])
    try:
        address = ctx.obj.get("ble_address") or await _find_address()
        if address is None:
            _formatter.print_error(
                "No heater advertising. Hold Back + Power for 5 s to "
                "enter pairing mode, or pass --ble-address.",
                title="Bluetooth",
            )
            return 1
        async with BleMqttAdapter(NavienBleClient(address)) as adapter:
            ctx.obj["ble_adapter"] = adapter
            await command(adapter, None)
        return 0
    except click.ClickException:
        raise
    except BleUnsupportedError as e:
        _formatter.print_error(str(e), title="Not Available Over Bluetooth")
    except RuntimeError as e:
        # The ble extra is missing, or bleak could not reach the adapter.
        _formatter.print_error(str(e), title="Bluetooth")
    except (TimeoutError, CrcMismatchError) as e:
        _formatter.print_error(
            str(e) or "The heater did not answer.", title="Bluetooth"
        )
    except Exception as e:
        _logger.error(f"Unexpected error: {e}", exc_info=True)
        _formatter.print_error(str(e), title="Unexpected Error")
    return 1


async def print_info(adapter: BleMqttAdapter, raw: bool) -> None:
    """``info`` over Bluetooth: what the ``DID`` and ``MSCD`` blocks hold.

    Only fields read from the heater are shown. The MQTT ``info`` output
    covers capability flags and firmware versions, which these blocks do
    not carry.
    """
    await adapter.request_device_info(None)
    info, serials = adapter.device_info, adapter.controller_serials
    if info is None or serials is None:  # request_device_info sets both
        raise RuntimeError("device info was not read")
    if raw:
        print(
            json.dumps(
                {"DID": info.raw.hex(), "MSCD": serials.raw.hex()}, indent=2
            )
        )
        return
    feature = device_feature_from_blocks(info, serials)
    unit = feature.get_field_unit("dhw_temperature_min")
    lo, hi = feature.dhw_temperature_min, feature.dhw_temperature_max
    rows = [
        ("Controller serial", serials.product_serial),
        ("PCB serial", serials.pcb_serial),
        ("Model type code", str(info.model_type)),
        ("Country code", str(info.country_code)),
        ("Setpoint range", f"{lo:.1f} - {hi:.1f}{unit}"),
        ("Min operation temp", f"{info.min_operation_temperature():.1f}{unit}"),
    ]
    width = max(len(label) for label, _ in rows)
    print("Device info (Bluetooth: DID and MSCD blocks)")
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")
