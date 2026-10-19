"""Enum and status-field values verified against NaviLink 2.04.00 (build 201).

Each assertion mirrors a declaration in the decompiled app (``KDEnum.java``
and ``KDResponseMgppStatus.java``), so a change here must be checked against
the app, not just the library.
"""

from typing import Any

import pytest

from nwp500.enums import (
    DHW_OPERATION_SETTING_TEXT,
    DR_EVENT_TEXT,
    RECIRC_MODE_TEXT,
    RESERVATION_MODE_TEXT,
    DeviceType,
    DhwOperationSetting,
    DREvent,
    RecirculationMode,
    ReservationMode,
    UnitType,
)
from nwp500.models import DeviceStatus, ReservationEntry


class TestRecirculationMode:
    """App ``MgppRecirculationOperationMode``: 0 Unknown, 1 Always on,
    2 Weekly, 3 HotButton only, 4 No recirculation."""

    @pytest.mark.parametrize(
        ("member", "value"),
        [
            (RecirculationMode.UNKNOWN, 0),
            (RecirculationMode.ALWAYS_ON, 1),
            (RecirculationMode.WEEKLY, 2),
            (RecirculationMode.HOT_BUTTON_ONLY, 3),
            (RecirculationMode.OFF, 4),
        ],
    )
    def test_values(self, member: RecirculationMode, value: int) -> None:
        assert member == value
        assert RecirculationMode(value) is member

    def test_always_alias(self) -> None:
        assert RecirculationMode.ALWAYS is RecirculationMode.ALWAYS_ON
        assert RecirculationMode(1).name == "ALWAYS_ON"

    def test_old_wrong_members_removed(self) -> None:
        for name in ("BUTTON", "SCHEDULE", "TEMPERATURE"):
            assert not hasattr(RecirculationMode, name)

    def test_text_covers_every_member(self) -> None:
        assert set(RECIRC_MODE_TEXT) == set(RecirculationMode)
        assert RECIRC_MODE_TEXT[RecirculationMode.WEEKLY] == "Weekly"
        assert RECIRC_MODE_TEXT[RecirculationMode.OFF] == "No Recirculation"

    def test_status_decodes_hot_button_only(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        data = {**device_status_dict, "recircOperationMode": 3}
        status = DeviceStatus(**data)
        assert status.recirc_operation_mode is RecirculationMode.HOT_BUTTON_ONLY


class TestReservationMode:
    """App ``MgppReservationMode``: 0 NOT_RESERVATION .. 5 POWER_OFF,
    no vacation."""

    @pytest.mark.parametrize(
        ("member", "value"),
        [
            (ReservationMode.NOT_RESERVATION, 0),
            (ReservationMode.HEAT_PUMP, 1),
            (ReservationMode.ELECTRIC, 2),
            (ReservationMode.ENERGY_SAVER, 3),
            (ReservationMode.HIGH_DEMAND, 4),
            (ReservationMode.POWER_OFF, 5),
        ],
    )
    def test_values(self, member: ReservationMode, value: int) -> None:
        assert member == value
        assert ReservationMode(value) is member

    def test_no_vacation_and_no_six(self) -> None:
        assert not hasattr(ReservationMode, "VACATION")
        with pytest.raises(ValueError):
            ReservationMode(6)

    def test_text_covers_every_member(self) -> None:
        assert set(RESERVATION_MODE_TEXT) == set(ReservationMode)

    def test_entry_mode_5_is_power_off(self) -> None:
        """Previously resolved through DhwOperationSetting as "Vacation"."""
        assert ReservationEntry(mode=5).mode_name == "Power Off"

    def test_entry_mode_0_and_unknown(self) -> None:
        assert ReservationEntry(mode=0).mode_name == "Not Reserved"
        assert ReservationEntry(mode=6).mode_name == "Unknown (6)"

    @pytest.mark.parametrize(
        ("mode", "text"),
        [
            (1, "Heat Pump"),
            (2, "Electric"),
            (3, "Energy Saver"),
            (4, "High Demand"),
        ],
    )
    def test_entry_modes_1_to_4_unchanged(self, mode: int, text: str) -> None:
        assert ReservationEntry(mode=mode).mode_name == text


class TestDhwOperationSettingStandby:
    """App ``MgppOperationMode.STANDBY(0)``."""

    def test_standby_member(self) -> None:
        assert DhwOperationSetting.STANDBY == 0
        text = DHW_OPERATION_SETTING_TEXT[DhwOperationSetting.STANDBY]
        assert text == "Standby"

    def test_status_accepts_zero(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        data = {**device_status_dict, "dhwOperationSetting": 0}
        status = DeviceStatus(**data)
        assert status.dhw_operation_setting is DhwOperationSetting.STANDBY

    def test_other_values_unchanged(self) -> None:
        assert DhwOperationSetting.VACATION == 5
        assert DhwOperationSetting.POWER_OFF == 6


class TestDREvent:
    """App decodes ``drEventStatus`` by array position: CPE is index 5 and
    GRID_ENERGY ("Grid Emergency") is index 6."""

    def test_cpe_and_grid_emergency(self) -> None:
        assert DREvent.CPE == 5
        assert DREvent.GRID_EMERGENCY == 6
        assert DR_EVENT_TEXT[DREvent.CPE] == "Customer Peak Event"
        assert DR_EVENT_TEXT[DREvent.GRID_EMERGENCY] == "Grid Emergency"

    def test_text_covers_every_member(self) -> None:
        assert set(DR_EVENT_TEXT) == set(DREvent)

    def test_status_decodes_six(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        status = DeviceStatus(**{**device_status_dict, "drEventStatus": 6})
        assert status.dr_event_status is DREvent.GRID_EMERGENCY


class TestUnitAndDeviceType:
    def test_new_unit_types(self) -> None:
        assert UnitType.NCB700 == 22
        assert UnitType.NFB700_H == 24
        assert UnitType.CAS_NFB700_H == 25
        assert UnitType.NPF_SYSTEM == 514
        assert UnitType.NPF == 513

    def test_device_type_names_and_aliases(self) -> None:
        assert DeviceType.IOT_MODULE == 8
        assert DeviceType.NFB700_MAIN == 50
        assert DeviceType.NFB700_SUB == 51
        assert DeviceType.NPF700_MAIN is DeviceType.NFB700_MAIN
        assert DeviceType.NPF700_SUB is DeviceType.NFB700_SUB
        assert DeviceType(50).name == "NFB700_MAIN"

    def test_hpwh_alias(self) -> None:
        assert DeviceType.HPWH == 52
        assert DeviceType.HPWH is DeviceType.NPF700_WIFI
        assert DeviceType(52).name == "NPF700_WIFI"


class TestDrOverrideStatus:
    """App decodes ``drOverrideStatus`` with ``MgppOnOFFFlag`` (0/1/2) and
    shows "DR applied" when it is ON (2)."""

    @pytest.mark.parametrize(
        ("raw", "active"), [(0, False), (1, False), (2, True)]
    )
    def test_dr_override_active(
        self, device_status_dict: dict[str, Any], raw: int, active: bool
    ) -> None:
        status = DeviceStatus(**{**device_status_dict, "drOverrideStatus": raw})
        assert status.dr_override_status == raw
        assert status.dr_override_active is active

    def test_no_hours_unit(self) -> None:
        field = DeviceStatus.model_fields["dr_override_status"]
        extra = field.json_schema_extra
        assert not (isinstance(extra, dict) and "unit_of_measurement" in extra)

    def test_in_model_dump(self, device_status_dict: dict[str, Any]) -> None:
        status = DeviceStatus(**{**device_status_dict, "drOverrideStatus": 2})
        assert status.model_dump()["dr_override_active"] is True


class TestAirFilterRemainingHours:
    """App: ``remain = airFilterAlarmPeriod - cumulatedOpTimeEvaFan``;
    ``airFilterAlarmElapsed`` is never read."""

    @pytest.mark.parametrize(
        ("period", "fan", "expected"),
        [
            (1000, 0, 1000),
            (1000, 400, 600),
            (1000, 1000, 0),
            (1000, 1200, 0),
            (0, 500, None),
        ],
    )
    def test_remaining(
        self,
        device_status_dict: dict[str, Any],
        period: int,
        fan: int,
        expected: int | None,
    ) -> None:
        status = DeviceStatus(
            **{
                **device_status_dict,
                "airFilterAlarmPeriod": period,
                "cumulatedOpTimeEvaFan": fan,
                "airFilterAlarmElapsed": 999,
            }
        )
        assert status.air_filter_remaining_hours == expected

    def test_in_model_dump(self, device_status_dict: dict[str, Any]) -> None:
        status = DeviceStatus(**device_status_dict)
        assert "air_filter_remaining_hours" in status.model_dump()


class TestMinorCode:
    def test_default_zero(self, device_status_dict: dict[str, Any]) -> None:
        assert "minorCode" not in device_status_dict
        assert DeviceStatus(**device_status_dict).minor_code == 0

    def test_parsed_from_camel_case(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        status = DeviceStatus(**{**device_status_dict, "minorCode": 101})
        assert status.minor_code == 101
        assert status.model_dump()["minor_code"] == 101
