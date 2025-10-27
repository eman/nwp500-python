"""
Exception hierarchy for nwp500-python library.

This module defines all custom exceptions used throughout the library,
providing a clear hierarchy for error handling and better developer experience.

Exception Hierarchy::

    Nwp500Error (base)
    ├── AuthenticationError
    │   ├── InvalidCredentialsError
    │   ├── TokenExpiredError
    │   └── TokenRefreshError
    ├── APIError
    ├── MqttError
    │   ├── MqttConnectionError
    │   ├── MqttNotConnectedError
    │   ├── MqttPublishError
    │   ├── MqttSubscriptionError
    │   └── MqttCredentialsError
    ├── ValidationError
    │   ├── ParameterValidationError
    │   └── RangeValidationError
    └── DeviceError
        ├── DeviceNotFoundError
        ├── DeviceOfflineError
        └── DeviceOperationError

Migration from v4.x
-------------------

If you were catching generic exceptions in your code, update as follows:

.. code-block:: python

    # Old code (v4.x)
    try:
        await mqtt_client.request_device_status(device)
    except RuntimeError as e:
        if "Not connected" in str(e):
            # handle connection error

    # New code (v5.0+)
    try:
        await mqtt_client.request_device_status(device)
    except MqttNotConnectedError:
        # handle connection error
    except MqttError:
        # handle other MQTT errors

    # Old code (v4.x)
    try:
        set_vacation_mode(days=35)
    except ValueError as e:
        # handle validation error

    # New code (v5.0+)
    try:
        set_vacation_mode(days=35)
    except RangeValidationError as e:
        print(f"Invalid {e.field}: {e.message}")
        print(f"Valid range: {e.min_value} to {e.max_value}")
    except ValidationError:
        # handle other validation errors
"""

from typing import Any, Optional

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"


class Nwp500Error(Exception):
    """Base exception for all nwp500 library errors.

    All custom exceptions in the nwp500 library inherit from this base class,
    allowing consumers to catch all library-specific errors with a single
    exception handler if desired.

    Attributes:
        message: Human-readable error message
        error_code: Machine-readable error code (optional)
        details: Additional context as a dictionary (optional)
        retriable: Whether the operation can be retried (optional)
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        retriable: bool = False,
    ):
        """Initialize base exception.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            details: Additional context (dict)
            retriable: Whether operation can be retried
        """
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.retriable = retriable
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error message with optional metadata."""
        parts = [self.message]
        if self.error_code:
            parts.append(f"[{self.error_code}]")
        if self.retriable:
            parts.append("(retriable)")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize exception for logging/monitoring.

        Returns:
            Dictionary with error type, message, code, details, and retriability
        """
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
            "retriable": self.retriable,
        }


# =============================================================================
# Authentication Exceptions
# =============================================================================


class AuthenticationError(Nwp500Error):
    """Base exception for authentication errors.

    Raised when authentication-related operations fail, including sign-in,
    token management, and credential validation.

    Attributes:
        message: Error message describing the failure
        status_code: HTTP status code (optional)
        response: Complete API response dictionary (optional)
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """Initialize authentication error.

        Args:
            message: Error message describing the failure
            status_code: HTTP status code
            response: Complete API response dictionary
            **kwargs: Additional arguments passed to base class
        """
        super().__init__(message, **kwargs)
        self.status_code = status_code
        self.response = response


class InvalidCredentialsError(AuthenticationError):
    """Raised when user credentials are invalid.

    This typically indicates a 401 Unauthorized response from the API
    due to incorrect email/password combination.
    """

    pass


class TokenExpiredError(AuthenticationError):
    """Raised when an authentication token has expired.

    Tokens have a limited lifetime and must be refreshed periodically.
    This exception indicates that a token has passed its expiration time.
    """

    pass


class TokenRefreshError(AuthenticationError):
    """Raised when token refresh operation fails.

    Token refresh can fail due to invalid refresh tokens, network issues,
    or API errors. When this occurs, full re-authentication may be required.
    """

    pass


# =============================================================================
# API Exceptions
# =============================================================================


class APIError(Nwp500Error):
    """Raised when API returns an error response.

    This exception is raised for various API-related failures including
    network errors, invalid responses, and API endpoint errors.

    Attributes:
        message: Error message describing the failure
        code: HTTP or API error code
        response: Complete API response dictionary (optional)
    """

    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        response: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """Initialize API error.

        Args:
            message: Error message describing the failure
            code: HTTP or API error code
            response: Complete API response dictionary
            **kwargs: Additional arguments passed to base class
        """
        super().__init__(message, **kwargs)
        self.code = code
        self.response = response


# =============================================================================
# MQTT Exceptions
# =============================================================================


class MqttError(Nwp500Error):
    """Base exception for MQTT operations.

    All MQTT-related errors inherit from this base class, allowing consumers
    to handle all MQTT issues with a single exception handler.
    """

    pass


class MqttConnectionError(MqttError):
    """Connection establishment or maintenance failed.

    Raised when the MQTT connection to AWS IoT Core cannot be established
    or when an existing connection fails. This may be due to network issues,
    invalid credentials, or AWS service problems.
    """

    pass


class MqttNotConnectedError(MqttError):
    """Operation requires active MQTT connection.

    Raised when attempting MQTT operations (publish, subscribe, etc.) without
    an established connection. Call connect() before performing MQTT operations.

    Example::

        mqtt_client = NavienMqttClient(auth_client)
        # Must connect first
        await mqtt_client.connect()
        await mqtt_client.request_device_status(device)
    """

    pass


class MqttPublishError(MqttError):
    """Failed to publish message to MQTT broker.

    Raised when a message cannot be published to an MQTT topic. This may
    occur during connection interruptions or when the broker rejects the
    message.
    """

    pass


class MqttSubscriptionError(MqttError):
    """Failed to subscribe to MQTT topic.

    Raised when subscription to an MQTT topic fails. This may occur if the
    connection is interrupted or if the client lacks permissions for the topic.
    """

    pass


class MqttCredentialsError(MqttError):
    """AWS credentials invalid or expired.

    Raised when AWS IoT credentials are missing, invalid, or expired.
    Re-authentication may be required to obtain fresh credentials.
    """

    pass


# =============================================================================
# Validation Exceptions
# =============================================================================


class ValidationError(Nwp500Error):
    """Base exception for validation failures.

    Raised when input parameters or data fail validation checks.
    """

    pass


class ParameterValidationError(ValidationError):
    """Invalid parameter value provided.

    Raised when a parameter value is invalid for reasons other than
    being out of range (e.g., wrong type, invalid format).

    Attributes:
        parameter: Name of the invalid parameter
        value: The invalid value provided
    """

    def __init__(
        self,
        message: str,
        parameter: Optional[str] = None,
        value: Any = None,
        **kwargs: Any,
    ):
        """Initialize parameter validation error.

        Args:
            message: Error message
            parameter: Name of the invalid parameter
            value: The invalid value provided
            **kwargs: Additional arguments passed to base class
        """
        super().__init__(message, **kwargs)
        self.parameter = parameter
        self.value = value


class RangeValidationError(ValidationError):
    """Value outside acceptable range.

    Raised when a numeric value is outside its valid range.

    Attributes:
        field: Name of the field
        value: The invalid value provided
        min_value: Minimum acceptable value
        max_value: Maximum acceptable value

    Example::

        try:
            set_temperature(200)
        except RangeValidationError as e:
            print(f"Invalid {e.field}: must be {e.min_value}-{e.max_value}")
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Any = None,
        min_value: Any = None,
        max_value: Any = None,
        **kwargs: Any,
    ):
        """Initialize range validation error.

        Args:
            message: Error message
            field: Name of the field
            value: The invalid value provided
            min_value: Minimum acceptable value
            max_value: Maximum acceptable value
            **kwargs: Additional arguments passed to base class
        """
        super().__init__(message, **kwargs)
        self.field = field
        self.value = value
        self.min_value = min_value
        self.max_value = max_value


# =============================================================================
# Device Exceptions
# =============================================================================


class DeviceError(Nwp500Error):
    """Base exception for device operations.

    All device-related errors inherit from this base class.
    """

    pass


class DeviceNotFoundError(DeviceError):
    """Requested device not found.

    Raised when a device cannot be found in the user's device list or
    when attempting to access a non-existent device.
    """

    pass


class DeviceOfflineError(DeviceError):
    """Device is offline or unreachable.

    Raised when a device is offline and cannot respond to commands or
    status requests. The device may be powered off, disconnected from
    the network, or experiencing connectivity issues.
    """

    pass


class DeviceOperationError(DeviceError):
    """Device operation failed.

    Raised when a device operation (mode change, temperature setting, etc.)
    fails. This may occur due to invalid commands, device restrictions,
    or device-side errors.
    """

    pass
