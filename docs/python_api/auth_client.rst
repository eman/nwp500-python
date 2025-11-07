======================
Authentication Client
======================

The ``NavienAuthClient`` handles all authentication with the Navien Smart Control API,
including sign-in, token management, and automatic token refresh.

Overview
========

The authentication client:

* Signs in with email and password
* Manages JWT tokens (ID, access, refresh)
* Provides AWS credentials for MQTT
* Automatically refreshes expired tokens
* Works as async context manager

Quick Start
===========

Basic Authentication
--------------------

.. code-block:: python

   from nwp500 import NavienAuthClient
   import asyncio

   async def main():
       # Use as context manager (recommended)
       async with NavienAuthClient("email@example.com", "password") as auth:
           print(f"Authenticated as: {auth.user_email}")
           print(f"User: {auth.current_user.full_name}")
           
           # auth is ready to use with API and MQTT clients
           # Tokens are automatically refreshed

   asyncio.run(main())

Environment Variables
---------------------

.. code-block:: python

   import os
   
   # Set credentials in environment
   os.environ['NAVIEN_EMAIL'] = 'your@email.com'
   os.environ['NAVIEN_PASSWORD'] = 'your_password'
   
   # Create without parameters
   async with NavienAuthClient() as auth:
       # Credentials loaded from environment
       print(f"Logged in as: {auth.user_email}")

API Reference
=============

NavienAuthClient
----------------

.. py:class:: NavienAuthClient(email=None, password=None, base_url=API_BASE_URL, stored_tokens=None)

   JWT-based authentication client for Navien Smart Control API.

   :param email: User email (or set NAVIEN_EMAIL env var)
   :type email: str or None
   :param password: User password (or set NAVIEN_PASSWORD env var)
   :type password: str or None
   :param base_url: API base URL
   :type base_url: str
   :param stored_tokens: Previously saved tokens to restore session
   :type stored_tokens: AuthTokens or None

   **Example:**

   .. code-block:: python

      # With parameters
      auth = NavienAuthClient("email@example.com", "password")
      
      # From environment variables
      auth = NavienAuthClient()
      
      # With stored tokens (skip re-authentication)
      stored = AuthTokens.from_dict(saved_data)
      auth = NavienAuthClient(
          "email@example.com", 
          "password",
          stored_tokens=stored
      )
      
      # Always use as context manager
      async with auth:
          # Authenticated
          pass

   .. note::
      If ``stored_tokens`` are provided and still valid, the initial 
      sign-in is skipped. If tokens are expired, they're automatically
      refreshed or re-authenticated as needed.

Authentication Methods
----------------------

sign_in()
^^^^^^^^^

.. py:method:: sign_in(email=None, password=None)

   Sign in to Navien Smart Control API.

   :param email: User email (uses constructor value if None)
   :type email: str or None
   :param password: User password (uses constructor value if None)
   :type password: str or None
   :return: Authentication response with user info and tokens
   :rtype: AuthenticationResponse
   :raises InvalidCredentialsError: If email/password incorrect
   :raises AuthenticationError: If sign-in fails

   **Example:**

   .. code-block:: python

      auth = NavienAuthClient()
      
      try:
          response = await auth.sign_in("email@example.com", "password")
          print(f"Signed in as: {response.user_info.full_name}")
          print(f"Tokens expire in: {response.tokens.time_until_expiry}")
      except InvalidCredentialsError:
          print("Wrong email or password")

refresh_token()
^^^^^^^^^^^^^^^

.. py:method:: refresh_token(refresh_token)

   Refresh access token using refresh token.

   :param refresh_token: Refresh token from previous sign-in
   :type refresh_token: str
   :return: New auth tokens
   :rtype: AuthTokens
   :raises TokenRefreshError: If refresh fails

   .. note::
      This is usually called automatically by ``ensure_valid_token()``.
      You rarely need to call it manually.

   **Example:**

   .. code-block:: python

      try:
          new_tokens = await auth.refresh_token(old_refresh_token)
          print(f"Token refreshed, expires: {new_tokens.expires_at}")
      except TokenRefreshError:
          print("Refresh failed - need to sign in again")

ensure_valid_token()
^^^^^^^^^^^^^^^^^^^^

.. py:method:: ensure_valid_token()

   Ensure access token is valid, refreshing if needed.

   :return: Current valid tokens or None if not authenticated
   :rtype: AuthTokens or None

   **Example:**

   .. code-block:: python

      # This is called automatically by API/MQTT clients
      tokens = await auth.ensure_valid_token()
      if tokens:
          print(f"Valid until: {tokens.expires_at}")

Token and Session Management
-----------------------------

close()
^^^^^^^

.. py:method:: close()

   Close the HTTP session.

   .. note::
      Called automatically when using context manager.

   **Example:**

   .. code-block:: python

      auth = NavienAuthClient(email, password)
      try:
          await auth.sign_in()
          # ... operations ...
      finally:
          await auth.close()

get_auth_headers()
^^^^^^^^^^^^^^^^^^

.. py:method:: get_auth_headers()

   Get HTTP headers for authenticated requests.

   :return: Headers dictionary with Authorization bearer token
   :rtype: dict[str, str]

   **Example:**

   .. code-block:: python

      headers = auth.get_auth_headers()
      # {'Authorization': 'Bearer eyJ0eXAiOiJKV1...'}
      
      # Used internally by API client
      async with aiohttp.ClientSession() as session:
          async with session.get(url, headers=headers) as resp:
              data = await resp.json()

Properties
----------

is_authenticated
^^^^^^^^^^^^^^^^

.. py:attribute:: is_authenticated

   Check if currently authenticated.

   :type: bool

   **Example:**

   .. code-block:: python

      if auth.is_authenticated:
          print("Ready to make API calls")
      else:
          await auth.sign_in(email, password)

current_user
^^^^^^^^^^^^

.. py:attribute:: current_user

   Get current user information.

   :type: UserInfo or None

   **Example:**

   .. code-block:: python

      if auth.current_user:
          print(f"Name: {auth.current_user.full_name}")
          print(f"Type: {auth.current_user.user_type}")
          print(f"Status: {auth.current_user.user_status}")

current_tokens
^^^^^^^^^^^^^^

.. py:attribute:: current_tokens

   Get current authentication tokens.

   :type: AuthTokens or None

   **Example:**

   .. code-block:: python

      if auth.current_tokens:
          tokens = auth.current_tokens
          print(f"Expires: {tokens.expires_at}")
          print(f"Time left: {tokens.time_until_expiry}")
          
          if tokens.is_expired:
              await auth.ensure_valid_token()

user_email
^^^^^^^^^^

.. py:attribute:: user_email

   Get authenticated user's email.

   :type: str or None

   **Example:**

   .. code-block:: python

      print(f"Logged in as: {auth.user_email}")

Data Models
===========

UserInfo
--------

.. py:class:: UserInfo

   User information from authentication.

   :param user_first_name: First name
   :param user_last_name: Last name
   :param user_type: User type
   :param user_status: Account status

   **Properties:**

   * ``full_name`` - Full name (first + last)

AuthTokens
----------

.. py:class:: AuthTokens

   Authentication tokens and AWS credentials.

   :param id_token: JWT ID token
   :param access_token: JWT access token
   :param refresh_token: Refresh token
   :param authentication_expires_in: Expiry in seconds
   :param access_key_id: AWS access key (for MQTT)
   :param secret_key: AWS secret key (for MQTT)
   :param session_token: AWS session token (for MQTT)
   :param issued_at: Token issue timestamp (auto-set if not provided)

   **Properties:**

   * ``expires_at`` - Expiration timestamp
   * ``is_expired`` - Check if expired
   * ``time_until_expiry`` - Time remaining
   * ``bearer_token`` - Formatted bearer token
   * ``are_aws_credentials_expired`` - Check if AWS credentials expired

   **Methods:**

   .. py:method:: from_dict(data)
      :classmethod:

      Create AuthTokens from dictionary (API response or saved data).

      :param data: Token data dictionary
      :type data: dict[str, Any]
      :return: AuthTokens instance
      :rtype: AuthTokens

      Supports both camelCase keys (API response) and snake_case keys (saved data).

   .. py:method:: to_dict()

      Serialize tokens to dictionary for storage.

      :return: Dictionary with all token data including issued_at timestamp
      :rtype: dict[str, Any]

      **Example:**

      .. code-block:: python

         # Save tokens
         tokens = auth.current_tokens
         token_data = tokens.to_dict()
         
         # Later, restore tokens
         restored = AuthTokens.from_dict(token_data)

AuthenticationResponse
----------------------

.. py:class:: AuthenticationResponse

   Complete sign-in response.

   :param user_info: User information
   :param tokens: Authentication tokens

Examples
========

Example 1: Basic Authentication
--------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient

   async def basic_auth():
       async with NavienAuthClient("email@example.com", "password") as auth:
           print(f"Authenticated: {auth.is_authenticated}")
           print(f"User: {auth.current_user.full_name}")
           print(f"Email: {auth.user_email}")
           
           tokens = auth.current_tokens
           print(f"Token expires: {tokens.expires_at}")
           print(f"Time remaining: {tokens.time_until_expiry}")

Example 2: Environment Variables
---------------------------------

.. code-block:: python

   import os
   from nwp500 import NavienAuthClient

   os.environ['NAVIEN_EMAIL'] = 'your@email.com'
   os.environ['NAVIEN_PASSWORD'] = 'your_password'

   async def env_auth():
       async with NavienAuthClient() as auth:
           print(f"Logged in as: {auth.user_email}")

Example 3: Manual Token Management
-----------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, InvalidCredentialsError

   async def manual_auth():
       auth = NavienAuthClient()
       
       try:
           # Sign in
           response = await auth.sign_in("email@example.com", "password")
           print(f"Signed in: {response.user_info.full_name}")
           
           # Check token status
           if auth.current_tokens.is_expired:
               print("Token expired, refreshing...")
               await auth.ensure_valid_token()
           
           # Use for API calls
           headers = auth.get_auth_headers()
           
       except InvalidCredentialsError:
           print("Invalid credentials")
       finally:
           await auth.close()

Example 4: Long-Running Application
------------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient

   async def long_running():
       async with NavienAuthClient(email, password) as auth:
           while True:
               # Token is automatically refreshed
               await auth.ensure_valid_token()
               
               # Do work
               await perform_operations(auth)
               
               # Sleep
               await asyncio.sleep(3600)

Example 5: Token Restoration (Skip Re-authentication)
------------------------------------------------------

.. code-block:: python

   import json
   from nwp500 import NavienAuthClient
   from nwp500.auth import AuthTokens

   async def save_tokens():
       """Save tokens for later reuse."""
       async with NavienAuthClient(email, password) as auth:
           tokens = auth.current_tokens
           
           # Serialize tokens to dictionary
           token_data = tokens.to_dict()
           
           # Save to file (or database, cache, etc.)
           with open('tokens.json', 'w') as f:
               json.dump(token_data, f)
           
           print("Tokens saved for future use")

   async def restore_tokens():
       """Restore authentication from saved tokens."""
       # Load saved tokens
       with open('tokens.json') as f:
           token_data = json.load(f)
       
       # Deserialize tokens
       stored_tokens = AuthTokens.from_dict(token_data)
       
       # Initialize client with stored tokens
       # This skips initial authentication if tokens are still valid
       async with NavienAuthClient(
           email, password,
           stored_tokens=stored_tokens
       ) as auth:
           # If tokens were expired, they're automatically refreshed
           # If AWS credentials expired, re-authentication occurs
           print(f"Authenticated (from stored tokens): {auth.user_email}")
           
           # Always save updated tokens after refresh
           new_tokens = auth.current_tokens
           if new_tokens.issued_at != stored_tokens.issued_at:
               token_data = new_tokens.to_dict()
               with open('tokens.json', 'w') as f:
                   json.dump(token_data, f)
               print("Tokens were refreshed and re-saved")

.. note::
   Token restoration is especially useful for applications that restart
   frequently (like Home Assistant) to avoid unnecessary authentication
   requests on every restart.

Error Handling
==============

.. code-block:: python

   from nwp500 import (
       InvalidCredentialsError,
       TokenExpiredError,
       TokenRefreshError,
       AuthenticationError
   )

   async def handle_auth_errors():
       try:
           async with NavienAuthClient(email, password) as auth:
               # Operations
               pass
       
       except InvalidCredentialsError:
           print("Wrong email or password")
       
       except TokenExpiredError:
           print("Token expired and refresh failed")
       
       except TokenRefreshError:
           print("Could not refresh token - sign in again")
       
       except AuthenticationError as e:
           print(f"Auth error: {e.message}")

Best Practices
==============

1. **Always use context manager:**

   .. code-block:: python

      # [OK] Correct
      async with NavienAuthClient(email, password) as auth:
          # operations
      
      # ✗ Wrong
      auth = NavienAuthClient(email, password)
      await auth.sign_in()
      # ... forgot to call auth.close()

2. **Use environment variables for credentials:**

   .. code-block:: python

      # Don't hardcode credentials
      async with NavienAuthClient() as auth:
          # Loaded from NAVIEN_EMAIL and NAVIEN_PASSWORD
          pass

3. **Share auth client:**

   .. code-block:: python

      async with NavienAuthClient(email, password) as auth:
          # Use same auth for both clients
          api = NavienAPIClient(auth)
          mqtt = NavienMqttClient(auth)

4. **Let automatic refresh work:**

   .. code-block:: python

      # Don't manually check/refresh
      # The client does it automatically

Related Documentation
=====================

* :doc:`api_client` - REST API client
* :doc:`mqtt_client` - MQTT client
* :doc:`exceptions` - Exception handling
