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
* Device information queries and renaming
* Firmware version checking and firmware image details
* Time-of-Use (TOU) schedule queries, conversion, application and removal
* Push notification settings
* Maintenance log (air filter and CIP replacement dates)
* Display preferences, fault history, user profile, app version check

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

      # /device/info also carries the installer and push flags
      if device.installer and device.installer.installer_id:
          print(f"Installer: {device.installer.installer_first_name}")
      if device.alarm_info:
          print(f"Fault alerts on: {device.alarm_info.is_error_alarm}")

update_device_info()
^^^^^^^^^^^^^^^^^^^^

.. py:method:: update_device_info(mac_address, additional_value, device_name, device_type=DeviceType.NPF700_WIFI, install_type=None, location=None)

   Rename a device or update its installation type and location
   (``POST /device/change-info``). ``install_type`` is omitted when
   empty, ``location`` is sent only when
   it has a state, city or address, and empty strings and zero
   coordinates inside it are left out.

   :param device_name: New device name
   :type device_name: str
   :param install_type: Installation type, e.g. ``"R"``
   :type install_type: str or None
   :param location: New location
   :type location: Location or None
   :return: True on success
   :rtype: bool

   **Example:**

   .. code-block:: python

      from nwp500 import Location

      await api.update_device_info(
          mac, additional_value, "Garage Heater",
          location=Location(state="California", city="Anytown",
                            address="123 Main Street"),
      )

list_simple_devices()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: list_simple_devices(target_user_id=None, offset=0, count=20)

   The trimmed device list from ``POST /device/simple-list``: identifiers,
   type and name only. ``target_user_id`` defaults to the signed-in user;
   an installer passes an owner's ID to list that owner's devices.

   :return: List of SimpleDevice objects
   :rtype: list[SimpleDevice]

get_error_history()
^^^^^^^^^^^^^^^^^^^

.. py:method:: get_error_history(mac_address, additional_value, continuous_key=None, count=20, installer_id=None)

   Faults the cloud has recorded for a device (``POST /device/error/list``),
   readable while the device is offline. It is an installer request: this
   method sends the signed-in user's ID as ``installerId`` by default. Whether the
   backend accepts an owner's ID there is untested.

   To fetch the next page pass the last entry's ``error_occurred_time`` as
   ``continuous_key``. Each entry carries the list's ``timeZone`` as
   ``time_zone``; ``occurred_at_local`` is the time in it.

   Installer accounts only: an owner account receives
   ``404 COMMON_NOT_AUTHORIZED`` (checked live).

   :return: List of DeviceErrorHistoryEntry objects
   :rtype: list[DeviceErrorHistoryEntry]

   **Example:**

   .. code-block:: python

      for fault in await api.get_error_history(mac, additional_value):
          print(fault.occurred_at, fault.error_code, fault.sub_error)

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

get_firmware_detail()
^^^^^^^^^^^^^^^^^^^^^

.. py:method:: get_firmware_detail(sw_code, sw_version)

   Describe a firmware image (``POST /firmware/info``) by the
   ``cur_sw_code``/``cur_version`` pair (or ``downloaded_version`` when an
   update is pending) from :class:`~nwp500.models.FirmwareInfo`.
   ``description`` holds the release notes and ``run_time`` the estimated
   update time in minutes.

   :param sw_code: Firmware component code
   :type sw_code: int
   :param sw_version: Firmware version number
   :type sw_version: int
   :return: Firmware image description
   :rtype: FirmwareDetail

   **Example:**

   .. code-block:: python

      for fw in await api.get_firmware_info(mac, additional_value):
          pending = fw.downloaded_version or fw.cur_version
          detail = await api.get_firmware_detail(fw.cur_sw_code, pending)
          print(detail.description, f"~{detail.run_time} min")

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

convert_tou() / update_tou()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

See :doc:`../../how-to/optimize-tou` for the OpenEI conversion and
apply workflow. ``convert_tou`` sends the signed-in user's ``userType``
from the sign-in response (``auth.current_user.user_type``) and falls
back to ``"O"`` (owner) when that is not available. ``get_tou_info``
and ``update_tou`` take a ``user_type`` that defaults to the same.

delete_tou()
^^^^^^^^^^^^

.. py:method:: delete_tou(mac_address, additional_value, register_path="wifi", source_type="openei", controller_id=None, user_type=None)

   Remove the TOU rate plan from a device (``DELETE /device/tou``). The
   request fields travel as a query string. Pass ``register_path="bt"`` and the ``controller_id`` for a plan
   that was registered over Bluetooth. ``user_type`` defaults to the
   signed-in user's type.

   :return: True on success
   :rtype: bool

get_manufacture_id()
^^^^^^^^^^^^^^^^^^^^

.. py:method:: get_manufacture_id(mac_address, additional_value, controller_id)

   The manufacture ID the TOU service holds for a device
   (``GET /device/tou/manufacture-id``). ``"000000000000000"`` means
   not available.

   :return: Manufacture ID
   :rtype: str

   ``controller_id`` is ``DeviceFeature.controller_serial_number``, the
   same value ``get_tou_info()`` takes; any other value returns
   ``500 INTERNAL_SERVER_ERROR``.

Push Notification Methods
--------------------------

get_push_settings()
^^^^^^^^^^^^^^^^^^^

.. py:method:: get_push_settings(mac_address, additional_value="")

   Which push notifications are enabled for a device
   (``POST /user/get-push-settings``).

   :return: Flags, each ``True`` (on), ``False`` (off) or ``None`` (not
            reported)
   :rtype: PushSettings

set_push_settings()
^^^^^^^^^^^^^^^^^^^

.. py:method:: set_push_settings(mac_address, additional_value="", *, error_alarm=None, descaling_alarm=None, etc_alarm=None)

   Enable or disable push notifications (``POST /user/set-push-settings``).
   Every flag the account has is sent, so a flag left ``None`` keeps its
   current value, read first with :meth:`get_push_settings`. One the
   cloud does not report (a member account's descaling flag) is omitted.
   On the
   wire 1 is on and 2 is off, the reverse of the device's on/off flags,
   which the library handles for you.

   :return: True on success
   :rtype: bool

   **Example:**

   .. code-block:: python

      # The other flags keep their current values.
      await api.set_push_settings(mac, additional_value, error_alarm=True)

update_push_token()
^^^^^^^^^^^^^^^^^^^

.. py:method:: update_push_token(push_token, model_name="Python Client", app_version="1.0.0", os="Python", os_version="3.8+")

   Register a push notification token (``POST /app/update-push-token``).

   :param push_token: Firebase device token
   :type push_token: str

   **Example:**

   .. code-block:: python

      await api.update_push_token("your_firebase_token", os="android")

Maintenance Log Methods
-----------------------

The cloud keeps a log of when the air filter was replaced and when a CIP
(clean-in-place / descaling) service was done. These are records only;
to reset the device's own filter timer use
:meth:`nwp500.NavienMqttClient.reset_air_filter`. See
:doc:`../../how-to/maintenance`.

record_filter_change() / record_cip_change()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: record_filter_change(mac_address, additional_value, maintenance_date, device_type=DeviceType.NPF700_WIFI)
.. py:method:: record_cip_change(mac_address, additional_value, maintenance_date, device_type=DeviceType.NPF700_WIFI)

   Record a replacement date (``POST /device/filter/change-info`` and
   ``POST /device/cip/change-info``). The date is sent as ``YYYY-M-D``
   without zero padding.

   :param maintenance_date: Date of the replacement
   :type maintenance_date: datetime.date
   :return: True on success
   :rtype: bool

get_filter_history() / get_cip_history()
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: get_filter_history(mac_address, additional_value, offset=0, count=20)
.. py:method:: get_cip_history(mac_address, additional_value, offset=0, count=20)

   List the recorded dates (``POST /device/filter/history`` and
   ``POST /device/cip/history``).

   :return: List of MaintenanceHistoryEntry objects
   :rtype: list[MaintenanceHistoryEntry]

Display Preference Methods
--------------------------

get_display_preferences()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: get_display_preferences(mac_address, additional_value, model_type_code=None)

   Unit display preferences the cloud stores for a device
   (``GET /device/preferences/format``). The cloud answers with a list;
   the first entry is the one in effect.

   :return: List of DisplayPreferences objects
   :rtype: list[DisplayPreferences]

   .. note::

      Not accepted for the NWP500 (``400 COMMON_BAD_REQUEST`` for device
      type 52, checked live); it serves the IoT-module hydro unit (device
      type 8).

set_display_preferences()
^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:method:: set_display_preferences(mac_address, additional_value, pressure_display_format, temperature_display_format, model_type_code=None)

   Store the display preferences (``POST /device/preferences/format``).
   Temperature is ``"F"``/``"C"`` and pressure ``"P"`` (psi)/``"M"``
   (metric).

   :return: True on success
   :rtype: bool

   .. note::

      Not accepted for the NWP500 (``400 COMMON_BAD_REQUEST`` for device
      type 52, checked live).

Account and App Methods
-----------------------

get_user_profile()
^^^^^^^^^^^^^^^^^^

.. py:method:: get_user_profile()

   The signed-in user's profile (``POST /user/info``): type, name, phone
   number, sequence number and e-mail.

   :return: User profile
   :rtype: UserProfile

get_app_version()
^^^^^^^^^^^^^^^^^

.. py:method:: get_app_version(os="A")

   The client release versions the cloud expects (``POST /app/version``),
   sent **without** authentication. When the backend is down for
   maintenance the cloud answers 403 with a notice, which is returned as
   :class:`~nwp500.models.AppVersionInfo` with ``server_check_text`` set
   (``is_under_maintenance`` is ``True``) instead of raising.

   :return: App version information
   :rtype: AppVersionInfo

   Before sign-in, when there is no client to call it on, use the
   module-level function, which opens a temporary session if none is
   given:

   .. code-block:: python

      from nwp500 import get_app_version

      info = await get_app_version()
      if info.is_under_maintenance:
          print(info.server_check_text)

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

* :doc:`auth_client`: Authentication client
* :doc:`mqtt_client`: MQTT client for monitoring/control
* :doc:`models`: Data models (Device, FirmwareInfo, etc.)
* :doc:`exceptions`: Exception handling
* :doc:`../protocol/rest_api`: REST API protocol details
