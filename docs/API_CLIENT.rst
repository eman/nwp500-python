
REST API Client Module
======================

The ``nwp500.api_client`` module provides a high-level client for interacting with the Navien Smart Control REST API.

Overview
--------

The API client implements all endpoints from the OpenAPI specification and automatically handles:

* Authentication and token management
* Automatic token refresh
* Request formatting with correct headers
* Response parsing with data models
* Error handling and retry logic

Usage Examples
--------------

Basic Usage
^^^^^^^^^^^

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient

    async with NavienAuthClient("user@example.com", "password") as auth_client:
        
        # Create API client
        api_client = NavienAPIClient(auth_client=auth_client)
        
        # List devices
        devices = await api_client.list_devices()
        
        for device in devices:
            print(f"{device.device_info.device_name}: {device.device_info.mac_address}")

Get First Device
^^^^^^^^^^^^^^^^

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient

    async with NavienAuthClient("user@example.com", "password") as auth_client:
        api_client = NavienAPIClient(auth_client=auth_client)
        
        # Get first device
        device = await api_client.get_first_device()
        if device:
            print(f"Found: {device.device_info.device_name}")

API Reference
-------------

NavienAPIClient
^^^^^^^^^^^^^^^

Main API client class.

**Constructor**

.. code-block:: python

    NavienAPIClient(
        auth_client: NavienAuthClient,
        base_url: str = "https://nlus.naviensmartcontrol.com/api/v2.1",
        session: Optional[aiohttp.ClientSession] = None
    )

**Parameters:**
    * ``auth_client``: Authenticated NavienAuthClient instance (required)
    * ``base_url``: Base URL for the API (default: official Navien API)
    * ``session``: Optional aiohttp session (uses auth_client's session if not provided)

**Methods:**

``list_devices(offset: int = 0, count: int = 20) -> List[Device]``
    List all devices associated with the user.
    
    Args:
        * ``offset``: Pagination offset (default: 0)
        * ``count``: Number of devices to return (default: 20, max: 20)
    
    Returns:
        List of Device objects
    
    Raises:
        * ``APIError``: If API request fails
        * ``AuthenticationError``: If not authenticated

``get_device_info(mac_address: str, additional_value: str = "") -> Device``
    Get detailed information about a specific device.
    
    Args:
        * ``mac_address``: Device MAC address
        * ``additional_value``: Additional device identifier (optional)
    
    Returns:
        Device object with detailed information
    
    Raises:
        * ``APIError``: If API request fails

``get_firmware_info(mac_address: str, additional_value: str = "") -> List[FirmwareInfo]``
    Get firmware information for a specific device.
    
    Args:
        * ``mac_address``: Device MAC address
        * ``additional_value``: Additional device identifier (optional)
    
    Returns:
        List of FirmwareInfo objects
    
    Raises:
        * ``APIError``: If API request fails

``get_tou_info(mac_address: str, additional_value: str, controller_id: str, user_type: str = "O") -> TOUInfo``
    Get Time of Use (TOU) information for a device.
    
    Args:
        * ``mac_address``: Device MAC address
        * ``additional_value``: Additional device identifier
        * ``controller_id``: Controller ID
        * ``user_type``: User type (default: "O")
    
    Returns:
        TOUInfo object
    
    Raises:
        * ``APIError``: If API request fails

``update_push_token(push_token: str, ...) -> bool``
    Update push notification token.
    
    Args:
        * ``push_token``: Push notification token
        * ``model_name``: Device model name (optional)
        * ``app_version``: Application version (optional)
        * ``os``: Operating system (optional)
        * ``os_version``: OS version (optional)
    
    Returns:
        True if successful

``get_first_device() -> Optional[Device]``
    Get the first device associated with the user.
    
    Returns:
        First Device object or None if no devices

**Properties:**

``is_authenticated: bool``
    Check if client is authenticated (via auth_client).

Data Models
-----------

Device
^^^^^^

Complete device information including location.

.. code-block:: python

    @dataclass
    class Device:
        device_info: DeviceInfo
        location: Location

DeviceInfo
^^^^^^^^^^

Device information from API.

.. code-block:: python

    @dataclass
    class DeviceInfo:
        home_seq: int
        mac_address: str
        additional_value: str
        device_type: int
        device_name: str
        connected: int
        install_type: Optional[str] = None

**Fields:**
    * ``home_seq``: Home sequence number
    * ``mac_address``: Device MAC address (e.g., "aabbccddeeff")
    * ``additional_value``: Additional device identifier (e.g., "5322")
    * ``device_type``: Device type code (52 for NWP500)
    * ``device_name``: Device name (e.g., "NWP500")
    * ``connected``: Connection status (2 = connected)
    * ``install_type``: Installation type (e.g., "R" for residential)

Location
^^^^^^^^

Location information for a device.

.. code-block:: python

    @dataclass
    class Location:
        state: Optional[str] = None
        city: Optional[str] = None
        address: Optional[str] = None
        latitude: Optional[float] = None
        longitude: Optional[float] = None
        altitude: Optional[float] = None

FirmwareInfo
^^^^^^^^^^^^

Firmware information for a device.

.. code-block:: python

    @dataclass
    class FirmwareInfo:
        mac_address: str
        additional_value: str
        device_type: int
        cur_sw_code: int
        cur_version: int
        downloaded_version: Optional[int] = None
        device_group: Optional[str] = None

TOUInfo
^^^^^^^

Time of Use (TOU) information.

.. code-block:: python

    @dataclass
    class TOUInfo:
        register_path: str
        source_type: str
        controller_id: str
        manufacture_id: str
        name: str
        utility: str
        zip_code: int
        schedule: List[TOUSchedule]

Exceptions
----------

APIError
^^^^^^^^

Raised when API returns an error response.

.. code-block:: python

    class APIError(Exception):
        message: str
        code: Optional[int]
        response: Optional[Dict]

**Attributes:**
    * ``message``: Error message
    * ``code``: HTTP status code or API error code
    * ``response``: Raw API response dictionary

Usage Examples
--------------

Example 1: List All Devices
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import asyncio
    from nwp500 import NavienAuthClient, NavienAPIClient

    async def list_my_devices():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            
            api_client = NavienAPIClient(auth_client=auth_client)
            devices = await api_client.list_devices()
            
            for device in devices:
                info = device.device_info
                loc = device.location
                
                print(f"Device: {info.device_name}")
                print(f"  MAC: {info.mac_address}")
                print(f"  Type: {info.device_type}")
                print(f"  Location: {loc.city}, {loc.state}")

    asyncio.run(list_my_devices())

Example 2: Get Device Details
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    async def get_device_details():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            
            api_client = NavienAPIClient(auth_client=auth_client)
            
            # Get first device
            device = await api_client.get_first_device()
            
            if device:
                mac = device.device_info.mac_address
                additional = device.device_info.additional_value
                
                # Get detailed info
                details = await api_client.get_device_info(mac, additional)
                
                print(f"Device: {details.device_info.device_name}")
                print(f"Install Type: {details.device_info.install_type}")
                print(f"Coordinates: {details.location.latitude}, "
                      f"{details.location.longitude}")

Example 3: Get Firmware Info
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    async def check_firmware():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            
            api_client = NavienAPIClient(auth_client=auth_client)
            device = await api_client.get_first_device()
            
            if device:
                mac = device.device_info.mac_address
                additional = device.device_info.additional_value
                
                firmwares = await api_client.get_firmware_info(mac, additional)
                
                for fw in firmwares:
                    print(f"SW Code: {fw.cur_sw_code}")
                    print(f"Version: {fw.cur_version}")

Example 4: Error Handling
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient, APIError
    from nwp500.auth import AuthenticationError

    async def safe_api_call():
        try:
            async with NavienAuthClient("user@example.com", "password") as auth_client:
                
                api_client = NavienAPIClient(auth_client=auth_client)
                devices = await api_client.list_devices()
                
                for device in devices:
                    print(device.device_info.device_name)
                    
        except AuthenticationError as e:
            print(f"Authentication failed: {e.message}")
        except APIError as e:
            print(f"API error: {e.message} (code: {e.code})")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")

Example 5: Pagination
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    async def paginate_devices():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            
            api_client = NavienAPIClient(auth_client=auth_client)
            
            offset = 0
            count = 10
            all_devices = []
            
            while True:
                devices = await api_client.list_devices(offset=offset, count=count)
                
                if not devices:
                    break
                
                all_devices.extend(devices)
                offset += count
                
                if len(devices) < count:
                    break
            
            print(f"Total devices: {len(all_devices)}")

Integration with Authentication
-------------------------------

The API client requires an authenticated NavienAuthClient:

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient

    # Create auth client and authenticate
    async with NavienAuthClient("user@example.com", "password") as auth_client:
        
        # Pass auth client to API client
        api_client = NavienAPIClient(auth_client=auth_client)
        devices = await api_client.list_devices()

Session Management
------------------

The API client uses the auth client's session by default:

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient

    async def efficient_requests():
        # Auth client manages the session
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            
            # API client reuses auth client's session
            api_client = NavienAPIClient(auth_client=auth_client)
            
            # Make multiple requests with same session
            devices = await api_client.list_devices()
            
            for device in devices:
                mac = device.device_info.mac_address
                additional = device.device_info.additional_value
                
                # Reuses same session
                info = await api_client.get_device_info(mac, additional)
                firmware = await api_client.get_firmware_info(mac, additional)

Response Format
---------------

All API responses follow this structure:

.. code-block:: json

    {
      "code": 200,
      "msg": "SUCCESS",
      "data": {}
    }

Error responses:

.. code-block:: json

    {
      "code": 601,
      "msg": "DEVICE_NOT_FOUND",
      "data": null
    }

Common error codes:

* ``200``: Success
* ``401``: Unauthorized (authentication failed)
* ``601``: Device not found
* ``602``: Invalid parameters

Testing
-------

Run the API client test:

.. code-block:: bash

    # Set credentials
    export NAVIEN_EMAIL='your_email@example.com'
    export NAVIEN_PASSWORD='your_password'

    # Run test
    python test_api_client.py

    # Test convenience function
    python test_api_client.py --convenience

Best Practices
--------------

1. **Always use context manager for auth client** - Ensures proper cleanup

   .. code-block:: python

       async with NavienAuthClient("user@example.com", "password") as auth_client:
           api_client = NavienAPIClient(auth_client=auth_client)
           # Your code here

2. **Handle errors appropriately**

   .. code-block:: python

       try:
           devices = await api_client.list_devices()
       except APIError as e:
           logger.error(f"API error: {e.message}")

3. **Share auth client between API and MQTT clients**

   .. code-block:: python

       async with NavienAuthClient("user@example.com", "password") as auth_client:
           api_client = NavienAPIClient(auth_client=auth_client)
           mqtt_client = NavienMqttClient(auth_client)

4. **Check authentication status**

   .. code-block:: python

       if auth_client.is_authenticated:
           api_client = NavienAPIClient(auth_client=auth_client)

5. **Use convenience functions for simple tasks**

   .. code-block:: python

       devices = await get_devices(email, password)

Limitations
-----------

* Maximum 20 devices per request (use pagination for more)
* Rate limiting may apply (implement exponential backoff)
* Some endpoints require device-specific configuration (e.g., TOU)

Further Reading
---------------

* :doc:`AUTHENTICATION` - Authentication details
* `OpenAPI Specification <openapi.yaml>`__ - Complete API specification

For questions or issues, please refer to the project repository.
