"""The awscrt websocket connection: SigV4 handshake and CONNECT options."""

import concurrent.futures
from typing import Any
from unittest.mock import MagicMock, patch

import awscrt.auth
import awscrt.mqtt
import pytest

from nwp500.mqtt import connection as conn


def _signing(future_or_error: Any) -> tuple[MagicMock, MagicMock]:
    """Run the signer with aws_sign_request mocked; return (args, sign)."""
    transform_args = MagicMock()
    sign = MagicMock()
    if isinstance(future_or_error, BaseException):
        sign.side_effect = future_or_error
    else:
        sign.return_value = future_or_error
    with patch.object(awscrt.auth, "aws_sign_request", sign):
        conn._sign_websocket_handshake(
            "us-east-1",
            awscrt.auth.AwsCredentialsProvider.new_static("key", "secret"),
            transform_args,
        )
    return transform_args, sign


def test_signer_uses_iot_sigv4_query_signing() -> None:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    transform_args, sign = _signing(future)

    request, config = sign.call_args.args
    assert request is transform_args.http_request
    assert config.algorithm == awscrt.auth.AwsSigningAlgorithm.V4
    assert (
        config.signature_type
        == awscrt.auth.AwsSignatureType.HTTP_REQUEST_QUERY_PARAMS
    )
    assert config.service == "iotdevicegateway"
    assert config.region == "us-east-1"
    assert config.omit_session_token is True
    transform_args.set_done.assert_not_called()


def test_signer_completes_once_on_success() -> None:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    transform_args, _ = _signing(future)
    future.set_result(None)
    transform_args.set_done.assert_called_once_with(None)


def test_signer_completes_once_with_a_signing_failure() -> None:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    transform_args, _ = _signing(future)
    error = RuntimeError("signing failed")
    future.set_exception(error)
    transform_args.set_done.assert_called_once_with(error)


def test_signer_completes_once_when_signing_raises() -> None:
    error = ValueError("bad request")
    transform_args, _ = _signing(error)
    transform_args.set_done.assert_called_once_with(error)


@pytest.mark.parametrize("will", [None, MagicMock(spec=awscrt.mqtt.Will)])
def test_build_connection_options(will: Any) -> None:
    interrupted = MagicMock()
    resumed = MagicMock()
    provider = MagicMock()
    with (
        patch.object(conn.awscrt.mqtt, "Connection") as connection,
        patch.object(conn.awscrt.mqtt, "Client") as client,
        patch.object(conn.awscrt.io, "ClientTlsContext") as tls_context,
        patch.object(conn.awscrt.io, "is_alpn_available", return_value=True),
    ):
        built = conn._build_connection(
            endpoint="example-ats.iot.us-east-1.amazonaws.com",
            region="us-east-1",
            credentials_provider=provider,
            client_id="navien-client-1",
            clean_session=True,
            keep_alive_secs=60,
            on_connection_interrupted=interrupted,
            on_connection_resumed=resumed,
            will=will,
        )

    assert built is connection.return_value
    tls_options = tls_context.call_args.args[0]
    assert tls_options.alpn_list == ["http/1.1"]
    assert client.call_args.args[1] is tls_context.return_value

    kwargs = connection.call_args.kwargs
    assert kwargs["client"] is client.return_value
    assert kwargs["host_name"] == "example-ats.iot.us-east-1.amazonaws.com"
    assert kwargs["port"] == 443
    assert kwargs["client_id"] == "navien-client-1"
    assert kwargs["clean_session"] is True
    assert kwargs["keep_alive_secs"] == 60
    assert kwargs["use_websockets"] is True
    assert kwargs["disable_metrics"] is True
    assert kwargs["will"] is will
    assert kwargs["on_connection_interrupted"] is interrupted
    assert kwargs["on_connection_resumed"] is resumed
    assert kwargs["socket_options"].connect_timeout_ms == 5000

    # The handshake transform signs with this connection's region and
    # credentials.
    transform = kwargs["websocket_handshake_transform"]
    assert transform.args == ("us-east-1", provider)
