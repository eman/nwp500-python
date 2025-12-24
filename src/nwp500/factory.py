"""Factory functions for convenient client creation and initialization.

This module provides helper functions to simplify the process of creating
and authenticating all Navien clients with a single function call.

Use factory functions when you want:
- Simplified initialization of all clients at once
- Automatic error handling during authentication
- Clear initialization order and dependencies
- Convenience over fine-grained control

Example:
    >>> auth, api, mqtt = await create_navien_clients(
    ...     email="user@example.com",
    ...     password="password"
    ... )
    >>> async with auth:
    ...     devices = await api.list_devices()
"""

from .api_client import NavienAPIClient
from .auth import NavienAuthClient
from .mqtt import NavienMqttClient

__all__ = ["create_navien_clients"]


async def create_navien_clients(
    email: str,
    password: str,
) -> tuple[NavienAuthClient, NavienAPIClient, NavienMqttClient]:
    """Create and authenticate all Navien clients with one call.

    This factory function handles the complete initialization sequence:
    1. Creates an auth client with the provided credentials
    2. Authenticates with the Navien API (via context manager)
    3. Creates API and MQTT clients using the authenticated session
    4. Returns all clients ready to use

    Args:
        email: Navien account email address
        password: Navien account password

    Returns:
        Tuple of (auth_client, api_client, mqtt_client) ready to use

    Raises:
        AuthenticationError: If authentication fails
        InvalidCredentialsError: If email/password are incorrect

    Example:
        >>> auth, api, mqtt = await create_navien_clients(
        ...     email="user@example.com",
        ...     password="password"
        ... )
        >>> async with auth:
        ...     # All clients are ready to use
        ...     devices = await api.list_devices()
        ...     await mqtt.connect()
        ...     # Use clients ...

    Note:
        You must still use the auth client as a context manager to ensure
        the session is properly cleaned up:

        >>> auth, api, mqtt = await create_navien_clients(email, password)
        >>> async with auth:
        ...     # Use api and mqtt clients here
        ...     ...
        >>> # Session is automatically closed when exiting the context
    """
    # Create auth client (doesn't authenticate yet)
    auth_client = NavienAuthClient(email, password)

    # Authenticate and enter context manager
    await auth_client.__aenter__()

    # Create API and MQTT clients that share the session
    api_client = NavienAPIClient(auth_client=auth_client)
    mqtt_client = NavienMqttClient(auth_client=auth_client)

    return auth_client, api_client, mqtt_client
