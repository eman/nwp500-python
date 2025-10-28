"""Tests for exception hierarchy and exception handling."""

import pytest

from nwp500.exceptions import (
    APIError,
    AuthenticationError,
    DeviceError,
    DeviceNotFoundError,
    DeviceOfflineError,
    DeviceOperationError,
    InvalidCredentialsError,
    MqttConnectionError,
    MqttCredentialsError,
    MqttError,
    MqttNotConnectedError,
    MqttPublishError,
    MqttSubscriptionError,
    Nwp500Error,
    ParameterValidationError,
    RangeValidationError,
    TokenExpiredError,
    TokenRefreshError,
    ValidationError,
)


class TestExceptionHierarchy:
    """Test exception inheritance relationships."""

    def test_base_exception_hierarchy(self):
        """Test that all exceptions inherit from Nwp500Error."""
        assert issubclass(AuthenticationError, Nwp500Error)
        assert issubclass(APIError, Nwp500Error)
        assert issubclass(MqttError, Nwp500Error)
        assert issubclass(ValidationError, Nwp500Error)
        assert issubclass(DeviceError, Nwp500Error)

    def test_authentication_exception_hierarchy(self):
        """Test authentication exception inheritance."""
        assert issubclass(InvalidCredentialsError, AuthenticationError)
        assert issubclass(TokenExpiredError, AuthenticationError)
        assert issubclass(TokenRefreshError, AuthenticationError)

    def test_mqtt_exception_hierarchy(self):
        """Test MQTT exception inheritance."""
        assert issubclass(MqttConnectionError, MqttError)
        assert issubclass(MqttNotConnectedError, MqttError)
        assert issubclass(MqttPublishError, MqttError)
        assert issubclass(MqttSubscriptionError, MqttError)
        assert issubclass(MqttCredentialsError, MqttError)

    def test_validation_exception_hierarchy(self):
        """Test validation exception inheritance."""
        assert issubclass(ParameterValidationError, ValidationError)
        assert issubclass(RangeValidationError, ValidationError)

    def test_device_exception_hierarchy(self):
        """Test device exception inheritance."""
        assert issubclass(DeviceNotFoundError, DeviceError)
        assert issubclass(DeviceOfflineError, DeviceError)
        assert issubclass(DeviceOperationError, DeviceError)

    def test_all_inherit_from_base_exception(self):
        """Test that all custom exceptions inherit from Exception."""
        assert issubclass(Nwp500Error, Exception)
        assert issubclass(AuthenticationError, Exception)
        assert issubclass(MqttNotConnectedError, Exception)


class TestBaseExceptionAttributes:
    """Test Nwp500Error base class attributes and methods."""

    def test_basic_error_creation(self):
        """Test creating a basic error with just a message."""
        error = Nwp500Error("Test error message")
        assert error.message == "Test error message"
        assert error.error_code is None
        assert error.details == {}
        assert error.retriable is False

    def test_error_with_code(self):
        """Test creating an error with an error code."""
        error = Nwp500Error("Test error", error_code="TEST_001")
        assert error.error_code == "TEST_001"
        assert "TEST_001" in str(error)
        assert "[TEST_001]" in str(error)

    def test_error_with_details(self):
        """Test creating an error with additional details."""
        details = {"foo": "bar", "baz": 123}
        error = Nwp500Error("Test error", details=details)
        assert error.details == details

    def test_retriable_error(self):
        """Test creating a retriable error."""
        error = Nwp500Error("Test error", retriable=True)
        assert error.retriable is True
        assert "(retriable)" in str(error)

    def test_error_to_dict(self):
        """Test serializing error to dictionary."""
        error = Nwp500Error(
            "Test error",
            error_code="TEST_001",
            details={"key": "value"},
            retriable=True,
        )
        error_dict = error.to_dict()

        assert error_dict["error_type"] == "Nwp500Error"
        assert error_dict["message"] == "Test error"
        assert error_dict["error_code"] == "TEST_001"
        assert error_dict["details"] == {"key": "value"}
        assert error_dict["retriable"] is True

    def test_error_string_representation(self):
        """Test error string formatting."""
        # Basic error
        error1 = Nwp500Error("Simple error")
        assert str(error1) == "Simple error"

        # With error code
        error2 = Nwp500Error("Error with code", error_code="ERR_123")
        assert "Error with code" in str(error2)
        assert "[ERR_123]" in str(error2)

        # Retriable
        error3 = Nwp500Error("Retriable error", retriable=True)
        assert "Retriable error" in str(error3)
        assert "(retriable)" in str(error3)

        # All together
        error4 = Nwp500Error(
            "Complex error", error_code="ERR_456", retriable=True
        )
        result = str(error4)
        assert "Complex error" in result
        assert "[ERR_456]" in result
        assert "(retriable)" in result


class TestAuthenticationExceptions:
    """Test authentication-related exceptions."""

    def test_authentication_error_attributes(self):
        """Test AuthenticationError attributes."""
        error = AuthenticationError(
            "Auth failed",
            status_code=401,
            response={"code": 401, "msg": "Unauthorized"},
        )
        assert error.message == "Auth failed"
        assert error.status_code == 401
        assert error.response == {"code": 401, "msg": "Unauthorized"}

    def test_invalid_credentials_error(self):
        """Test InvalidCredentialsError."""
        error = InvalidCredentialsError("Invalid password", status_code=401)
        assert isinstance(error, AuthenticationError)
        assert error.message == "Invalid password"
        assert error.status_code == 401

    def test_token_expired_error(self):
        """Test TokenExpiredError."""
        error = TokenExpiredError("Token has expired")
        assert isinstance(error, AuthenticationError)
        assert error.message == "Token has expired"

    def test_token_refresh_error(self):
        """Test TokenRefreshError."""
        error = TokenRefreshError("Refresh failed", status_code=400)
        assert isinstance(error, AuthenticationError)
        assert error.message == "Refresh failed"


class TestAPIExceptions:
    """Test API-related exceptions."""

    def test_api_error_attributes(self):
        """Test APIError attributes."""
        error = APIError(
            "API request failed",
            code=500,
            response={"error": "Internal Server Error"},
        )
        assert error.message == "API request failed"
        assert error.code == 500
        assert error.response == {"error": "Internal Server Error"}


class TestMQTTExceptions:
    """Test MQTT-related exceptions."""

    def test_mqtt_connection_error(self):
        """Test MqttConnectionError."""
        error = MqttConnectionError("Connection failed", error_code="CONN_001")
        assert isinstance(error, MqttError)
        assert error.message == "Connection failed"
        assert error.error_code == "CONN_001"

    def test_mqtt_not_connected_error(self):
        """Test MqttNotConnectedError."""
        error = MqttNotConnectedError("Not connected to broker")
        assert isinstance(error, MqttError)
        assert "Not connected" in error.message

    def test_mqtt_publish_error(self):
        """Test MqttPublishError."""
        error = MqttPublishError(
            "Publish failed", error_code="PUB_001", retriable=True
        )
        assert isinstance(error, MqttError)
        assert error.retriable is True
        assert error.error_code == "PUB_001"

    def test_mqtt_subscription_error(self):
        """Test MqttSubscriptionError."""
        error = MqttSubscriptionError("Subscribe failed")
        assert isinstance(error, MqttError)

    def test_mqtt_credentials_error(self):
        """Test MqttCredentialsError."""
        error = MqttCredentialsError("AWS credentials expired")
        assert isinstance(error, MqttError)


class TestValidationExceptions:
    """Test validation-related exceptions."""

    def test_parameter_validation_error(self):
        """Test ParameterValidationError."""
        error = ParameterValidationError(
            "Invalid parameter",
            parameter="username",
            value="",
        )
        assert isinstance(error, ValidationError)
        assert error.parameter == "username"
        assert error.value == ""

    def test_range_validation_error(self):
        """Test RangeValidationError."""
        error = RangeValidationError(
            "Value out of range",
            field="temperature",
            value=200,
            min_value=100,
            max_value=140,
        )
        assert isinstance(error, ValidationError)
        assert error.field == "temperature"
        assert error.value == 200
        assert error.min_value == 100
        assert error.max_value == 140

    def test_range_validation_error_message(self):
        """Test RangeValidationError with detailed message."""
        error = RangeValidationError(
            "Temperature must be between 100 and 140",
            field="temperature",
            value=150,
            min_value=100,
            max_value=140,
        )
        assert "100" in error.message
        assert "140" in error.message


class TestDeviceExceptions:
    """Test device-related exceptions."""

    def test_device_not_found_error(self):
        """Test DeviceNotFoundError."""
        error = DeviceNotFoundError("Device ABC123 not found")
        assert isinstance(error, DeviceError)

    def test_device_offline_error(self):
        """Test DeviceOfflineError."""
        error = DeviceOfflineError("Device is offline")
        assert isinstance(error, DeviceError)

    def test_device_operation_error(self):
        """Test DeviceOperationError."""
        error = DeviceOperationError("Failed to change mode")
        assert isinstance(error, DeviceError)


class TestExceptionChaining:
    """Test exception chaining with 'from' clause."""

    def test_exception_chain_preserved(self):
        """Test that exception chains are preserved."""
        original = ValueError("Original error")

        try:
            try:
                raise original
            except ValueError as e:
                raise MqttConnectionError("Wrapped error") from e
        except MqttConnectionError as e:
            assert e.__cause__ is original
            assert isinstance(e.__cause__, ValueError)

    def test_exception_chain_with_details(self):
        """Test exception chain with additional details."""
        original = KeyError("missing_key")

        try:
            try:
                raise original
            except KeyError as e:
                raise APIError(
                    "Invalid response format",
                    code=500,
                    error_code="INVALID_JSON",
                ) from e
        except APIError as e:
            assert e.__cause__ is original
            assert e.error_code == "INVALID_JSON"


class TestExceptionUsagePatterns:
    """Test common exception usage patterns."""

    def test_catching_base_exception(self):
        """Test catching all nwp500 exceptions."""
        with pytest.raises(Nwp500Error):
            raise MqttNotConnectedError("Not connected")

    def test_catching_specific_mqtt_error(self):
        """Test catching specific MQTT error."""
        with pytest.raises(MqttNotConnectedError):
            raise MqttNotConnectedError("Not connected")

    def test_catching_mqtt_base_class(self):
        """Test catching all MQTT errors."""
        with pytest.raises(MqttError):
            raise MqttPublishError("Publish failed")

    def test_catching_validation_errors(self):
        """Test catching validation errors."""
        with pytest.raises(ValidationError):
            raise RangeValidationError(
                "Out of range",
                field="temp",
                value=200,
                min_value=0,
                max_value=100,
            )

    def test_multiple_exception_handling(self):
        """Test handling multiple exception types."""

        def operation_that_may_fail(fail_type):
            if fail_type == "connection":
                raise MqttConnectionError("Connection failed")
            elif fail_type == "credentials":
                raise MqttCredentialsError("Invalid credentials")
            elif fail_type == "validation":
                raise RangeValidationError(
                    "Invalid range",
                    field="x",
                    value=10,
                    min_value=0,
                    max_value=5,
                )

        # Test each case
        with pytest.raises(MqttConnectionError):
            operation_that_may_fail("connection")

        with pytest.raises(MqttCredentialsError):
            operation_that_may_fail("credentials")

        with pytest.raises(RangeValidationError):
            operation_that_may_fail("validation")
