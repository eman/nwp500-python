
Authentication Module
=====================

The ``nwp500.auth`` module provides comprehensive authentication functionality for the Navien Smart Control REST API.

.. important::
   **Non-Standard Authorization Header**
   
   The Navien Smart Control API uses a **non-standard authorization header format**:
   
   * Header name: **lowercase** ``authorization`` (not ``Authorization``)
   * Header value: **raw token** (no ``Bearer`` prefix)
   
   Example: ``{"authorization": "eyJraWQi..."}``
   
   This differs from standard OAuth2/JWT Bearer token authentication. Always use 
   ``client.get_auth_headers()`` to ensure correct header format.

Overview
--------

The Navien Smart Control API uses JWT (JSON Web Tokens) for authentication. The authentication flow is simplified:

1. **Initialize with Credentials**: Provide email and password to ``NavienAuthClient``
2. **Automatic Authentication**: Authentication happens when entering the async context
3. **Use Access Token**: Include access token in API requests
4. **Refresh Token**: Refresh the access token before it expires

Authentication Flow
-------------------

.. code-block::

   ┌──────────┐
   │  Client  │
   │  created │
   │  with    │
   │  creds   │
   └────┬─────┘
        │
        │ Async context enter
        │ (automatic sign-in)
        ▼
   ┌──────────────────┐
   │  Navien API      │
   │  POST /sign-in   │
   └────┬─────────────┘
        │
        │ Returns:
        │  - idToken
        │  - accessToken (expires in 3600s)
        │  - refreshToken
        │  - AWS credentials (optional)
        ▼
   ┌──────────┐
   │  Client  │
   │  Ready   │
   │  to use  │
   └────┬─────┘
        │
        │ Use accessToken in API requests
        │ authorization: <accessToken>
        │
        │ When token expires...
        │ POST /auth/refresh
        │ { refreshToken }
        ▼
   ┌──────────────────┐
   │  New Tokens      │
   └──────────────────┘

Usage Examples
--------------

Basic Authentication
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from nwp500.auth import NavienAuthClient

    # Create client with credentials - authentication happens automatically
    async with NavienAuthClient("user@example.com", "password") as client:
        # Already authenticated!
        print(f"Welcome {client.current_user.full_name}")
        print(f"Logged in as: {client.user_email}")
        
        # Get authentication headers for API requests
        # IMPORTANT: Uses lowercase 'authorization' with raw token (no 'Bearer ')
        headers = client.get_auth_headers()
        
        # Access tokens directly
        print(f"Access token expires at: {client.current_tokens.expires_at}")

Convenience Functions
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from nwp500.auth import authenticate, refresh_access_token

    # One-shot authentication
    response = await authenticate("user@example.com", "password")
    print(f"Authenticated as: {response.user_info.full_name}")
    
    # One-shot token refresh
    new_tokens = await refresh_access_token(response.tokens.refresh_token)

Automatic Token Management
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    async with NavienAuthClient("user@example.com", "password") as client:
        # Client automatically tracks token expiration
        # Refresh if needed
        valid_tokens = await client.ensure_valid_token()
        
        # Always use current valid token
        if valid_tokens:
            headers = client.get_auth_headers()

API Reference
-------------

NavienAuthClient
^^^^^^^^^^^^^^^^

Main authentication client class.

**Constructor**

.. code-block:: python

    NavienAuthClient(
        user_id: str,
        password: str,
        base_url: str = "https://nlus.naviensmartcontrol.com/api/v2.1",
        session: Optional[aiohttp.ClientSession] = None,
        timeout: int = 30
    )

**Parameters:**
    * ``user_id``: User email address (required)
    * ``password``: User password (required)
    * ``base_url``: Base URL for the API
    * ``session``: Optional aiohttp session (created automatically if not provided)
    * ``timeout``: Request timeout in seconds

**Note:**
    Authentication is performed automatically when entering the async context manager.
    You do not need to call ``sign_in()`` manually.

**Methods:**

``sign_in(user_id: str, password: str) -> AuthenticationResponse``
    Authenticate user and obtain tokens.
    
    Raises:
        * ``InvalidCredentialsError``: If credentials are invalid
        * ``AuthenticationError``: If authentication fails

``refresh_token(refresh_token: str) -> AuthTokens``
    Refresh access token using refresh token.
    
    Raises:
        * ``TokenRefreshError``: If token refresh fails

``ensure_valid_token() -> Optional[AuthTokens]``
    Ensure we have a valid access token, refreshing if necessary.
    
    Returns valid tokens or None if not authenticated.

**Properties:**

``is_authenticated: bool``
    Check if client is currently authenticated.

``current_user: Optional[UserInfo]``
    Get current authenticated user information.

``current_tokens: Optional[AuthTokens]``
    Get current authentication tokens.

``user_email: Optional[str]``
    Get the authenticated user's email address.

Data Classes
^^^^^^^^^^^^

AuthenticationResponse
~~~~~~~~~~~~~~~~~~~~~~

Complete authentication response.

.. code-block:: python

    @dataclass
    class AuthenticationResponse:
        user_info: UserInfo
        tokens: AuthTokens
        legal: List[Dict[str, Any]]
        code: int
        message: str

AuthTokens
~~~~~~~~~~

Authentication tokens and metadata.

.. code-block:: python

    @dataclass
    class AuthTokens:
        id_token: str
        access_token: str
        refresh_token: str
        authentication_expires_in: int
        access_key_id: Optional[str]
        secret_key: Optional[str]
        session_token: Optional[str]
        authorization_expires_in: Optional[int]
        issued_at: datetime

**Properties:**
    * ``expires_at: datetime`` - When the token expires
    * ``is_expired: bool`` - Whether the token has expired (with 5 min buffer)
    * ``time_until_expiry: timedelta`` - Time remaining until expiration
    * ``bearer_token: str`` - Formatted "Bearer <token>" for Authorization header

UserInfo
~~~~~~~~

User information from authentication.

.. code-block:: python

    @dataclass
    class UserInfo:
        user_type: str
        user_first_name: str
        user_last_name: str
        user_status: str
        user_seq: int

**Properties:**
    * ``full_name: str`` - User's full name

Exceptions
^^^^^^^^^^

All exceptions inherit from ``AuthenticationError``.

**AuthenticationError**
    Base exception for authentication errors.
    
    Attributes:
        * ``message: str`` - Error message
        * ``code: Optional[int]`` - HTTP status code
        * ``response: Optional[Dict]`` - Raw API response

**InvalidCredentialsError**
    Raised when credentials are invalid.

**TokenExpiredError**
    Raised when a token has expired.

**TokenRefreshError**
    Raised when token refresh fails.

Usage Examples
--------------

Example 1: Simple Authentication
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import asyncio
    from nwp500.auth import NavienAuthClient, InvalidCredentialsError, AuthenticationError

    async def main():
        try:
            async with NavienAuthClient("user@example.com", "password") as client:
                print(f"Logged in as: {client.current_user.full_name}")
                print(f"Token valid until: {client.current_tokens.expires_at}")
        except InvalidCredentialsError:
            print("Invalid email or password")
        except AuthenticationError as e:
            print(f"Authentication failed: {e.message}")

    asyncio.run(main())

Example 2: Token Refresh
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import asyncio
    from nwp500.auth import NavienAuthClient

    async def main():
        async with NavienAuthClient("user@example.com", "password") as client:
            # Check token status
            if client.current_tokens.is_expired:
                print("Token expired, refreshing...")
                new_tokens = await client.refresh_token(
                    client.current_tokens.refresh_token
                )
                print("Token refreshed successfully")
            else:
                print(f"Token valid for: {client.current_tokens.time_until_expiry}")

    asyncio.run(main())

Example 3: Long-Running Session
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import asyncio
    from nwp500.auth import NavienAuthClient

    async def make_api_request(client, endpoint):
        """Make an authenticated API request."""
        # Ensure we have a valid token
        tokens = await client.ensure_valid_token()
        if not tokens:
            raise RuntimeError("Not authenticated")
        
        headers = client.get_auth_headers()
        # Make your API request here...
        return headers

    async def main():
        async with NavienAuthClient("user@example.com", "password") as client:
            # Make multiple requests over time
            for i in range(10):
                headers = await make_api_request(client, f"/api/endpoint/{i}")
                print(f"Request {i} - authenticated")
                await asyncio.sleep(60)  # Wait 1 minute between requests

    asyncio.run(main())

Example 4: Error Handling
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import asyncio
    from nwp500.auth import (
        NavienAuthClient,
        InvalidCredentialsError,
        TokenRefreshError,
        AuthenticationError
    )

    async def safe_authenticate(email, password):
        """Authenticate with comprehensive error handling."""
        try:
            async with NavienAuthClient(email, password) as client:
                print(f"✅ Successfully authenticated as {client.current_user.full_name}")
                return client.current_tokens
                
        except InvalidCredentialsError as e:
            print(f"❌ Invalid credentials")
            print(f"   Message: {e.message}")
            print(f"   Code: {e.code}")
            return None
            
        except TokenRefreshError as e:
            print(f"❌ Token refresh failed")
            print(f"   Message: {e.message}")
            return None
            
        except AuthenticationError as e:
            print(f"❌ Authentication error")
            print(f"   Message: {e.message}")
            if e.response:
                print(f"   Response: {e.response}")
            return None
            
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
            return None

    async def main():
        tokens = await safe_authenticate("user@example.com", "password")
        if tokens:
            print(f"Token expires at: {tokens.expires_at}")

    asyncio.run(main())

Example 5: Session Reuse
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import asyncio
    import aiohttp
    from nwp500.auth import NavienAuthClient

    async def main():
        # Create a shared session for better performance
        async with aiohttp.ClientSession() as session:
            # Pass the session to the auth client
            async with NavienAuthClient(
                "user@example.com", 
                "password",
                session=session
            ) as client:
                # Use the same session for API requests
                headers = client.get_auth_headers()
                async with session.get(
                    "https://nlus.naviensmartcontrol.com/api/v2.1/device/list",
                    headers=headers,
                    json={"offset": 0, "count": 20, "userId": "user@example.com"}
                ) as resp:
                    data = await resp.json()
                    print(f"Devices: {data}")

    asyncio.run(main())

Testing
-------

A test script is provided to verify authentication:

.. code-block:: bash

    # Run interactive authentication test
    python test_auth.py

    # Test convenience functions
    python test_auth.py --convenience

The test will prompt for credentials and verify:

1. Sign-in functionality
2. Token refresh
3. Automatic token management
4. Bearer token formatting

Security Considerations
-----------------------

**Token Storage**
    * Never commit tokens to source control
    * Store tokens securely (e.g., encrypted storage, environment variables)
    * Tokens expire after 3600 seconds (1 hour) by default

**Credential Management**
    * Use environment variables for credentials
    * Never hardcode passwords in code
    * Consider using a secrets management system

**Token Refresh**
    * Tokens are automatically refreshed when within 5 minutes of expiration
    * Always use ``ensure_valid_token()`` for long-running sessions
    * Handle ``TokenRefreshError`` gracefully

**Network Security**
    * All API communication uses HTTPS
    * Bearer tokens are transmitted in Authorization header
    * Session tokens include AWS credentials for IoT communication

API Endpoints
-------------

Sign In
^^^^^^^

**Endpoint:** ``POST /user/sign-in``

**Request:**

.. code-block:: json

    {
      "userId": "user@example.com",
      "password": "password"
    }

**Response:**

.. code-block:: json

    {
      "code": 200,
      "msg": "SUCCESS",
      "data": {
        "userInfo": {
          "userType": "O",
          "userFirstName": "John",
          "userLastName": "Doe",
          "userStatus": "NORMAL",
          "userSeq": 36283
        },
        "legal": [],
        "token": {
          "idToken": "eyJraWQiOiJ...",
          "accessToken": "eyJraWQiOiJ...",
          "refreshToken": "eyJjdHkiOiJ...",
          "authenticationExpiresIn": 3600,
          "accessKeyId": "ASIA...",
          "secretKey": "...",
          "sessionToken": "IQoJb3...",
          "authorizationExpiresIn": 3600
        }
      }
    }

Refresh Token
^^^^^^^^^^^^^

**Endpoint:** ``POST /auth/refresh``

**Request:**

.. code-block:: json

    {
      "refreshToken": "eyJjdHkiOiJ..."
    }

**Response:**

.. code-block:: json

    {
      "code": 200,
      "msg": "SUCCESS",
      "data": {
        "idToken": "eyJraWQiOiJ...",
        "accessToken": "eyJraWQiOiJ...",
        "refreshToken": "eyJjdHkiOiJ...",
        "authenticationExpiresIn": 3600
      }
    }

Troubleshooting
---------------

**Invalid Credentials Error**
    * Verify email and password are correct
    * Check if account is active
    * Ensure no typos in credentials

**Token Refresh Fails**
    * Refresh token may have expired (longer lifetime than access token)
    * Re-authenticate with credentials
    * Check network connectivity

**Network Errors**
    * Verify internet connection
    * Check if API endpoint is accessible
    * Review firewall settings

**Timeout Errors**
    * Increase timeout value in NavienAuthClient constructor
    * Check network latency
    * Verify API is responding

Integration with Other Modules
------------------------------

The authentication module integrates with other components:

**Device API**
    Use authenticated tokens to access device information and control:

.. code-block:: python

    from nwp500.auth import NavienAuthClient
    from nwp500.api_client import NavienAPIClient
    
    async with NavienAuthClient("user@example.com", "password") as auth_client:
        # Use with device API
        api_client = NavienAPIClient(auth_client=auth_client)
        devices = await api_client.list_devices()
        print(f"Found {len(devices)} device(s)")

**MQTT Client**
    AWS credentials from authentication enable MQTT connection:

.. code-block:: python

    from nwp500.auth import NavienAuthClient
    from nwp500.mqtt_client import NavienMqttClient
    
    async with NavienAuthClient("user@example.com", "password") as auth_client:
        # Use AWS credentials for MQTT/IoT connection
        mqtt_client = NavienMqttClient(auth_client)
        await mqtt_client.connect()
        print(f"Connected to MQTT: {mqtt_client.client_id}")

Further Reading
---------------

* :doc:`MQTT_MESSAGES` - MQTT protocol documentation
* :doc:`DEVICE_STATUS_FIELDS` - Available device data
* :doc:`MQTT_CLIENT` - MQTT client usage guide

For questions or issues, please refer to the project repository.
