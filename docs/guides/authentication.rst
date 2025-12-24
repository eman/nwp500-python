Authentication and Session Management
=====================================

This guide explains how authentication works in nwp500-python and how to properly
manage sessions across different clients.

Quick Start
-----------

The simplest way to get started:

.. code-block:: python

    import asyncio
    from nwp500 import NavienAuthClient, NavienAPIClient

    async def main():
        # Create auth client and authenticate
        async with NavienAuthClient("email@example.com", "password") as auth:
            # Create API client using the auth session
            api = NavienAPIClient(auth_client=auth)
            
            # Use the API client
            devices = await api.list_devices()
            print(f"Found {len(devices)} devices")

    asyncio.run(main())

How It Works
------------

Authentication Flow
~~~~~~~~~~~~~~~~~~~

1. **Create the auth client**: ``NavienAuthClient(email, password)``
   - Stores credentials in memory
   - Does NOT authenticate yet

2. **Enter the context manager**: ``async with auth_client:``
   - Creates an aiohttp session
   - Authenticates with Navien API (using stored credentials)
   - Tokens are obtained and stored
   - Ready to use

3. **Create other clients**: ``NavienAPIClient(auth_client=auth)``
   - Reuses the same session from auth client
   - No need for separate authentication
   - Can create multiple clients, all sharing the same session

4. **Exit the context manager**: ``async with`` block ends
   - Session is automatically closed
   - All tokens are discarded
   - Clients can no longer be used

Session Management
~~~~~~~~~~~~~~~~~~

The auth client manages a single aiohttp session that is shared with all other
clients for efficiency.

**Session lifecycle:**

.. code-block:: python

    auth = NavienAuthClient(email, password)
    # Session doesn't exist yet!
    
    async with auth:
        # Session created here
        api = NavienAPIClient(auth_client=auth)
        mqtt = NavienMqttClient(auth_client=auth)
        
        # Both api and mqtt share the same session
        devices = await api.list_devices()
        await mqtt.connect()
        
        # Use clients...
    
    # Session is closed here!
    # api and mqtt can no longer be used


Sharing Session Between Clients
--------------------------------

All clients (API and MQTT) can share the same session by using the same
auth client:

.. code-block:: python

    async with NavienAuthClient(email, password) as auth:
        # Single auth client for all clients
        api = NavienAPIClient(auth_client=auth)
        mqtt = NavienMqttClient(auth_client=auth)
        
        # Same session is used efficiently
        devices = await api.list_devices()  # Uses shared session
        await mqtt.connect()  # Uses shared session
        
        # Devices remain current even when using different clients
        status = devices[0].status


Token Management
----------------

Automatic Token Refresh
~~~~~~~~~~~~~~~~~~~~~~~

Tokens are automatically refreshed when they expire:

.. code-block:: python

    async with NavienAuthClient(email, password) as auth:
        # Tokens obtained during __aenter__
        print(auth.current_tokens.access_token)
        
        # Tokens are automatically refreshed when making API calls
        # No manual refresh needed in most cases
        devices = await api.list_devices()


Checking Token Expiration
~~~~~~~~~~~~~~~~~~~~~~~~~~

You can check if tokens are expired:

.. code-block:: python

    async with NavienAuthClient(email, password) as auth:
        tokens = auth.current_tokens
        
        # Check JWT token expiration
        if tokens.is_expired:
            print("JWT token has expired (already refreshed by library)")
        
        # Check AWS credentials expiration
        if tokens.are_aws_credentials_expired:
            print("AWS credentials have expired")


Restoring Previous Sessions
----------------------------

If you saved tokens from a previous session, you can restore them without
requiring another login:

.. code-block:: python

    import json
    from nwp500 import NavienAuthClient, AuthTokens

    # Save tokens from a previous session
    async with NavienAuthClient(email, password) as auth:
        tokens_data = auth.current_tokens.model_dump(mode="json")
        with open("tokens.json", "w") as f:
            json.dump(tokens_data, f)

    # Later: Restore from saved tokens
    with open("tokens.json") as f:
        saved_tokens = AuthTokens.model_validate_json(f.read())

    # Authenticate using saved tokens (skips login if still valid)
    async with NavienAuthClient(email, password, stored_tokens=saved_tokens) as auth:
        api = NavienAPIClient(auth_client=auth)
        devices = await api.list_devices()


Token Storage Best Practices
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Security Considerations:**

1. **Never hardcode credentials**: Use environment variables or secure vaults
2. **Tokens have expiration**: Store with timestamp to check validity
3. **Refresh tokens are sensitive**: Protect like passwords
4. **Use HTTPS**: Always use secure connections
5. **Rotate tokens regularly**: Don't reuse the same tokens indefinitely

**Example: Secure storage with expiration check**

.. code-block:: python

    import json
    from datetime import datetime
    from nwp500 import NavienAuthClient, AuthTokens

    async def authenticate_with_cache(email: str, password: str, cache_file: str):
        """Authenticate, using cached tokens if still valid."""
        
        # Try to load cached tokens
        try:
            with open(cache_file) as f:
                data = json.load(f)
                cached_tokens = AuthTokens.model_validate(data["tokens"])
                cached_time = datetime.fromisoformat(data["cached_at"])
                
                # Use cached tokens if less than 1 hour old
                if (datetime.now() - cached_time).total_seconds() < 3600:
                    return NavienAuthClient(
                        email,
                        password,
                        stored_tokens=cached_tokens
                    )
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        
        # Create new auth (triggers fresh login)
        return NavienAuthClient(email, password)


Advanced: Custom Session
------------------------

If you need to use a custom aiohttp session:

.. code-block:: python

    import aiohttp
    from nwp500 import NavienAuthClient, NavienAPIClient

    # Create custom session with specific configuration
    connector = aiohttp.TCPConnector(limit_per_host=5)
    custom_session = aiohttp.ClientSession(connector=connector)

    try:
        # Pass custom session to auth client
        auth = NavienAuthClient(
            email,
            password,
            session=custom_session
        )
        
        async with auth:
            api = NavienAPIClient(auth_client=auth)
            devices = await api.list_devices()
    finally:
        # Session management is YOUR responsibility
        await custom_session.close()


Troubleshooting
---------------

"Session is closed" Error
~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: You get "Session is closed" when trying to use clients

**Cause**: Exited the auth context manager before using clients

**Solution**: Keep using clients inside the ``async with`` block

.. code-block:: python

    # ❌ WRONG
    async with NavienAuthClient(email, password) as auth:
        api = NavienAPIClient(auth_client=auth)
    
    # Session is closed here!
    devices = await api.list_devices()  # Error!

    # ✅ CORRECT
    async with NavienAuthClient(email, password) as auth:
        api = NavienAPIClient(auth_client=auth)
        devices = await api.list_devices()  # Works!


"Authentication Failed" Error
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Invalid credentials error during authentication

**Cause**: Wrong email or password

**Solution**: Check credentials and verify account exists

.. code-block:: python

    from nwp500 import InvalidCredentialsError
    
    try:
        async with NavienAuthClient(email, password) as auth:
            ...
    except InvalidCredentialsError:
        print("Email or password is incorrect")


Token Refresh Failures
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Tokens can't be refreshed

**Cause**: Refresh token expired or revoked

**Solution**: Perform a fresh login (don't use stored_tokens)

.. code-block:: python

    # Don't use stored tokens if refresh is failing
    auth = NavienAuthClient(email, password)  # No stored_tokens
    async with auth:
        # Fresh login will be performed
        ...
