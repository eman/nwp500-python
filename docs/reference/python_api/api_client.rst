==========
API Client
==========

The ``NavienAPIClient`` provides REST API access to Navien Smart Control for device
discovery, configuration queries, and management operations.

.. important::
   Use the API client for **device discovery and configuration**.
   Use :doc:`mqtt_client` for **real-time monitoring and control**.

Overview
========

The API client provides:

* Device discovery and listing
* Device information queries
* Firmware version checking
* Time-of-Use (TOU) schedule queries
* Push notification management

All methods are async and require an authenticated :doc:`auth_client`.

Quick Start
===========

Basic Usage
-----------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient
   import asyncio

   async def main():
       async with NavienAuthClient("email@example.com", "password") as auth:
           api = NavienAPIClient(auth)
           
           # List all devices
           devices = await api.list_devices()
           for device in devices:
               info = device.device_info
               print(f"{info.device_name}")
               print(f"  MAC: {info.mac_address}")
               print(f"  Status: {'Online' if info.connected == 2 else 'Offline'}")

   asyncio.run(main())

API Reference
=============

NavienAPIClient
---------------

.. py:class:: NavienAPIClient(auth_client, base_url=API_BASE_URL, session=None)

   REST API client for Navien Smart Control.

   :param auth_client: Authenticated NavienAuthClient instance
   :type auth_client: NavienAuthClient
   :param base_url: API base URL
   :type base_url: str
   :param session: Optional aiohttp session
   :type session: aiohttp.ClientSession or None
   :raises ValueError: If auth_client not authenticated

   **Example:**

   .. code-block:: python

      async with NavienAuthClient(email, password) as auth:
          api = NavienAPIClient(auth)
          # Ready to use

Device Methods
--------------

list_devices()
^^^^^^^^^^^^^^

.. py:method:: list_devices(offset=0, count=20)

   List all devices registered to your account.

   :param offset: Pagination offset (default: 0)
   :type offset: int
   :param count: Number of devices to return, max 20 (default: 20)
   :type count: int
   :return: List of Device objects
   :rtype: list[Device]
   :raises APIError: If request fails
   :raises AuthenticationError: If not authenticated

   **Example:**

   .. code-block:: python

      # Get all devices (up to 20)
      devices = await api.list_devices()
      
      # Pagination
      first_batch = await api.list_devices(offset=0, count=10)
      second_batch = await api.list_devices(offset=10, count=10)
      
      # Process devices
      for device in devices:
          info = device.device_info
          loc = device.location
          
          print(f"{info.device_name}")
          print(f"  MAC: {info.mac_address}")
          print(f"  Type: {info.device_type}")
          print(f"  Connected: {info.connected == 2}")
          
          if loc.city:
              print(f"  Location: {loc.city}, {loc.state}")

get_first_device()
^^^^^^^^^^^^^^^^^^

.. py:method:: get_first_device()

   Get the first device from your account (convenience method).

   :return: First device or None if no devices
   :rtype: Device or None

   **Example:**

   .. code-block:: python

      device = await api.get_first_device()
      if device:
          print(f"Using device: {device.device_info.device_name}")
      else:
          print("No devices found")

get_device_info()
^^^^^^^^^^^^^^^^^

.. py:method:: get_device_info(mac_address, additional_value="")

   Get detailed information about a specific device.

   :param mac_address: Device MAC address (without colons)
   :type mac_address: str
   :param additional_value: Additional device identifier
   :type additional_value: str
   :return: Device object with full information
   :rtype: Device
   :raises APIError: If device not found

   **Example:**

   .. code-block:: python

      # Get specific device
      device = await api.get_device_info("04786332fca0")
      
      print(f"Device: {device.device_info.device_name}")
      print(f"Model: {device.device_info.device_type}")
      print(f"Location: {device.location.city}")

Firmware Methods
----------------

get_firmware_info()
^^^^^^^^^^^^^^^^^^^

.. py:method:: get_firmware_info(mac_address=None, additional_value="")

   Get firmware version information for devices.

   :param mac_address: Specific device MAC or None for all devices
   :type mac_address: str or None
   :param additional_value: Additional device identifier
   :type additional_value: str
   :return: List of firmware information objects
   :rtype: list[FirmwareInfo]

   **Example:**

   .. code-block:: python

      # Get firmware for all devices
      firmware_list = await api.get_firmware_info()
      
      for fw in firmware_list:
          print(f"Device: {fw.mac_address}")
          print(f"  Current version: {fw.cur_version}")
          print(f"  Current code: {fw.cur_sw_code}")
          
          if fw.downloaded_version:
              print(f"  [WARNING]  Update available: {fw.downloaded_version}")
              print(f"     Download code: {fw.downloaded_sw_code}")
          else:
              print(f"  [OK] Up to date")
      
      # Get firmware for specific device
      fw_info = await api.get_firmware_info(mac_address="04786332fca0")

Time-of-Use Methods
-------------------

get_tou_info()
^^^^^^^^^^^^^^

.. py:method:: get_tou_info(mac_address, additional_value, controller_id)

   Get Time-of-Use pricing schedule for a device.

   :param mac_address: Device MAC address
   :type mac_address: str
   :param additional_value: Additional device identifier
   :type additional_value: str
   :param controller_id: Controller serial number
   :type controller_id: str
   :return: TOU information
   :rtype: TOUInfo

   **Example:**

   .. code-block:: python

      # Get controller ID from device
      device = await api.get_first_device()
      
      # Query TOU settings (need controller ID from MQTT)
      tou = await api.get_tou_info(
          mac_address=device.device_info.mac_address,
          additional_value=device.device_info.additional_value,
          controller_id="ABC123456"  # From device feature
      )
      
      print(f"Utility: {tou.utility}")
      print(f"Schedule: {tou.name}")
      print(f"ZIP: {tou.zip_code}")
      
      for schedule in tou.schedule:
          print(f"Season months: {schedule.season}")
          for interval in schedule.intervals:
              print(f"  {interval}")

Push Notification Methods
--------------------------

update_push_token()
^^^^^^^^^^^^^^^^^^^

.. py:method:: update_push_token(device_token, device_type="ios")

   Update push notification token.

   :param device_token: Firebase/APNs device token
   :type device_token: str
   :param device_type: Device type ("ios" or "android")
   :type device_type: str

   **Example:**

   .. code-block:: python

      # Register for push notifications
      await api.update_push_token(
          device_token="your_firebase_token",
          device_type="android"
      )

Properties
----------

is_authenticated
^^^^^^^^^^^^^^^^

.. py:attribute:: is_authenticated

   Check if client is authenticated.

   :type: bool

   **Example:**

   .. code-block:: python

      if api.is_authenticated:
          devices = await api.list_devices()

user_email
^^^^^^^^^^

.. py:attribute:: user_email

   Get authenticated user's email.

   :type: str or None

   **Example:**

   .. code-block:: python

      print(f"API client for: {api.user_email}")

Examples
========

Example 1: Device Discovery and Report
---------------------------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient

   async def device_report():
       async with NavienAuthClient() as auth:
           api = NavienAPIClient(auth)
           
           devices = await api.list_devices()
           print(f"Found {len(devices)} device(s)\n")
           print("DEVICE REPORT")
           print("=" * 60)
           
           for i, device in enumerate(devices, 1):
               info = device.device_info
               loc = device.location
               
               status = "🟢 Online" if info.connected == 2 else "🔴 Offline"
               
               print(f"\n{i}. {info.device_name}")
               print(f"   Status: {status}")
               print(f"   MAC: {info.mac_address}")
               print(f"   Type: {info.device_type}")
               
               if loc.city:
                   print(f"   Location: {loc.city}, {loc.state}")
                   print(f"   Coordinates: {loc.latitude}, {loc.longitude}")

   asyncio.run(device_report())

Example 2: Firmware Check
--------------------------

.. code-block:: python

   async def check_firmware():
       async with NavienAuthClient() as auth:
           api = NavienAPIClient(auth)
           
           firmware_list = await api.get_firmware_info()
           
           print("FIRMWARE STATUS")
           print("=" * 60)
           
           updates_available = 0
           
           for fw in firmware_list:
               print(f"\nDevice: {fw.mac_address}")
               print(f"  Current: {fw.cur_version} (code: {fw.cur_sw_code})")
               
               if fw.downloaded_version:
                   print(f"  [WARNING]  UPDATE AVAILABLE")
                   print(f"     Version: {fw.downloaded_version}")
                   print(f"     Code: {fw.downloaded_sw_code}")
                   updates_available += 1
               else:
                   print(f"  [OK] Up to date")
           
           if updates_available:
               print(f"\n{updates_available} device(s) have updates available")
           else:
               print("\nAll devices are up to date")

   asyncio.run(check_firmware())

Example 3: Multi-Device Management
-----------------------------------

.. code-block:: python

   async def manage_devices():
       async with NavienAuthClient() as auth:
           api = NavienAPIClient(auth)
           
           # Get all devices
           devices = await api.list_devices()
           firmware_list = await api.get_firmware_info()
           
           # Create firmware lookup
           firmware_map = {fw.mac_address: fw for fw in firmware_list}
           
           # Process each device
           for device in devices:
               info = device.device_info
               fw = firmware_map.get(info.mac_address)
               
               print(f"\n{info.device_name}")
               print(f"  MAC: {info.mac_address}")
               print(f"  Status: {'Online' if info.connected == 2 else 'Offline'}")
               
               if fw:
                   print(f"  Firmware: {fw.cur_version}")
                   if fw.downloaded_version:
                       print(f"  Update: {fw.downloaded_version} available")

   asyncio.run(manage_devices())

Example 4: Pagination for Many Devices
---------------------------------------

.. code-block:: python

   async def get_all_devices():
       async with NavienAuthClient() as auth:
           api = NavienAPIClient(auth)
           
           all_devices = []
           offset = 0
           batch_size = 20
           
           while True:
               batch = await api.list_devices(offset=offset, count=batch_size)
               
               if not batch:
                   break
               
               all_devices.extend(batch)
               print(f"Loaded {len(batch)} devices (total: {len(all_devices)})")
               
               if len(batch) < batch_size:
                   break
               
               offset += batch_size
           
           return all_devices

   asyncio.run(get_all_devices())

Error Handling
==============

.. code-block:: python

   from nwp500 import APIError, AuthenticationError

   async def safe_api_calls():
       try:
           async with NavienAuthClient() as auth:
               api = NavienAPIClient(auth)
               devices = await api.list_devices()
               return devices
       
       except AuthenticationError as e:
           print(f"Auth failed: {e.message}")
           if e.status_code == 401:
               print("Invalid credentials")
           return None
       
       except APIError as e:
           print(f"API error: {e.message}")
           print(f"Code: {e.code}")
           
           if e.code == 404:
               print("Resource not found")
           elif e.code >= 500:
               print("Server error - try again later")
           
           return None

Best Practices
==============

1. **Use API client for discovery, MQTT for monitoring:**

   .. code-block:: python

      # [OK] Correct usage
      async with NavienAuthClient() as auth:
          # API: Discover devices
          api = NavienAPIClient(auth)
          device = await api.get_first_device()
          
          # MQTT: Monitor and control
          mqtt = NavienMqttClient(auth)
          await mqtt.connect()
          await mqtt.subscribe_device_status(device, on_status)

2. **Cache device list:**

   .. code-block:: python

      # Get once
      devices = await api.list_devices()
      
      # Reuse for multiple operations
      for device in devices:
          await process_device(device)

3. **Check firmware regularly:**

   .. code-block:: python

      # Check daily
      while True:
          fw_list = await api.get_firmware_info()
          check_for_updates(fw_list)
          await asyncio.sleep(86400)  # 24 hours

4. **Handle pagination:**

   .. code-block:: python

      all_devices = []
      offset = 0
      
      while True:
          batch = await api.list_devices(offset=offset, count=20)
          if not batch:
              break
          all_devices.extend(batch)
          offset += 20

Related Documentation
=====================

* :doc:`auth_client` - Authentication client
* :doc:`mqtt_client` - MQTT client for monitoring/control
* :doc:`models` - Data models (Device, FirmwareInfo, etc.)
* :doc:`exceptions` - Exception handling
* :doc:`../protocol/rest_api` - REST API protocol details
