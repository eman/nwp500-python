==========
Exceptions
==========

**New in v5.0:** Complete exception architecture with enterprise-grade error handling.

The nwp500 library provides a comprehensive exception hierarchy for robust error handling.
All custom exceptions inherit from a base class and provide structured error information.

Exception Hierarchy
===================

All library exceptions inherit from ``Nwp500Error``::

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

Base Exception
==============

Nwp500Error
-----------

.. py:class:: Nwp500Error(message, *, error_code=None, details=None, retriable=False)

   Base exception for all nwp500 library errors.

   All custom exceptions in the library inherit from this base class, allowing
   consumers to catch all library-specific errors with a single handler.

   :param message: Human-readable error message
   :type message: str
   :param error_code: Machine-readable error code (optional)
   :type error_code: str or None
   :param details: Additional context as dictionary (optional)
   :type details: dict or None
   :param retriable: Whether the operation can be retried (optional)
   :type retriable: bool

   **Attributes:**

   * ``message`` (str) - Human-readable error message
   * ``error_code`` (str or None) - Machine-readable error code
   * ``details`` (dict) - Additional context
   * ``retriable`` (bool) - Whether operation can be retried

   **Methods:**

   * ``to_dict()`` - Serialize exception for logging/monitoring

   **Example - Catching all library errors:**

   .. code-block:: python

      from nwp500 import NavienMqttClient, Nwp500Error

      try:
          mqtt = NavienMqttClient(auth)
          await mqtt.connect()
          await mqtt.request_device_status(device)
      except Nwp500Error as e:
          # Catches all library exceptions
          print(f"Library error: {e}")
          
          # Check if retriable
          if e.retriable:
              print("This operation can be retried")
          
          # Log structured data
          logger.error("Operation failed", extra=e.to_dict())

Authentication Exceptions
=========================

AuthenticationError
-------------------

.. py:class:: AuthenticationError(message, status_code=None, response=None, **kwargs)

   Base exception for authentication-related errors.

   :param message: Error description
   :type message: str
   :param status_code: HTTP status code (optional)
   :type status_code: int or None
   :param response: Complete API response dictionary (optional)
   :type response: dict or None

   **Attributes:**

   * ``message`` (str) - Error message
   * ``status_code`` (int or None) - HTTP status code
   * ``response`` (dict or None) - Full API response

InvalidCredentialsError
-----------------------

.. py:class:: InvalidCredentialsError

   Raised when email/password combination is incorrect.

   Subclass of :py:class:`AuthenticationError`. Typically indicates a 401
   Unauthorized response from the API.

   **Example:**

   .. code-block:: python

      from nwp500 import NavienAuthClient, InvalidCredentialsError

      try:
          async with NavienAuthClient(email, password) as auth:
              pass
      except InvalidCredentialsError as e:
          print(f"Invalid credentials: {e}")
          print("Please check your email and password")
          # Prompt user to re-enter credentials

TokenExpiredError
-----------------

.. py:class:: TokenExpiredError

   Raised when an authentication token has expired.

   Subclass of :py:class:`AuthenticationError`. Tokens have a limited lifetime
   and must be refreshed periodically.

TokenRefreshError
-----------------

.. py:class:: TokenRefreshError

   Raised when token refresh operation fails.

   Subclass of :py:class:`AuthenticationError`. Occurs when refresh token is
   invalid or expired, requiring full re-authentication.

   **Example:**

   .. code-block:: python

      from nwp500 import NavienAuthClient, TokenRefreshError

      try:
          await auth.ensure_valid_token()
      except TokenRefreshError as e:
          print(f"Token refresh failed: {e}")
          print("Re-authenticating with fresh credentials")
          await auth.sign_in(email, password)

API Exceptions
==============

APIError
--------

.. py:class:: APIError(message, code=None, response=None, **kwargs)

   Raised when REST API returns an error response.

   :param message: Error description
   :type message: str
   :param code: HTTP or API error code (optional)
   :type code: int or None
   :param response: Complete API response dictionary (optional)
   :type response: dict or None

   **Common HTTP codes:**

   * 400 - Bad request (invalid parameters)
   * 401 - Unauthorized (authentication failed)
   * 404 - Not found (device or resource missing)
   * 429 - Rate limited (too many requests)
   * 500 - Server error (Navien API issue)
   * 503 - Service unavailable (API down)

   **Example:**

   .. code-block:: python

      from nwp500 import NavienAPIClient, APIError

      try:
          device = await api.get_device_info("invalid_mac")
      except APIError as e:
          print(f"API error: {e.message}")
          
          if e.code == 404:
              print("Device not found")
          elif e.code == 401:
              print("Authentication failed")
          elif e.code >= 500:
              print("Server error - try again later")

MQTT Exceptions
===============

MqttError
---------

.. py:class:: MqttError

   Base exception for MQTT operations.

   All MQTT-related errors inherit from this base class, allowing consumers
   to handle all MQTT issues with a single exception handler.

MqttConnectionError
-------------------

.. py:class:: MqttConnectionError

   Connection establishment or maintenance failed.

   Raised when the MQTT connection to AWS IoT Core cannot be established or
   when an existing connection fails. May be due to network issues, invalid
   credentials, or AWS service problems.

   **Example:**

   .. code-block:: python

      from nwp500 import NavienMqttClient, MqttConnectionError

      try:
          mqtt = NavienMqttClient(auth)
          await mqtt.connect()
      except MqttConnectionError as e:
          print(f"Connection failed: {e}")
          print("Check network connectivity and AWS credentials")

MqttNotConnectedError
---------------------

.. py:class:: MqttNotConnectedError

   Operation requires active MQTT connection.

   Raised when attempting MQTT operations (publish, subscribe, etc.) without
   an established connection. Call ``connect()`` before performing operations.

   **Example:**

   .. code-block:: python

      from nwp500 import NavienMqttClient, MqttNotConnectedError

      mqtt = NavienMqttClient(auth)
      
      try:
          await mqtt.request_device_status(device)
      except MqttNotConnectedError:
          # Not connected - establish connection first
          await mqtt.connect()
          await mqtt.request_device_status(device)

MqttPublishError
----------------

.. py:class:: MqttPublishError

   Failed to publish message to MQTT broker.

   Raised when a message cannot be published to an MQTT topic. This may occur
   during connection interruptions or when the broker rejects the message.

   Often includes ``retriable=True`` flag for intelligent retry strategies.

   **Example with retry:**

   .. code-block:: python

      from nwp500 import MqttPublishError
      import asyncio

      async def publish_with_retry(mqtt, topic, payload, max_retries=3):
          for attempt in range(max_retries):
              try:
                  await mqtt.publish(topic, payload)
                  return  # Success
              except MqttPublishError as e:
                  if e.retriable and attempt < max_retries - 1:
                      wait_time = 2 ** attempt  # Exponential backoff
                      print(f"Retry in {wait_time}s...")
                      await asyncio.sleep(wait_time)
                  else:
                      raise  # Not retriable or max retries reached

MqttSubscriptionError
---------------------

.. py:class:: MqttSubscriptionError

   Failed to subscribe to MQTT topic.

   Raised when subscription to an MQTT topic fails. This may occur if the
   connection is interrupted or if the client lacks permissions for the topic.

MqttCredentialsError
--------------------

.. py:class:: MqttCredentialsError

   AWS credentials invalid or expired.

   Raised when AWS IoT credentials are missing, invalid, or expired.
   Re-authentication may be required to obtain fresh credentials.

   **Example:**

   .. code-block:: python

      from nwp500 import NavienMqttClient, MqttCredentialsError

      try:
          mqtt = NavienMqttClient(auth)
      except MqttCredentialsError as e:
          print(f"Credentials error: {e}")
          print("Re-authenticating to get fresh AWS credentials")
          await auth.sign_in(email, password)

Validation Exceptions
=====================

ValidationError
---------------

.. py:class:: ValidationError

   Base exception for validation failures.

   Raised when input parameters or data fail validation checks.

ParameterValidationError
------------------------

.. py:class:: ParameterValidationError(message, parameter=None, value=None, **kwargs)

   Invalid parameter value provided.

   Raised when a parameter value is invalid for reasons other than being
   out of range (e.g., wrong type, invalid format).

   :param parameter: Name of the invalid parameter
   :type parameter: str or None
   :param value: The invalid value provided
   :type value: Any

RangeValidationError
--------------------

.. py:class:: RangeValidationError(message, field=None, value=None, min_value=None, max_value=None, **kwargs)

   Value outside acceptable range.

   Raised when a numeric value is outside its valid range.

   :param field: Name of the field
   :type field: str or None
   :param value: The invalid value provided
   :type value: Any
   :param min_value: Minimum acceptable value
   :type min_value: Any
   :param max_value: Maximum acceptable value
   :type max_value: Any

   **Example:**

   .. code-block:: python

      from nwp500 import NavienMqttClient, RangeValidationError

      try:
          await mqtt.set_dhw_temperature(device, 200.0)
      except RangeValidationError as e:
          print(f"Invalid {e.field}: {e.value}")
          print(f"Valid range: {e.min_value} to {e.max_value}")
          # Output: Invalid temperature_f: 200.0
          #         Valid range: 95 to 150

Device Exceptions
=================

DeviceError
-----------

.. py:class:: DeviceError

   Base exception for device operations.

   All device-related errors inherit from this base class.

DeviceNotFoundError
-------------------

.. py:class:: DeviceNotFoundError

   Requested device not found.

   Raised when a device cannot be found in the user's device list or when
   attempting to access a non-existent device.

DeviceOfflineError
------------------

.. py:class:: DeviceOfflineError

   Device is offline or unreachable.

   Raised when a device is offline and cannot respond to commands or status
   requests. The device may be powered off, disconnected from the network,
   or experiencing connectivity issues.

DeviceOperationError
--------------------

.. py:class:: DeviceOperationError

   Device operation failed.

   Raised when a device operation (mode change, temperature setting, etc.)
   fails. This may occur due to invalid commands, device restrictions, or
   device-side errors.

Error Handling Patterns
=======================

Pattern 1: Specific Exception Handling
---------------------------------------

Handle specific exception types for granular control:

.. code-block:: python

   from nwp500 import (
       NavienAuthClient,
       NavienMqttClient,
       InvalidCredentialsError,
       MqttNotConnectedError,
       RangeValidationError,
   )

   async def robust_operation():
       try:
           async with NavienAuthClient(email, password) as auth:
               mqtt = NavienMqttClient(auth)
               await mqtt.connect()
               
               await mqtt.set_dhw_temperature(device, 120.0)
               
       except InvalidCredentialsError:
           print("Invalid credentials - check email/password")
           
       except MqttNotConnectedError:
           print("MQTT not connected - device may be offline")
           
       except RangeValidationError as e:
           print(f"Invalid {e.field}: {e.value}")
           print(f"Valid range: {e.min_value} to {e.max_value}")

Pattern 2: Category-Based Handling
-----------------------------------

Catch exception categories (Auth, MQTT, Validation):

.. code-block:: python

   from nwp500 import (
       AuthenticationError,
       MqttError,
       ValidationError,
       Nwp500Error,
   )

   try:
       # Operations
       pass
       
   except AuthenticationError as e:
       print(f"Authentication failed: {e}")
       # Re-authenticate
       
   except MqttError as e:
       print(f"MQTT error: {e}")
       # Check connection
       
   except ValidationError as e:
       print(f"Invalid input: {e}")
       # Fix parameters

Pattern 3: Retry Logic with retriable Flag
-------------------------------------------

Implement intelligent retry strategies:

.. code-block:: python

   from nwp500 import MqttPublishError
   import asyncio

   async def operation_with_retry(max_retries=3):
       for attempt in range(max_retries):
           try:
               await mqtt.publish(topic, payload)
               return  # Success
               
           except MqttPublishError as e:
               if e.retriable and attempt < max_retries - 1:
                   wait_time = 2 ** attempt  # Exponential backoff
                   print(f"Attempt {attempt + 1} failed, retrying in {wait_time}s")
                   await asyncio.sleep(wait_time)
               else:
                   print(f"Operation failed: {e}")
                   raise

Pattern 4: Structured Logging
------------------------------

Use ``to_dict()`` for structured error logging:

.. code-block:: python

   import logging
   from nwp500 import Nwp500Error

   logger = logging.getLogger(__name__)

   try:
       await mqtt.request_device_status(device)
   except Nwp500Error as e:
       # Log structured error data
       logger.error("Operation failed", extra=e.to_dict())
       # Output includes: error_type, message, error_code, details, retriable

Pattern 5: Catch-All with Base Exception
-----------------------------------------

Catch all library exceptions with ``Nwp500Error``:

.. code-block:: python

   from nwp500 import Nwp500Error

   try:
       # Any library operation
       await mqtt.connect()
       await mqtt.request_device_status(device)
       
   except Nwp500Error as e:
       # All nwp500 exceptions inherit from Nwp500Error
       print(f"Library error: {e}")
       
       # Check if retriable
       if e.retriable:
           print("This operation can be retried")
       
       # Log for debugging
       logger.error("Operation failed", extra=e.to_dict())

Exception Chaining
==================

**New in v5.0:** All exception wrapping preserves the original exception chain.

When the library wraps exceptions (e.g., wrapping ``aiohttp.ClientError`` in
``AuthenticationError``), the original exception is preserved using Python's
``raise ... from`` syntax.

**Example - Inspecting exception chains:**

.. code-block:: python

   from nwp500 import AuthenticationError
   import aiohttp

   try:
       async with NavienAuthClient(email, password) as auth:
           pass
   except AuthenticationError as e:
       print(f"Authentication error: {e}")
       
       # Check for original cause
       if e.__cause__:
           print(f"Original error: {e.__cause__}")
           print(f"Original type: {type(e.__cause__).__name__}")
           
           # Was it a network error?
           if isinstance(e.__cause__, aiohttp.ClientError):
               print("Network connectivity issue")

This preserves full stack traces for debugging in production.

Best Practices
==============

1. **Catch specific exceptions first, then general:**

   .. code-block:: python

      try:
          await mqtt.connect()
      except MqttNotConnectedError:
          # Handle specific case
          pass
      except MqttError:
          # Handle general MQTT errors
          pass
      except Nwp500Error:
          # Handle any library error
          pass

2. **Use exception attributes for user-friendly messages:**

   .. code-block:: python

      try:
          await mqtt.set_dhw_temperature(device, 200.0)
      except RangeValidationError as e:
          # Show helpful message
          print(f"Temperature must be between {e.min_value}°F and {e.max_value}°F")

3. **Check retriable flag before retrying:**

   .. code-block:: python

      try:
          await mqtt.publish(topic, payload)
      except MqttPublishError as e:
          if e.retriable:
              # Safe to retry
              await asyncio.sleep(1)
              await mqtt.publish(topic, payload)
          else:
              # Don't retry
              raise

4. **Use to_dict() for monitoring/logging:**

   .. code-block:: python

      try:
          await operation()
      except Nwp500Error as e:
          # Send structured data to monitoring system
          monitoring.record_exception(e.to_dict())

5. **Always cleanup resources:**

   .. code-block:: python

      mqtt = NavienMqttClient(auth)
      try:
          await mqtt.connect()
          # Operations
      except Nwp500Error as e:
          print(f"Error: {e}")
      finally:
          await mqtt.disconnect()

Migration from v4.x
===================

If upgrading from v4.x, update your exception handling:

**Before (v4.x):**

.. code-block:: python

   try:
       await mqtt.request_device_status(device)
   except RuntimeError as e:
       if "Not connected" in str(e):
           await mqtt.connect()

**After (v5.0+):**

.. code-block:: python

   from nwp500 import MqttNotConnectedError

   try:
       await mqtt.request_device_status(device)
   except MqttNotConnectedError:
       await mqtt.connect()
       await mqtt.request_device_status(device)

See the CHANGELOG.rst for complete migration guide with more examples.

Related Documentation
=====================

* :doc:`auth_client` - Authentication client
* :doc:`api_client` - REST API client
* :doc:`mqtt_client` - MQTT client
* Complete example: ``examples/exception_handling_example.py``
