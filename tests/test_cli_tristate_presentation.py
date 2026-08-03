"""CLI rendering of tri-state status flags.

The device encodes these flags as 0 = unknown, 1 = OFF, 2 = ON. A field
reading 0 must never be presented as "No" - that reports a definite OFF
the device never claimed.

This module guards the presentation layer specifically, because the model
change is easy to make without updating every render site: a missed one
is silent, since ``None`` is falsy and a two-way ternary happily prints
"No".
"""

import pytest

# The CLI package pulls in the optional `cli` extra (click/rich). Skip
# rather than hard-fail when running against a bare install.
pytest.importorskip("rich", reason="requires the 'cli' extra")
pytest.importorskip("click", reason="requires the 'cli' extra")

from nwp500.cli.presentation import (
    _yes_no_unknown,
    build_device_status_rows,
)
from nwp500.models import DeviceStatus

# Status flags typed DeviceTriState, with the row label the CLI gives each.
# Only those actually rendered by build_device_status_rows appear here.
RENDERED_TRISTATE_ROWS = {
    "operation_busy": ("OPERATION STATUS", "Busy"),
    "anti_legionella_operation_busy": ("ANTI-LEGIONELLA", "Operation Busy"),
}

TRISTATE_ALIASES = {
    "operation_busy": "operationBusy",
    "anti_legionella_operation_busy": "antiLegionellaOperationBusy",
}


class TestYesNoUnknown:
    """The formatter itself."""

    def test_none_is_unknown(self):
        assert _yes_no_unknown(None) == "Unknown"

    def test_true_is_yes(self):
        assert _yes_no_unknown(True) == "Yes"

    def test_false_is_no(self):
        assert _yes_no_unknown(False) == "No"

    def test_all_three_are_distinct(self):
        rendered = [_yes_no_unknown(v) for v in (None, False, True)]
        assert len(set(rendered)) == 3


class TestTriStateRendering:
    """End-to-end: a 0 on the wire must reach the CLI as "Unknown"."""

    def _rows(self, status_data, alias, raw):
        """Build the CLI rows, keyed by (section, label)."""
        data = dict(status_data)
        data[alias] = raw
        return {
            (section, label): value
            for section, label, value in build_device_status_rows(
                DeviceStatus(**data)
            )
        }

    @pytest.mark.parametrize(
        ("field", "location"), list(RENDERED_TRISTATE_ROWS.items())
    )
    def test_zero_renders_unknown(self, device_status_dict, field, location):
        """0 must not be presented as "No"."""
        rows = self._rows(device_status_dict, TRISTATE_ALIASES[field], 0)
        assert rows[location] == "Unknown"

    @pytest.mark.parametrize(
        ("field", "location"), list(RENDERED_TRISTATE_ROWS.items())
    )
    def test_one_renders_no(self, device_status_dict, field, location):
        """1 is a real OFF and still reads "No"."""
        rows = self._rows(device_status_dict, TRISTATE_ALIASES[field], 1)
        assert rows[location] == "No"

    @pytest.mark.parametrize(
        ("field", "location"), list(RENDERED_TRISTATE_ROWS.items())
    )
    def test_two_renders_yes(self, device_status_dict, field, location):
        """2 is a real ON and still reads "Yes"."""
        rows = self._rows(device_status_dict, TRISTATE_ALIASES[field], 2)
        assert rows[location] == "Yes"


def test_no_tristate_field_uses_a_two_way_ternary():
    """Structural guard against the miss this test module exists for.

    A two-way ``"Yes" if <tristate> else "No"`` compiles and passes any
    test that only exercises 1 and 2, then silently mislabels unknown as
    "No". Catch it in the source instead.
    """
    from pathlib import Path

    import nwp500.cli.presentation as presentation

    source = Path(presentation.__file__).read_text()
    tristate_fields = (
        "operation_busy",
        "comp_use",
        "anti_legionella_use",
        "anti_legionella_operation_busy",
        "heat_upper_use",
        "heat_lower_use",
        "air_filter_alarm_use",
        "recirc_reservation_use",
    )
    offenders = [
        line.strip()
        for line in source.splitlines()
        if '"Yes" if' in line
        and any(f".{field}" in line for field in tristate_fields)
    ]
    assert not offenders, (
        "tri-state fields rendered with a two-way ternary "
        f"(use _yes_no_unknown): {offenders}"
    )
