"""The recorded history's line format, and the recorder that writes it."""

import io
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from nwp500 import status_history
from nwp500.models import DeviceStatus

AT = datetime(2026, 10, 18, 14, 30, tzinfo=UTC)


class TestTheLines:
    def test_a_line_reads_back_as_the_status(self, device_status_dict):
        text = status_history.line(AT, device_status_dict)
        ((at, status),) = status_history.read([text])
        assert at == AT
        assert status == DeviceStatus.model_validate(device_status_dict)

    def test_a_line_is_one_line_of_json(self, device_status_dict):
        text = status_history.line(AT, device_status_dict)
        assert "\n" not in text
        assert json.loads(text) == {
            "t": "2026-10-18T14:30:00+00:00",
            "status": device_status_dict,
        }

    def test_the_offset_is_kept(self, device_status_dict):
        pdt = AT.astimezone(timezone(timedelta(hours=-7)))
        ((at, _),) = status_history.read(
            [status_history.line(pdt, device_status_dict)]
        )
        assert at == AT
        assert at.utcoffset() == timedelta(hours=-7)

    def test_a_naive_instant_is_refused(self, device_status_dict):
        with pytest.raises(ValueError, match="UTC offset"):
            status_history.line(AT.replace(tzinfo=None), device_status_dict)

    def test_blank_lines_are_skipped_and_order_kept(self, device_status_dict):
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
    def test_a_bad_line_names_its_number(self, device_status_dict, text, why):
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
    def test_it_writes_a_line_per_status(self, Recorder, device_status_dict):
        out = io.StringIO()
        record = Recorder(out, clock=lambda: AT)
        record("cmd/52/navilink-x/st", _message(device_status_dict))
        record("cmd/52/navilink-x/st", _message(device_status_dict))
        assert record.written == 2
        readings = status_history.read(out.getvalue().splitlines())
        assert [at for at, _ in readings] == [AT, AT]

    def test_it_keeps_the_raw_payload_but_not_the_address(
        self, Recorder, device_status_dict
    ):
        out = io.StringIO()
        raw = device_status_dict | {"macAddress": "aa:bb"}
        Recorder(out, clock=lambda: AT)("topic", _message(raw))
        assert json.loads(out.getvalue())["status"] == device_status_dict

    def test_other_messages_are_ignored(self, Recorder):
        out = io.StringIO()
        record = Recorder(out, clock=lambda: AT)
        record("topic", {"response": {"feature": {"volumeCode": 3}}})
        record("topic", {"response": {"status": "busy"}})
        assert record.written == 0
        assert out.getvalue() == ""

    def test_a_status_that_does_not_parse_is_skipped(self, Recorder, caplog):
        out = io.StringIO()
        record = Recorder(out, clock=lambda: AT)
        record("topic", _message({"dhwUse": 1}))
        assert record.written == 0
        assert "does not parse" in caplog.text

    def test_the_default_clock_is_utc(self, Recorder, device_status_dict):
        out = io.StringIO()
        Recorder(out)("topic", _message(device_status_dict))
        ((at, _),) = status_history.read([out.getvalue()])
        assert at.utcoffset() == timedelta(0)
