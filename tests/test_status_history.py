"""The recorded history's line format, and the recorder that writes it."""

import asyncio
import contextlib
import io
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from nwp500 import status_history
from nwp500.models import DeviceStatus

AT = datetime(2026, 10, 18, 14, 30, tzinfo=UTC)
#: A file every write to fails, as on a full disk.
DEV_FULL = Path("/dev/full")


class TestTheLines:
    def test_a_line_reads_back_as_the_status(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        text = status_history.line(AT, device_status_dict)
        ((at, status),) = status_history.read([text])
        assert at == AT
        assert status == DeviceStatus.model_validate(device_status_dict)

    def test_a_line_is_one_line_of_json(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        text = status_history.line(AT, device_status_dict)
        assert "\n" not in text
        assert json.loads(text) == {
            "t": "2026-10-18T14:30:00+00:00",
            "status": device_status_dict,
        }

    def test_the_offset_is_kept(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        pdt = AT.astimezone(timezone(timedelta(hours=-7)))
        ((at, _),) = status_history.read(
            [status_history.line(pdt, device_status_dict)]
        )
        assert at == AT
        assert at.utcoffset() == timedelta(hours=-7)

    def test_a_naive_instant_is_refused(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="UTC offset"):
            status_history.line(AT.replace(tzinfo=None), device_status_dict)

    def test_blank_lines_are_skipped_and_order_kept(
        self, device_status_dict: dict[str, Any]
    ) -> None:
        later = AT + timedelta(minutes=1)
        lines = [
            status_history.line(later, device_status_dict) + "\n",
            "\n",
            status_history.line(AT, device_status_dict) + "\n",
        ]
        assert [at for at, _ in status_history.read(lines)] == [later, AT]


class TestBadLines:
    @pytest.mark.parametrize(
        ("text", "why"),
        [
            ("not json", "Expecting value"),
            ("[1, 2]", "not a JSON object"),
            ('{"status": {}}', "no 't'"),
            ('{"t": "yesterday", "status": {}}', "isoformat"),
            ('{"t": "2026-10-18T14:30:00", "status": {}}', "no UTC offset"),
            ('{"t": "2026-10-18T14:30:00+00:00", "status": {}}', "validation"),
            ('{"t": "2026-10-18T14:30:00+00:00"}', "no 'status'"),
            ('{"t": 5, "status": {}}', "must be str"),
        ],
    )
    def test_a_bad_line_names_its_number(
        self, device_status_dict: dict[str, Any], text: str, why: str
    ) -> None:
        good = status_history.line(AT, device_status_dict)
        with pytest.raises(ValueError, match="line 2 is not") as raised:
            status_history.read([good, text])
        assert why in str(raised.value)


def _message(status: dict[str, Any]) -> dict[str, Any]:
    return {"response": {"status": status}}


@pytest.fixture
def Recorder() -> Any:
    """The recorder, which needs the CLI's extras; the format does not."""
    pytest.importorskip("click")
    from nwp500.cli.recording import Recorder

    return Recorder


class TestTheRecorder:
    def test_it_writes_a_line_per_status(
        self, Recorder: Any, device_status_dict: dict[str, Any]
    ) -> None:
        out = io.StringIO()
        record = Recorder(out, clock=lambda: AT)
        record("cmd/52/navilink-x/st", _message(device_status_dict))
        record("cmd/52/navilink-x/st", _message(device_status_dict))
        assert record.written == 2
        readings = status_history.read(out.getvalue().splitlines())
        assert [at for at, _ in readings] == [AT, AT]

    def test_it_keeps_the_raw_payload_but_not_the_address(
        self, Recorder: Any, device_status_dict: dict[str, Any]
    ) -> None:
        out = io.StringIO()
        raw = device_status_dict | {"macAddress": "aa:bb"}
        Recorder(out, clock=lambda: AT)("topic", _message(raw))
        assert json.loads(out.getvalue())["status"] == device_status_dict

    def test_other_messages_are_ignored(self, Recorder: Any) -> None:
        out = io.StringIO()
        record = Recorder(out, clock=lambda: AT)
        record("topic", {"response": {"feature": {"volumeCode": 3}}})
        record("topic", {"response": {"status": "busy"}})
        assert record.written == 0
        assert out.getvalue() == ""

    def test_a_status_that_does_not_parse_is_skipped(
        self, Recorder: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        out = io.StringIO()
        record = Recorder(out, clock=lambda: AT)
        record("topic", _message({"dhwUse": 1}))
        assert record.written == 0
        assert "does not parse" in caplog.text

    def test_the_default_clock_is_utc(
        self, Recorder: Any, device_status_dict: dict[str, Any]
    ) -> None:
        out = io.StringIO()
        Recorder(out)("topic", _message(device_status_dict))
        ((at, _),) = status_history.read([out.getvalue()])
        assert at.utcoffset() == timedelta(0)

    def test_a_failed_write_is_reported_once_and_stops_it(
        self, Recorder: Any, device_status_dict: dict[str, Any]
    ) -> None:
        class Full(io.StringIO):
            def write(self, text: str) -> int:
                raise OSError(28, "No space left on device")

        errors: list[OSError] = []
        record = Recorder(Full(), clock=lambda: AT, on_error=errors.append)
        record("topic", _message(device_status_dict))
        record("topic", _message(device_status_dict))
        assert len(errors) == 1
        assert record.failed is errors[0]
        assert record.written == 0


class FakeMqtt:
    """Answers each status request through the device subscription."""

    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status
        self.handlers: list[Any] = []

    async def subscribe_device(self, device: Any, handler: Any) -> int:
        self.handlers.append(handler)
        return 1

    async def start_periodic_requests(self, device: Any, **kw: Any) -> None:
        return None

    async def request_device_status(self, device: Any) -> int:
        loop = asyncio.get_running_loop()
        for handler in self.handlers:
            loop.call_soon(handler, "topic", _message(self.status))
        return 1


class TestHandleRecording:
    @pytest.fixture
    def recording(self) -> Any:
        pytest.importorskip("click")
        from nwp500.cli import recording

        return recording

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DEV_FULL.exists(), reason="needs /dev/full")
    async def test_a_failed_write_stops_the_recording(
        self, recording: Any, device_status_dict: dict[str, Any]
    ) -> None:
        with pytest.raises(recording.RecordingError, match="recording stopped"):
            await asyncio.wait_for(
                recording.handle_recording(
                    FakeMqtt(device_status_dict), None, "/dev/full"
                ),
                timeout=5,
            )

    @pytest.mark.asyncio
    async def test_it_appends_on_a_line_of_its_own(
        self, recording: Any, tmp_path: Path, device_status_dict: dict[str, Any]
    ) -> None:
        path = tmp_path / "h.jsonl"
        # A history written without its final newline.
        path.write_text(status_history.line(AT, device_status_dict))
        task = asyncio.create_task(
            recording.handle_recording(
                FakeMqtt(device_status_dict), None, str(path)
            )
        )
        for _ in range(100):
            await asyncio.sleep(0.01)
            if path.read_text().count("\n") >= 2:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert len(status_history.read(path.read_text().splitlines())) == 2

    def test_an_empty_or_missing_file_needs_no_separator(
        self, recording: Any, tmp_path: Path
    ) -> None:
        assert recording._ends_a_line(tmp_path / "missing.jsonl")
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert recording._ends_a_line(empty)
        empty.write_text("{}")
        assert not recording._ends_a_line(empty)
