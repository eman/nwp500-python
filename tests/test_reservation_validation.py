"""Raw reservation entries are checked before they reach the device (#148).

``update_reservations`` and ``update_reservations_confirmed`` take raw entry
dicts. They used to send them unchecked, so an unknown mode, an impossible
time or a setpoint far outside the heater's range went out as-is. Entries
are now held to the protocol's field ranges, and ``param`` to the setpoint
range the heater reports in its feature data.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.exceptions import (
    DeviceCapabilityError,
    ParameterValidationError,
    RangeValidationError,
)
from nwp500.models import DeviceFeature
from nwp500.mqtt.control import (
    MqttDeviceController,
    validate_reservation_entries,
)
from nwp500.reservations import update_reservations_confirmed

# The heater's reported setpoint range, in half-degrees Celsius:
# 81 = 40.5 degC (104.9 degF), 131 = 65.5 degC (149.9 degF).
DEVICE_MIN_RAW = 81
DEVICE_MAX_RAW = 131


def _features() -> DeviceFeature:
    return DeviceFeature.model_validate(
        {
            "temperatureType": 2,
            "countryCode": 3,
            "modelTypeCode": 513,
            "controlTypeCode": 100,
            "volumeCode": 1,
            "controllerSwVersion": 1,
            "panelSwVersion": 1,
            "wifiSwVersion": 1,
            "controllerSwCode": 1,
            "panelSwCode": 1,
            "wifiSwCode": 1,
            "recircSwVersion": 1,
            "recircModelTypeCode": 0,
            "controllerSerialNumber": "ABC123",
            "dhwTemperatureSettingUse": 2,
            "tempFormulaType": 1,
            "dhwTemperatureMin": DEVICE_MIN_RAW,
            "dhwTemperatureMax": DEVICE_MAX_RAW,
            "freezeProtectionTempMin": 12,
            "freezeProtectionTempMax": 20,
            "recircTemperatureMin": 81,
            "recircTemperatureMax": 120,
        }
    )


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "enable": 2,
        "week": 84,  # Mon, Wed, Fri
        "hour": 6,
        "min": 30,
        "mode": 3,
        "param": 120,
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def mock_device() -> MagicMock:
    device = MagicMock()
    device.device_info.mac_address = "aa:bb:cc:dd:ee:ff"
    device.device_info.device_type = 52
    device.device_info.additional_value = "additional"
    return device


def _make_controller(
    features: DeviceFeature | None,
) -> tuple[MqttDeviceController, AsyncMock, AsyncMock]:
    publish = AsyncMock(return_value=1)
    controller = MqttDeviceController(
        client_id="test-client",
        session_id="test-session",
        publish_func=publish,
    )
    get_features = AsyncMock(return_value=features)
    controller._get_device_features = get_features  # type: ignore[method-assign]
    return controller, publish, get_features


class TestValidateReservationEntries:
    def test_valid_entries_pass(self) -> None:
        validate_reservation_entries(
            [
                _entry(),
                _entry(enable=1, week=2, hour=0, min=0, mode=1),
                _entry(week=254, hour=23, min=59, mode=6),
            ],
            _features(),
        )

    def test_empty_list_passes(self) -> None:
        validate_reservation_entries([], _features())

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("enable", 0),
            ("enable", 3),
            ("enable", True),  # would be coerced to 1, i.e. disabled
            ("week", 0),  # no days
            ("week", 1),  # bit 0 is unused
            ("week", 85),
            ("week", 256),
            ("hour", 6.0),
            ("param", 120.5),
            ("mode", "3"),
        ],
    )
    def test_bad_field_raises_parameter_error(
        self, field: str, value: Any
    ) -> None:
        with pytest.raises(ParameterValidationError) as exc:
            validate_reservation_entries([_entry(**{field: value})])
        assert exc.value.parameter == f"reservation[1].{field}"

    def test_missing_field_raises_parameter_error(self) -> None:
        entry = _entry()
        del entry["param"]
        with pytest.raises(ParameterValidationError) as exc:
            validate_reservation_entries([entry])
        assert exc.value.parameter == "reservation[1].param"

    @pytest.mark.parametrize(
        ("field", "value", "low", "high"),
        [
            ("hour", -1, 0, 23),
            ("hour", 24, 0, 23),
            ("min", -1, 0, 59),
            ("min", 60, 0, 59),
            ("mode", 0, 1, 6),
            ("mode", 7, 1, 6),
            ("param", -1, 0, 255),
            ("param", 256, 0, 255),
        ],
    )
    def test_out_of_range_field_raises_range_error(
        self, field: str, value: int, low: int, high: int
    ) -> None:
        with pytest.raises(RangeValidationError) as exc:
            validate_reservation_entries([_entry(**{field: value})])
        assert exc.value.field == f"reservation[1].{field}"
        assert exc.value.value == value
        assert (exc.value.min_value, exc.value.max_value) == (low, high)

    def test_error_names_the_offending_entry(self) -> None:
        with pytest.raises(RangeValidationError) as exc:
            validate_reservation_entries([_entry(), _entry(hour=99)])
        assert exc.value.field == "reservation[2].hour"

    @pytest.mark.parametrize("param", [DEVICE_MIN_RAW, DEVICE_MAX_RAW])
    def test_param_at_device_limits_passes(self, param: int) -> None:
        validate_reservation_entries([_entry(param=param)], _features())

    @pytest.mark.parametrize(
        "param", [0, DEVICE_MIN_RAW - 1, DEVICE_MAX_RAW + 1, 200]
    )
    def test_param_outside_device_range_raises(self, param: int) -> None:
        with pytest.raises(RangeValidationError) as exc:
            validate_reservation_entries([_entry(param=param)], _features())
        assert exc.value.field == "reservation[1].param"
        assert exc.value.min_value == DEVICE_MIN_RAW
        assert exc.value.max_value == DEVICE_MAX_RAW

    def test_param_without_features_is_held_to_a_byte(self) -> None:
        # 200 (100 degC) is outside any heater's range but fits the byte;
        # without feature data only the byte range can be checked.
        validate_reservation_entries([_entry(param=200)])


class TestControllerUpdateReservations:
    @pytest.mark.asyncio
    async def test_valid_entries_are_published(
        self, mock_device: MagicMock
    ) -> None:
        controller, publish, get_features = _make_controller(_features())
        entries = [_entry(), _entry(param=DEVICE_MAX_RAW, mode=4)]

        await controller.update_reservations(mock_device, entries)

        get_features.assert_awaited_once_with(mock_device)
        publish.assert_awaited_once()
        assert publish.await_args is not None
        _, command = publish.await_args.args
        assert command["request"]["reservation"] == entries

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [
            {"mode": 7},
            {"hour": 24},
            {"min": 60},
            {"enable": True},
            {"week": 0},
        ],
    )
    async def test_bad_entry_raises_before_fetching_or_publishing(
        self, mock_device: MagicMock, overrides: dict[str, Any]
    ) -> None:
        controller, publish, get_features = _make_controller(_features())

        with pytest.raises((ParameterValidationError, RangeValidationError)):
            await controller.update_reservations(
                mock_device, [_entry(), _entry(**overrides)]
            )

        get_features.assert_not_awaited()
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("param", [DEVICE_MIN_RAW - 1, 200])
    async def test_param_outside_device_range_is_not_published(
        self, mock_device: MagicMock, param: int
    ) -> None:
        controller, publish, _ = _make_controller(_features())

        with pytest.raises(RangeValidationError) as exc:
            await controller.update_reservations(
                mock_device, [_entry(param=param)]
            )

        assert exc.value.max_value == DEVICE_MAX_RAW
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_features_raises(
        self, mock_device: MagicMock
    ) -> None:
        controller, publish, _ = _make_controller(None)

        with pytest.raises(DeviceCapabilityError):
            await controller.update_reservations(mock_device, [_entry()])

        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_schedule_needs_no_features(
        self, mock_device: MagicMock
    ) -> None:
        """Clearing the schedule has no setpoints to check."""
        controller, publish, get_features = _make_controller(None)

        await controller.update_reservations(mock_device, [], enabled=False)

        get_features.assert_not_awaited()
        publish.assert_awaited_once()


class TestConfirmedUpdate:
    @pytest.mark.asyncio
    async def test_bad_entry_raises_before_subscribing(
        self, mock_device: MagicMock
    ) -> None:
        mqtt = MagicMock()
        mqtt.subscribe_reservation_response = AsyncMock()
        mqtt.unsubscribe_reservation_response = AsyncMock()
        mqtt.update_reservations = AsyncMock()

        with pytest.raises(RangeValidationError):
            await update_reservations_confirmed(
                mqtt, mock_device, [_entry(mode=7)]
            )

        mqtt.subscribe_reservation_response.assert_not_awaited()
        mqtt.update_reservations.assert_not_awaited()
