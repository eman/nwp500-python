from unittest.mock import AsyncMock, MagicMock

import pytest

from nwp500.enums import CurrentOperationMode
from nwp500.events import EventEmitter
from nwp500.models import DeviceFeature, DeviceStatus
from nwp500.mqtt.state_tracker import DeviceStateTracker
from nwp500.mqtt.subscriptions import MqttSubscriptionManager
from nwp500.mqtt_events import (
    StatusReceivedEvent,
    TemperatureChangedEvent,
)


def test_models_have_mac_address():
    """Test that DeviceStatus and DeviceFeature have mac_address field."""
    # Use model_construct to avoid providing all required fields
    status = DeviceStatus.model_construct(
        command=0, mac_address="00:11:22:33:44:55"
    )
    assert status.mac_address == "00:11:22:33:44:55"

    feature = DeviceFeature.model_construct(
        controller_serial_number="ABC123", mac_address="00:11:22:33:44:55"
    )
    assert feature.mac_address == "00:11:22:33:44:55"


def test_events_have_device_mac():
    """Test that events carry device_mac."""
    status = DeviceStatus.model_construct(command=0)
    event = StatusReceivedEvent(device_mac="00:11:22:33:44:55", status=status)
    assert event.device_mac == "00:11:22:33:44:55"

    temp_event = TemperatureChangedEvent(
        device_mac="00:11:22:33:44:55",
        old_temperature=120.0,
        new_temperature=122.0,
    )
    assert temp_event.device_mac == "00:11:22:33:44:55"


@pytest.mark.asyncio
async def test_state_tracker_emits_with_mac():
    """Test that DeviceStateTracker includes mac_address in events."""
    emitter = MagicMock(spec=EventEmitter)
    emitter.emit = AsyncMock(return_value=1)
    tracker = DeviceStateTracker(emitter)

    mac1 = "00:11:22:33:44:55"
    mac2 = "AA:BB:CC:DD:EE:FF"

    # We need to provide enough fields for computed properties if they are used
    # DeviceStatus uses dhwTemperature computed property
    # which uses dhw_temperature_raw
    status1_v1 = DeviceStatus.model_construct(
        dhw_temperature_raw=100,
        operation_mode=CurrentOperationMode.STANDBY,
        current_inst_power=0.0,
        error_code=0,
    )
    status1_v2 = DeviceStatus.model_construct(
        dhw_temperature_raw=104,
        operation_mode=CurrentOperationMode.STANDBY,
        current_inst_power=0.0,
        error_code=0,
    )

    # First update sets initial state
    await tracker.process(mac1, status1_v1)
    assert emitter.emit.call_count == 0

    # Second update triggers event
    await tracker.process(mac1, status1_v2)
    assert emitter.emit.call_count == 1

    args, kwargs = emitter.emit.call_args
    assert args[0] == "temperature_changed"
    event = args[1]
    assert isinstance(event, TemperatureChangedEvent)
    assert event.device_mac == mac1

    # Update for different device
    status2_v1 = DeviceStatus.model_construct(
        dhw_temperature_raw=110,
        operation_mode=CurrentOperationMode.STANDBY,
        current_inst_power=0.0,
        error_code=0,
    )
    status2_v2 = DeviceStatus.model_construct(
        dhw_temperature_raw=114,
        operation_mode=CurrentOperationMode.STANDBY,
        current_inst_power=0.0,
        error_code=0,
    )

    await tracker.process(mac2, status2_v1)
    await tracker.process(mac2, status2_v2)

    # Should have emitted another event for mac2
    assert emitter.emit.call_count == 2
    args, kwargs = emitter.emit.call_args
    event = args[1]
    assert event.device_mac == mac2


def test_make_handler_injects_mac():
    """Test that MqttSubscriptionManager._make_handler injects mac_address."""
    # Mock dependencies for MqttSubscriptionManager
    connection = MagicMock()
    event_emitter = MagicMock()
    schedule_coroutine = MagicMock()

    manager = MqttSubscriptionManager(
        connection=connection,
        client_id="test_client",
        event_emitter=event_emitter,
        schedule_coroutine=schedule_coroutine,
    )

    mac = "00:11:22:33:44:55"
    callback_called = []

    def my_callback(parsed):
        callback_called.append(parsed)

    handler = manager._make_handler(
        model=DeviceStatus, callback=my_callback, key="status", device_mac=mac
    )

    # Simulate receiving a message
    message = {
        "status": {
            "command": 0,
            "specialFunctionStatus": 0,
            "errorCode": 0,
            "subErrorCode": 0,
            "smartDiagnostic": 0,
            "faultStatus1": 0,
            "faultStatus2": 0,
            "wifiRssi": 0,
            "dhwChargePer": 0.0,
            "drEventStatus": 0,
            "vacationDaySetting": 0,
            "vacationDayElapsed": 0,
            "antiLegionellaPeriod": 0,
            "programReservationType": 0,
            "tempFormulaType": 0,
            "currentStatenum": 0,
            "targetFanRpm": 0,
            "currentFanRpm": 0,
            "fanPwm": 0,
            "mixingRate": 0.0,
            "eevStep": 0,
            "airFilterAlarmPeriod": 0,
            "airFilterAlarmElapsed": 0,
            "cumulatedOpTimeEvaFan": 0,
            "cumulatedDhwFlowRate": 0.0,
            "touStatus": 0,
            "drOverrideStatus": 0,
            "touOverrideStatus": 0,
            "totalEnergyCapacity": 0.0,
            "availableEnergyCapacity": 0.0,
            "recircOperationMode": 0,
            "recircPumpOperationStatus": 0,
            "recircHotBtnReady": 0,
            "recircOperationReason": 0,
            "recircErrorStatus": 0,
            "currentInstPower": 0.0,
            "didReload": 0,
            "operationBusy": 0,
            "freezeProtectionUse": 0,
            "dhwUse": 0,
            "dhwUseSustained": 0,
            "programReservationUse": 0,
            "ecoUse": 0,
            "compUse": 0,
            "eevUse": 0,
            "evaFanUse": 0,
            "shutOffValveUse": 0,
            "conOvrSensorUse": 0,
            "wtrOvrSensorUse": 0,
            "antiLegionellaUse": 0,
            "antiLegionellaOperationBusy": 0,
            "errorBuzzerUse": 0,
            "currentHeatUse": 0,
            "heatUpperUse": 0,
            "heatLowerUse": 0,
            "scaldUse": 0,
            "airFilterAlarmUse": 0,
            "recircOperationBusy": 0,
            "recircReservationUse": 0,
            "dhwTemperature": 100,
            "dhwTemperatureSetting": 100,
            "dhwTargetTemperatureSetting": 100,
            "freezeProtectionTemperature": 100,
            "dhwTemperature2": 100,
            "hpUpperOnTempSetting": 100,
            "hpUpperOffTempSetting": 100,
            "hpLowerOnTempSetting": 100,
            "hpLowerOffTempSetting": 100,
            "heUpperOnTempSetting": 100,
            "heUpperOffTempSetting": 100,
            "heLowerOnTempSetting": 100,
            "heLowerOffTempSetting": 100,
            "heatMinOpTemperature": 100,
            "recircTempSetting": 100,
            "recircTemperature": 100,
            "recircFaucetTemperature": 100,
            "currentInletTemperature": 100,
            "currentDhwFlowRate": 100,
            "hpUpperOnDiffTempSetting": 100,
            "hpUpperOffDiffTempSetting": 100,
            "hpLowerOnDiffTempSetting": 100,
            "hpLowerOffDiffTempSetting": 100,
            "heUpperOnDiffTempSetting": 100,
            "heUpperOffDiffTempSetting": 100,
            "heLowerOnTDiffempSetting": 100,
            "heLowerOffDiffTempSetting": 100,
            "recircDhwFlowRate": 100,
            "tankUpperTemperature": 100,
            "tankLowerTemperature": 100,
            "dischargeTemperature": 100,
            "suctionTemperature": 100,
            "evaporatorTemperature": 100,
            "ambientTemperature": 100,
            "targetSuperHeat": 100,
            "currentSuperHeat": 100,
            "operationMode": 0,
            "dhwOperationSetting": 3,
            "temperatureType": 2,
            "freezeProtectionTempMin": 43.0,
            "freezeProtectionTempMax": 65.0,
        }
    }

    handler("test/topic", message)

    assert len(callback_called) == 1
    parsed = callback_called[0]
    assert isinstance(parsed, DeviceStatus)
    assert parsed.mac_address == mac
