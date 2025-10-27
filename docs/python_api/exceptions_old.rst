==========
Exceptions
==========

Exception classes for error handling in the nwp500 library.

Overview
========

The library provides specific exception types for different error
scenarios:

* **Authentication errors** - Sign-in, token refresh failures
* **API errors** - REST API request failures
* **MQTT errors** - Connection and communication issues

All exceptions inherit from Python's base ``Exception`` class and
provide additional context through attributes.

Authentication Exceptions
=========================

AuthenticationError
-------------------

Base exception for all authentication-related errors.

.. py:class:: AuthenticationError(message, status_code=None, response=None)

   Base class for authentication failures.

   :param message: Error description
   :type message: str
   :param status_code: HTTP status code if available
   :type status_code: int or None
   :param response: Complete API response dictionary
   :type response: dict or None

   **Attributes:**

   * ``message`` (str) - Error message
   * ``status_code`` (int or None) - HTTP status code
   * ``response`` (dict or None) - Full API response

   **Example:**

   .. code-block:: python

      from nwp500 import AuthenticationError

      try:
          async with NavienAuthClient(email, password) as auth:
              # Operations
              pass
      except AuthenticationError as e:
          print(f"Auth failed: {e.message}")
          if e.status_code:
              print(f"Status code: {e.status_code}")
          if e.response:
              print(f"Response: {e.response}")

InvalidCredentialsError
-----------------------

Raised when email/password combination is incorrect.

.. py:class:: InvalidCredentialsError

   Subclass of :py:class:`AuthenticationError`.

   Raised during ``sign_in()`` when credentials are rejected.

   **Example:**

   .. code-block:: python

      from nwp500 import InvalidCredentialsError

      try:
          await auth.sign_in("wrong@email.com", "wrong_password")
      except InvalidCredentialsError:
          print("Invalid email or password")
          # Prompt user to re-enter credentials

TokenExpiredError
-----------------

Raised when an authentication token has expired.

.. py:class:: TokenExpiredError

   Subclass of :py:class:`AuthenticationError`.

   Usually raised when token refresh fails and re-authentication is
   required.

   **Example:**

   .. code-block:: python

      from nwp500 import TokenExpiredError

      try:
          await api.list_devices()
      except TokenExpiredError:
          print("Token expired - please sign in again")
          # Re-authenticate

TokenRefreshError
-----------------

Raised when automatic token refresh fails.

.. py:class:: TokenRefreshError

   Subclass of :py:class:`AuthenticationError`.

   Occurs when refresh token is invalid or expired, requiring new
   sign-in.

   **Example:**

   .. code-block:: python

      from nwp500 import TokenRefreshError

      try:
          await auth.ensure_valid_token()
      except TokenRefreshError:
          print("Cannot refresh token - signing in again")
          await auth.sign_in(email, password)

API Exceptions
==============

APIError
--------

Raised when REST API returns an error response.

.. py:class:: APIError(message, code=None, response=None)

   Exception for REST API failures.

   :param message: Error description
   :type message: str
   :param code: HTTP or API error code
   :type code: int or None
   :param response: Complete API response dictionary
   :type response: dict or None

   **Attributes:**

   * ``message`` (str) - Error message
   * ``code`` (int or None) - HTTP/API error code
   * ``response`` (dict or None) - Full API response

   **Common HTTP codes:**

   * 400 - Bad request (invalid parameters)
   * 401 - Unauthorized (authentication failed)
   * 404 - Not found (device or resource missing)
   * 429 - Rate limited (too many requests)
   * 500 - Server error (Navien API issue)
   * 503 - Service unavailable (API down)

   **Example:**

   .. code-block:: python

      from nwp500 import APIError

      try:
          device = await api.get_device_info("invalid_mac")
      except APIError as e:
          print(f"API error: {e.message}")
          print(f"Code: {e.code}")

          if e.code == 404:
              print("Device not found")
          elif e.code == 401:
              print("Authentication failed")
          elif e.code >= 500:
              print("Server error - try again later")

MQTT Exceptions
===============

MQTT-related errors typically manifest as Python exceptions from the
underlying ``awscrt`` and ``awsiot`` libraries.

Common MQTT Errors
------------------

**Connection Failures:**

* ``ConnectionError`` - Failed to connect to AWS IoT Core
* ``TimeoutError`` - Connection attempt timed out
* ``ssl.SSLError`` - TLS/SSL handshake failed

**Authentication Failures:**

* ``Exception`` with "unauthorized" - Invalid AWS credentials
* ``Exception`` with "forbidden" - AWS policy denies access

**Network Errors:**

* ``OSError`` - Network interface issues
* ``socket.error`` - Socket-level errors

Example MQTT Error Handling
----------------------------

.. code-block:: python

   from nwp500 import NavienMqttClient
   import asyncio

   async def safe_mqtt_connect():
       mqtt = NavienMqttClient(auth)

       try:
           await mqtt.connect()
           print("Connected successfully")

       except ConnectionError as e:
           print(f"Connection failed: {e}")
           # Check network, credentials

       except TimeoutError:
           print("Connection timed out")
           # Retry with longer timeout

       except Exception as e:
           print(f"Unexpected error: {e}")
           # Log for debugging

Error Handling Patterns
=======================

Pattern 1: Specific Exception Handling
---------------------------------------

.. code-block:: python

   from nwp500 import (
       NavienAuthClient,
       InvalidCredentialsError,
       TokenExpiredError,
       APIError
   )

   async def robust_operation():
       try:
           async with NavienAuthClient(email, password) as auth:
               api = NavienAPIClient(auth)
               devices = await api.list_devices()
               return devices

       except InvalidCredentialsError:
           print("Invalid credentials")
           # Re-prompt user

       except TokenExpiredError:
           print("Token expired")
           # Force re-authentication

       except APIError as e:
           if e.code == 429:
               print("Rate limited - waiting...")
               await asyncio.sleep(60)
               # Retry
           else:
               print(f"API error: {e.message}")

       except Exception as e:
           print(f"Unexpected error: {e}")
           # Log and notify

Pattern 2: Base Exception Handling
-----------------------------------

.. code-block:: python

   from nwp500 import AuthenticationError, APIError

   async def simple_handling():
       try:
           async with NavienAuthClient(email, password) as auth:
               api = NavienAPIClient(auth)
               return await api.list_devices()

       except AuthenticationError as e:
           # Handles all auth errors
           print(f"Authentication failed: {e.message}")
           return None

       except APIError as e:
           # Handles all API errors
           print(f"API request failed: {e.message}")
           return None

Pattern 3: Retry Logic
-----------------------

.. code-block:: python

   from nwp500 import APIError
   import asyncio

   async def retry_on_failure(max_retries=3):
       for attempt in range(max_retries):
           try:
               async with NavienAuthClient(email, password) as auth:
                   api = NavienAPIClient(auth)
                   return await api.list_devices()

           except APIError as e:
               if e.code >= 500:
                   # Server error - retry
                   print(f"Attempt {attempt + 1} failed: {e.message}")
                   if attempt < max_retries - 1:
                       await asyncio.sleep(2 ** attempt)  # Exponential backoff
                   else:
                       raise  # Give up after max retries
               else:
                   # Client error - don't retry
                   raise

Pattern 4: Graceful Degradation
--------------------------------

.. code-block:: python

   from nwp500 import APIError, AuthenticationError

   async def with_fallback():
       try:
           async with NavienAuthClient(email, password) as auth:
               api = NavienAPIClient(auth)
               devices = await api.list_devices()
               return devices

       except AuthenticationError:
           print("Cannot authenticate - using cached data")
           return load_cached_devices()

       except APIError:
           print("API unavailable - using cached data")
           return load_cached_devices()

Best Practices
==============

1. **Catch specific exceptions first:**

   .. code-block:: python

      try:
          await auth.sign_in(email, password)
      except InvalidCredentialsError:
          # Handle specifically
          pass
      except AuthenticationError:
          # Handle generally
          pass
      except Exception:
          # Handle anything else
          pass

2. **Use exception attributes:**

   .. code-block:: python

      try:
          await api.list_devices()
      except APIError as e:
          # Use error details
          log.error(f"API error: {e.message}")
          log.error(f"Code: {e.code}")
          log.debug(f"Response: {e.response}")

3. **Implement retry logic for transient errors:**

   .. code-block:: python

      async def with_retry(func, max_attempts=3):
          for i in range(max_attempts):
              try:
                  return await func()
              except APIError as e:
                  if e.code >= 500 and i < max_attempts - 1:
                      await asyncio.sleep(2 ** i)
                  else:
                      raise

4. **Always cleanup resources:**

   .. code-block:: python

      mqtt = NavienMqttClient(auth)
      try:
          await mqtt.connect()
          # Operations
      except Exception as e:
          print(f"Error: {e}")
      finally:
          await mqtt.disconnect()

5. **Log for debugging:**

   .. code-block:: python

      import logging

      try:
          await api.list_devices()
      except APIError as e:
          logging.error(f"API error: {e.message}", extra={
              'code': e.code,
              'response': e.response
          })

Related Documentation
=====================

* :doc:`auth_client` - Authentication client
* :doc:`api_client` - REST API client
* :doc:`mqtt_client` - MQTT client
