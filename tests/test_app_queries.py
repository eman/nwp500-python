"""Tests for the queries added from the NaviLink app's request builder.

Wire samples come from live captures against an NWP500
(``reference/captures/`` in the working tree, not committed).
"""

import asyncio
import concurrent.futures
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from nwp500.auth import (
    AuthenticationResponse,
    AuthTokens,
    NavienAuthClient,
    UserInfo,
)
from nwp500.models import (
    DeviceDiagnostics,
    EnergyUsageResponse,
    FirmwareDownloadInfo,
    RecirculationSchedule,
)
from nwp500.mqtt import NavienMqttClient
from nwp500.mqtt.subscriptions import MqttSubscriptionManager

TD_RD_RESPONSE: dict[str, Any] = {
    "deviceType": 52,
    "macAddress": "04786332fca0",
    "additionalValue": "5322",
    "typeOfTD": 2,
    "data": {
        "tsData": {
            "cumulatedPwrHp": 1266585,
            "cumulatedPwrHe": 146337,
            "daysSinceInstallation": 359,
            "cumulatedOccNumEco": 0,
            "cumulatedOccNumDryFire": 0,
            "numOffRostProtectBurn": 0,
            "cumulatedOccNumConOvrFlow": 3,
            "cumulatedOccNumWtrOvrFlow": 0,
            "cumulatedOpTimeDrShed": 0,
            "cumulatedOpTimeDrLoadUp": 0,
            "cumulatedOpTimeDrAdvLoadUp": 0,
            "cumulatedOpTimeDrCpp": 0,
            "cumulatedOpTimeDrGridEmg": 0,
            "cumulatedOccNumAbDisTmp": 0,
            "cumulatedOccNumHpo": 0,
            "cumulatedOccNumAbSucTmp": 0,
            "cumulatedOccNumAbDisSucTmp": 0,
        },
        "tcData": {},
        "tdData": {
            "numOfdhwUse": 0,
            "dhwUseTotalFlow": 0,
            "dhwUseTotalTime": 0,
            "numOfLongDhwUse": 0,
            "longDhwUseTotalFlow": 0,
            "longDhwUseTotalTime": 0,
            "numOfShortDhwUse": 0,
            "avrageRecoveryTime": 7,
        },
        "taData": {
            "cumulatedOpTimeComp": 3124,
            "cumulatedOpNumComp": 757,
            "cumulatedOpTimeEvaFan": 3138,
            "cumulatedOpNumEvaFan": 794,
            "cumulatedOpStepEev": 1102,
            "cumulatedOpTimeUhe": 35,
            "cumulatedOpNumUhe": 375,
            "cumulatedOpTimeLhe": 0,
            "cumulatedOpNumLhe": 20,
            "cumulatedOpNumShutOffVv": 0,
            "mixingValveOpTotalStep": 0,
            "mixingValveOpAvgMixinGrate": 5,
            "cumulatedOpNumRecircPump": 0,
            "cumulatedOpTimeRecircPump": 0,
            "cumulatedOpTimeInvComp1": 0,
            "cumulatedOpTimeInvComp2": 0,
            "cumulatedOpTimeInvComp3": 0,
            "cumulatedOpTimeInvComp4": 0,
        },
    },
}

MONTHLY_RESPONSE: dict[str, Any] = {
    "deviceType": 52,
    "macAddress": "04786332fca0",
    "additionalValue": "5322",
    "typeOfUsage": 1,
    "total": {
        "heUsage": 146337,
        "hpUsage": 1266585,
        "heTime": 35,
        "hpTime": 3124,
    },
    "usage": [
        {"year": 2025, "data": [{"heUsage": 0, "hpUsage": 0}] * 12},
        {
            "year": 2026,
            "data": [
                {
                    "heUsage": 34473,
                    "hpUsage": 163228,
                    "heTime": 9,
                    "hpTime": 412,
                }
            ]
            + [{"heUsage": 0, "hpUsage": 0}] * 11,
        },
    ],
}


class TestDiagnosticsModel:
    def test_parses_captured_response(self):
        diag = DeviceDiagnostics.from_response(TD_RD_RESPONSE)

        assert diag.type_of_td == 2
        assert diag.ts_data.cumulated_pwr_hp == 1266585
        assert diag.ts_data.cumulated_pwr_he == 146337
        assert diag.ts_data.days_since_installation == 359
        assert diag.ts_data.cumulated_occ_num_con_ovr_flow == 3
        assert diag.ts_data.num_of_frost_protect_burn == 0
        assert diag.td_data.average_recovery_time == 7
        assert diag.td_data.num_of_dhw_use == 0
        assert diag.ta_data.cumulated_op_time_comp == 3124
        assert diag.ta_data.cumulated_op_num_comp == 757
        assert diag.ta_data.cumulated_op_time_uhe == 35
        assert diag.ta_data.mixing_valve_op_avg_mixing_rate == 5
        assert diag.ta_data.cumulated_op_time_inv_comp4 == 0

    def test_every_wire_key_maps_to_a_field(self):
        """No wire key may be silently dropped by a wrong alias."""
        diag = DeviceDiagnostics.from_response(TD_RD_RESPONSE)
        dumped = diag.model_dump(by_alias=True)
        for block in ("tsData", "tdData", "taData"):
            assert dumped[block] == TD_RD_RESPONSE["data"][block], block

    def test_missing_blocks_default(self):
        diag = DeviceDiagnostics.from_response(
            {"deviceType": 52, "typeOfTD": 2, "data": {"tcData": {}}}
        )
        assert diag.ts_data.days_since_installation == 0
        assert diag.ta_data.cumulated_op_num_comp == 0


class TestFirmwareDownloadInfoModel:
    def test_parses_captured_all_zero_entry(self):
        info = FirmwareDownloadInfo.model_validate(
            {
                "deviceType": 52,
                "macAddress": "04786332fca0",
                "additionalValue": "5322",
                "downloadSwInfo": [
                    {"swCode": 0, "otaMode": 0, "swVersion": 0, "status": 0}
                ],
            }
        )
        assert len(info.download_sw_info) == 1
        entry = info.download_sw_info[0]
        assert entry.component_name == "Unknown"
        assert entry.sw_version == 0

    def test_component_name_from_sw_code(self):
        info = FirmwareDownloadInfo.model_validate(
            {"downloadSwInfo": [{"swCode": 1, "swVersion": 184614912}]}
        )
        assert info.download_sw_info[0].component_name == "Controller"


class TestEnergyModelShapes:
    def test_monthly_response(self):
        res = EnergyUsageResponse.model_validate(MONTHLY_RESPONSE)

        assert res.type_of_usage == 1
        assert res.total.heat_pump_time == 3124
        year = res.get_year_data(2026)
        assert year is not None
        assert year.month is None
        assert len(year.data) == 12
        assert year.data[0].heat_pump_usage == 163228
        assert res.get_year_data(2024) is None
        # A monthly entry is not a month entry
        assert res.get_month_data(2026, 1) is None

    def test_daily_response_still_parses(self):
        res = EnergyUsageResponse.model_validate(
            {
                "total": {"heUsage": 1, "hpUsage": 2},
                "usage": [{"year": 2025, "month": 9, "data": [{"hpUsage": 5}]}],
            }
        )
        assert res.type_of_usage is None
        month = res.get_month_data(2025, 9)
        assert month is not None
        assert month.data[0].heat_pump_usage == 5
        assert month.data[0].ep_usage == 0
        assert month.data[0].water_usage == 0


class TestRecirculationScheduleModel:
    def test_json_list_read_back(self):
        schedule = RecirculationSchedule.model_validate(
            {"reservationUse": 1, "reservation": []}
        )
        assert schedule.enabled is False
        assert schedule.reservation == []

    def test_hex_read_back(self):
        """The legacy res/recirc-rsv topic delivers a hex string."""
        schedule = RecirculationSchedule.model_validate(
            {"reservationUse": 2, "reservation": "023e06000200"}
        )
        assert schedule.enabled is True
        assert len(schedule.reservation) == 1
        entry = schedule.reservation[0]
        assert (entry.enable, entry.week, entry.hour, entry.min) == (
            2,
            62,
            6,
            0,
        )
        assert entry.pump_on is True

    def test_hex_and_json_read_backs_compare_equal(self):
        """The hex form carries param as unsigned 0xFF, JSON as -1."""
        from_hex = RecirculationSchedule.model_validate(
            {"reservationUse": 2, "reservation": "023e060002ff"}
        )
        from_json = RecirculationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {
                        "enable": 2,
                        "week": 62,
                        "hour": 6,
                        "min": 0,
                        "mode": 2,
                        "param": -1,
                    }
                ],
            }
        )
        assert from_hex.reservation[0].param == -1
        assert from_hex.canonical() == from_json.canonical()

    def test_canonical_is_order_independent(self):
        a = RecirculationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {"enable": 2, "week": 62, "hour": 6, "min": 0},
                    {"enable": 2, "week": 62, "hour": 18, "min": 0},
                ],
            }
        )
        b = RecirculationSchedule.model_validate(
            {
                "reservationUse": 2,
                "reservation": [
                    {"enable": 2, "week": 62, "hour": 18, "min": 0},
                    {"enable": 2, "week": 62, "hour": 6, "min": 0},
                ],
            }
        )
        assert a.canonical() == b.canonical()


def _device(mac: str = "04786332fca0", home_seq: int = 25004) -> MagicMock:
    device = MagicMock()
    device.device_info.mac_address = mac
    device.device_info.device_type = 52
    device.device_info.additional_value = "5322"
    device.device_info.home_seq = home_seq
    return device


def _manager() -> MqttSubscriptionManager:
    """Manager over a fake connection whose subscribe acks immediately."""
    connection = MagicMock()

    def fake_subscribe(topic: str, qos: Any, callback: Any) -> Any:
        future: concurrent.futures.Future[dict[str, Any]] = (
            concurrent.futures.Future()
        )
        future.set_result({"topic": topic, "qos": qos})
        return future, 1

    connection.subscribe.side_effect = fake_subscribe
    connection.unsubscribe.side_effect = lambda topic: (
        _resolved({"topic": topic}),
        2,
    )
    return MqttSubscriptionManager(
        connection=connection,
        client_id="test-client",
        event_emitter=MagicMock(),
        schedule_coroutine=MagicMock(),
    )


def _resolved(value: Any) -> concurrent.futures.Future[Any]:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    future.set_result(value)
    return future


async def _deliver(
    manager: MqttSubscriptionManager, topic: str, message: dict[str, Any]
) -> None:
    """Push a JSON message through the manager's dispatch path."""
    await manager._dispatch_message(  # pyright: ignore[reportPrivateUsage]
        topic, json.dumps(message).encode()
    )


class TestTypedSubscriptions:
    @pytest.mark.asyncio
    async def test_diagnostics_subscribes_app_form_topic(self):
        manager = _manager()
        received = []

        await manager.subscribe_diagnostics(_device(), received.append)

        topic = "cmd/52/25004/0/test-client/res/td/rd"
        assert topic in manager.subscriptions
        await _deliver(manager, topic, {"response": TD_RD_RESPONSE})
        assert len(received) == 1
        assert received[0].ta_data.cumulated_op_num_comp == 757

        await manager.unsubscribe_diagnostics(_device(), received.append)
        assert topic not in manager.subscriptions

    @pytest.mark.asyncio
    async def test_firmware_info_rides_the_device_wildcard(self):
        """No extra broker subscription; only /res/dl-sw-info fires."""
        manager = _manager()
        received = []

        await manager.subscribe_firmware_download_info(
            _device(), received.append
        )

        assert list(manager.subscriptions) == ["cmd/52/navilink-04786332fca0/#"]
        await _deliver(
            manager,
            "cmd/52/navilink-04786332fca0/res/did",
            {"response": {"feature": {}}},
        )
        assert received == []
        await _deliver(
            manager,
            "cmd/52/navilink-04786332fca0/res/dl-sw-info",
            {
                "response": {
                    "deviceType": 52,
                    "downloadSwInfo": [{"swCode": 1, "swVersion": 3}],
                }
            },
        )
        assert len(received) == 1
        assert received[0].download_sw_info[0].component_name == "Controller"

    @pytest.mark.asyncio
    async def test_subscribe_device_tracks_devices(self):
        manager = _manager()
        assert manager.subscribed_devices == []

        device = _device()
        await manager.subscribe_device(device, lambda t, m: None)
        await manager.subscribe_device(device, lambda t, m: None)

        assert manager.subscribed_devices == [device]
        manager.clear_subscriptions()
        assert manager.subscribed_devices == []

    @pytest.mark.asyncio
    async def test_monthly_energy_subscription_parses(self):
        manager = _manager()
        received = []

        await manager.subscribe_energy_usage_monthly(_device(), received.append)

        topic = "cmd/52/test-client/res/energy-usage-monthly-query/rd"
        assert topic in manager.subscriptions
        await _deliver(manager, topic, {"response": MONTHLY_RESPONSE})
        assert received[0].get_year_data(2026).data[0].heat_pump_usage == (
            163228
        )


class TestSubscriptionLifecycle:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_only_the_matching_kind(self):
        """Regression: one callback registered for status and firmware info
        on the same wildcard topic; unsubscribing firmware info removed the
        status handler instead."""
        manager = _manager()
        device = _device()
        received: list[Any] = []

        await manager.subscribe_device_status(device, received.append)
        await manager.subscribe_firmware_download_info(device, received.append)
        await manager.unsubscribe_firmware_download_info(
            device, received.append
        )

        wildcard = "cmd/52/navilink-04786332fca0/#"
        kinds = [
            getattr(h, "_subscription_kind", None)
            for h in manager._message_handlers[wildcard]
        ]
        assert kinds == ["device_status"]
        await _deliver(
            manager,
            "cmd/52/navilink-04786332fca0/res/dl-sw-info",
            {"response": {"downloadSwInfo": [{"swCode": 1}]}},
        )
        assert received == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("subscribe", "unsubscribe", "topic"),
        [
            (
                "subscribe_energy_usage_monthly",
                "unsubscribe_energy_usage_monthly",
                "cmd/52/test-client/res/energy-usage-monthly-query/rd",
            ),
            (
                "subscribe_energy_usage_hourly",
                "unsubscribe_energy_usage_hourly",
                "cmd/52/test-client/res/energy-usage-hourly-query/rd",
            ),
            (
                "subscribe_recirculation_schedule_response",
                "unsubscribe_recirculation_schedule_response",
                "cmd/52/test-client/res/recirc-rsv/rd",
            ),
        ],
    )
    async def test_typed_subscribe_and_unsubscribe(
        self, subscribe, unsubscribe, topic
    ):
        manager = _manager()
        device = _device()

        def callback(parsed: Any) -> None:
            pass

        await getattr(manager, subscribe)(device, callback)
        assert topic in manager.subscriptions

        await getattr(manager, unsubscribe)(device, callback)
        assert topic not in manager.subscriptions

    @pytest.mark.asyncio
    async def test_firmware_unsubscribe(self):
        manager = _manager()
        device = _device()
        received: list[Any] = []

        await manager.subscribe_firmware_download_info(device, received.append)
        await manager.unsubscribe_firmware_download_info(
            device, received.append
        )

        assert manager.subscriptions == {}

    @pytest.mark.asyncio
    async def test_typed_response_subscriptions_record_the_device(self):
        """Regression: only wildcard subscriptions recorded the device, so a
        client using only energy or diagnostics subscriptions sent no
        st/end on disconnect."""
        manager = _manager()
        device = _device()

        await manager.subscribe_diagnostics(device, lambda d: None)

        assert manager.subscribed_devices == [device]


class TestYearlyEnergyReport:
    def test_each_year_totals_its_own_months(self):
        """Regression: every year's summary showed the device's lifetime
        total instead of that year's months."""
        from nwp500.cli.presentation import build_yearly_energy_report

        res = EnergyUsageResponse.model_validate(MONTHLY_RESPONSE)
        report = build_yearly_energy_report(res, 2026)

        assert report is not None
        assert report.totals.heat_pump_usage_wh == 163228
        assert report.totals.heat_element_usage_wh == 34473
        assert report.totals.total_time_hours == 421
        assert report.lifetime is not None
        assert report.lifetime.total_usage_wh == 1266585 + 146337
        assert [row.label for row in report.days][:2] == ["January", "February"]

    def test_daily_and_monthly_summaries_are_per_period(self):
        from nwp500.cli.presentation import (
            build_daily_energy_report,
            build_energy_report,
        )

        res = EnergyUsageResponse.model_validate(
            {
                "total": {"hpUsage": 1000000, "heUsage": 5000},
                "usage": [
                    {
                        "year": 2026,
                        "month": 9,
                        "data": [{"hpUsage": 10}, {"hpUsage": 5, "heUsage": 1}],
                    }
                ],
            }
        )
        daily = build_daily_energy_report(res, 2026, 9)
        summary = build_energy_report(res)

        assert daily is not None
        assert daily.totals.total_usage_wh == 16
        assert summary.totals.total_usage_wh == 16
        assert summary.lifetime is not None
        assert summary.lifetime.total_usage_wh == 1005000

    def test_lifetime_printed_once_for_several_years(self, monkeypatch):
        from nwp500.cli import output_formatters

        calls: list[str] = []
        formatter = MagicMock()
        formatter.print_yearly_energy_table.side_effect = lambda r: (
            calls.append(f"year:{r.year}")
        )
        formatter.print_lifetime_energy.side_effect = lambda t: calls.append(
            "lifetime"
        )
        monkeypatch.setattr(
            output_formatters, "get_formatter", lambda: formatter
        )

        res = EnergyUsageResponse.model_validate(MONTHLY_RESPONSE)
        output_formatters.print_yearly_energy_usage(res, [2025, 2026])

        assert calls == ["year:2025", "year:2026", "lifetime"]


class _FakeSdkConnection:
    """Stand-in for the awscrt connection behind ``MqttConnection``.

    ``publish_behaviour`` is called with the topic for each publish and
    returns a result or raises, letting a test simulate a destroyed
    connection or an interruption mid-way through ``disconnect()``.
    """

    def __init__(self, publish_behaviour: Any = None) -> None:
        self.published: list[str] = []
        self.disconnect_calls = 0
        self._publish_behaviour = publish_behaviour

    def publish(self, topic: str, payload: bytes, qos: Any) -> Any:
        self.published.append(topic)
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        try:
            if self._publish_behaviour is not None:
                self._publish_behaviour(topic)
            future.set_result({"packet_id": len(self.published)})
        except BaseException as exc:
            future.set_exception(exc)
        return future, len(self.published)

    def disconnect(self) -> concurrent.futures.Future[Any]:
        self.disconnect_calls += 1
        return _resolved({})


def _authenticated_auth() -> NavienAuthClient:
    auth = NavienAuthClient("test@example.com", "password")
    auth._auth_response = AuthenticationResponse(
        user_info=UserInfo(user_first_name="Test", user_last_name="User"),
        tokens=AuthTokens(
            id_token="id",
            access_token="access",
            refresh_token="refresh",
            authentication_expires_in=3600,
            access_key_id="key",
            secret_key="secret",
            session_token="session",
            authorization_expires_in=3600,
        ),
    )
    return auth


def _connected_client(
    sdk: _FakeSdkConnection, devices: list[Any], **config: Any
) -> NavienMqttClient:
    """A client wired to a real MqttConnection over a fake SDK connection."""
    from nwp500.mqtt.connection import MqttConnection
    from nwp500.mqtt.utils import MqttConnectionConfig

    client = NavienMqttClient(
        _authenticated_auth(),
        config=MqttConnectionConfig(client_id="test-client", **config),
    )
    manager = MqttConnection(client.config, client._auth_client)
    manager._connection = sdk
    manager._connected = True
    client._connection_manager = manager
    client._connected = True
    client._subscription_manager = MagicMock()
    client._subscription_manager.subscribed_devices = devices
    return client


class TestSessionEndOnDisconnect:
    @pytest.mark.asyncio
    async def test_sends_st_end_for_each_subscribed_device(self):
        sdk = _FakeSdkConnection()
        client = _connected_client(
            sdk, [_device("aaaaaaaaaaaa"), _device("bbbbbbbbbbbb")]
        )

        await client.disconnect()

        assert sdk.published == [
            "cmd/52/navilink-aaaaaaaaaaaa/st/end",
            "cmd/52/navilink-bbbbbbbbbbbb/st/end",
        ]
        assert sdk.disconnect_calls == 1
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_can_be_turned_off(self):
        sdk = _FakeSdkConnection()
        client = _connected_client(
            sdk, [_device()], send_session_end_on_disconnect=False
        )

        await client.disconnect()

        assert sdk.published == []
        assert sdk.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_nothing_sent_when_not_connected(self):
        sdk = _FakeSdkConnection()
        client = _connected_client(sdk, [_device()])
        client._connected = False

        await client.disconnect()

        assert sdk.published == []
        # Interrupted state still tears the SDK connection down.
        assert sdk.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_destroyed_connection_is_still_closed(self):
        """Regression: a destroyed-connection error on st/end marks the
        connection manager disconnected while the client flag stays set;
        its disconnect() then returned early and left the SDK connection
        (and its auto-reconnect) alive."""
        from awscrt.exceptions import AwsCrtError

        def destroyed(topic: str) -> None:
            raise AwsCrtError(
                0, "AWS_ERROR_MQTT_CONNECTION_DESTROYED", "destroyed"
            )

        sdk = _FakeSdkConnection(destroyed)
        client = _connected_client(sdk, [_device()])

        await client.disconnect()

        assert sdk.disconnect_calls == 1
        assert client._connection_manager._connection is None
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_interruption_midway_queues_nothing(self):
        """Regression: after an interruption flipped the client flag, the
        remaining st/end went through publish() into the offline queue
        and would have been replayed on the next connect."""
        client: NavienMqttClient

        def interrupt(topic: str) -> None:
            # What the SDK interruption callback does, on its own thread.
            client._connected = False

        sdk = _FakeSdkConnection(interrupt)
        client = _connected_client(
            sdk, [_device("aaaaaaaaaaaa"), _device("bbbbbbbbbbbb")]
        )

        await client.disconnect()

        assert sdk.published == ["cmd/52/navilink-aaaaaaaaaaaa/st/end"]
        assert client.queued_commands_count == 0
        assert sdk.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_failed_st_end_does_not_block_disconnect(self):
        def boom(topic: str) -> None:
            raise RuntimeError("broker gone")

        sdk = _FakeSdkConnection(boom)
        client = _connected_client(sdk, [_device()])

        await client.disconnect()

        assert sdk.disconnect_calls == 1
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_slow_st_end_is_bounded(self, monkeypatch):
        sdk = _FakeSdkConnection()
        client = _connected_client(sdk, [_device()])

        async def never(topic: str, payload: Any, qos: Any = None) -> int:
            await asyncio.sleep(60)
            return 0

        monkeypatch.setattr(client._connection_manager, "publish", never)
        monkeypatch.setattr("nwp500.mqtt.client._SESSION_END_TIMEOUT", 0.01)

        await client.disconnect()

        assert sdk.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_no_subscription_manager(self):
        sdk = _FakeSdkConnection()
        client = _connected_client(sdk, [])
        client._subscription_manager = None

        await client.disconnect()

        assert sdk.published == []
        assert sdk.disconnect_calls == 1
