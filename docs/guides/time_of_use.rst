Time of Use (TOU) Pricing
==========================

The Navien NWP500 supports Time of Use (TOU) pricing schedules, allowing the water heater to optimize heating based on electricity rates that vary throughout the day. The Navien mobile app integrates with the OpenEI (Open Energy Information) API to retrieve utility rate information.

Overview
--------

Time of Use pricing enables:

* **Cost optimization**: Heat water during off-peak hours when electricity rates are lower
* **Demand response**: Reduce energy consumption during peak rate periods
* **Custom schedules**: Configure up to 16 different time periods with varying rates
* **Seasonal support**: Different schedules for different months of the year
* **Weekday/weekend support**: Separate schedules for weekdays and weekends

The system uses utility rate data from OpenEI to automatically configure optimal heating schedules based on your location and utility provider.

OpenEI API Integration
----------------------

The Navien mobile app queries the OpenEI Utility Rates API to retrieve current electricity rate information for the user's location. This allows the app to present available rate plans and configure TOU schedules automatically.

API Endpoint
~~~~~~~~~~~~

.. code-block:: text

    GET https://api.openei.org/utility_rates

Query Parameters
~~~~~~~~~~~~~~~~

The following parameters are used to query utility rates:

.. list-table::
   :widths: 20 15 65
   :header-rows: 1

   * - Parameter
     - Type
     - Description
   * - ``version``
     - integer
     - API version (currently ``7``)
   * - ``format``
     - string
     - Response format (``json``)
   * - ``api_key``
     - string
     - OpenEI API key (embedded in Navien app)
   * - ``detail``
     - string
     - Level of detail (``full`` for complete rate structure)
   * - ``address``
     - string
     - ZIP code or address to search
   * - ``sector``
     - string
     - Customer sector (``Residential``, ``Commercial``, etc.)
   * - ``orderby``
     - string
     - Sort field (``startdate`` for most recent rates)
   * - ``direction``
     - string
     - Sort direction (``desc`` for descending)
   * - ``limit``
     - integer
     - Maximum number of results (``100``)

Example Request
~~~~~~~~~~~~~~~

.. code-block:: text

    GET https://api.openei.org/utility_rates?version=7&format=json&api_key=YOUR_API_KEY&detail=full&address=94903&sector=Residential&orderby=startdate&direction=desc&limit=100

Response Format
~~~~~~~~~~~~~~~

The API returns a JSON response with an array of utility rate plans:

.. code-block:: json

    {
      "items": [
        {
          "label": "67575942fe4f0b50f5027994",
          "uri": "https://apps.openei.org/IURDB/rate/view/67575942fe4f0b50f5027994",
          "approved": true,
          "is_default": false,
          "utility": "Pacific Gas & Electric Co",
          "eiaid": 14328,
          "name": "E-1 -Residential Service Baseline Region Y",
          "startdate": 1727766000,
          "sector": "Residential",
          "servicetype": "Bundled",
          "description": "This schedule is applicable to single-phase and polyphase residential service...",
          "energyratestructure": [
            [
              {
                "max": 10.5,
                "unit": "kWh daily",
                "rate": 0.40206
              },
              {
                "max": 42,
                "unit": "kWh daily",
                "rate": 0.50323
              }
            ]
          ],
          "energyweekdayschedule": [
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
          ],
          "energyweekendschedule": [
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
          ]
        }
      ]
    }

Key Response Fields
"""""""""""""""""""

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - Field
     - Type
     - Description
   * - ``utility``
     - string
     - Name of the utility company
   * - ``eiaid``
     - integer
     - EIA (Energy Information Administration) utility ID
   * - ``name``
     - string
     - Rate plan name
   * - ``startdate``
     - integer
     - Unix timestamp when rate plan becomes effective
   * - ``energyratestructure``
     - array
     - Tiered rate structure by season and tier
   * - ``energyweekdayschedule``
     - array
     - 24-hour schedule by month (0=off-peak, 1=on-peak)
   * - ``energyweekendschedule``
     - array
     - 24-hour weekend schedule by month
   * - ``mincharge``
     - float
     - Minimum daily charge
   * - ``fixedchargeunits``
     - string
     - Units for fixed charges (e.g., ``$/month``)

Rate Structure
~~~~~~~~~~~~~~

The ``energyratestructure`` field contains tiered pricing:

* Each outer array element represents a season or month
* Each inner array element represents a usage tier
* ``rate`` field contains the price per kWh
* ``max`` field indicates the upper limit for that tier (optional)

Hour-by-Hour Schedules
~~~~~~~~~~~~~~~~~~~~~~

The ``energyweekdayschedule`` and ``energyweekendschedule`` arrays map rate periods:

* 12 elements (one per month)
* Each month has 24 elements (one per hour)
* Values map to indices in ``energyratestructure``
* ``0`` typically represents off-peak, ``1`` represents on-peak

TOU API Methods
---------------

The library provides methods for working with TOU information through both REST API and MQTT.

REST API: Get TOU Info
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def get_tou_info(
        mac_address: str,
        additional_value: str,
        controller_id: str,
        user_type: str = "O"
    ) -> TOUInfo

Retrieves stored TOU configuration from the Navien cloud API.

**Parameters:**

* ``mac_address``: Device MAC address
* ``additional_value``: Additional device identifier
* ``controller_id``: Controller serial number
* ``user_type``: User type (default: ``"O"`` for owner)

**Returns:**

``TOUInfo`` object containing:

.. code-block:: python

    @dataclass
    class TOUInfo:
        register_path: str        # Path where TOU data is stored
        source_type: str          # Source of rate data (e.g., "openei")
        controller_id: str        # Controller serial number
        manufacture_id: str       # Manufacturer ID
        name: str                 # Rate plan name
        utility: str              # Utility company name
        zip_code: int            # ZIP code
        schedule: List[TOUSchedule]  # TOU schedule periods

MQTT: Configure TOU Schedule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def configure_tou_schedule(
        device: Device,
        controller_serial_number: str,
        periods: List[Dict[str, Any]],
        enabled: bool = True
    ) -> None

Configures the TOU schedule directly on the device via MQTT.

**Parameters:**

* ``device``: Device object from API
* ``controller_serial_number``: Controller serial number (obtain via device info)
* ``periods``: List of TOU period dictionaries (up to 16 periods)
* ``enabled``: Whether to enable TOU scheduling (default: ``True``)

MQTT: Enable/Disable TOU
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def set_tou_enabled(
        device: Device,
        enabled: bool
    ) -> None

Enables or disables TOU operation without changing the schedule.

**Parameters:**

* ``device``: Device object
* ``enabled``: ``True`` to enable TOU, ``False`` to disable

MQTT: Request TOU Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def request_tou_settings(
        device: Device,
        controller_serial_number: str
    ) -> None

Requests the current TOU configuration from the device.

**Parameters:**

* ``device``: Device object
* ``controller_serial_number``: Controller serial number

The device will respond on the topic:

.. code-block:: text

    cmd/{deviceType}/{deviceId}/res/tou/rd

Building TOU Periods
--------------------

Helper Methods
~~~~~~~~~~~~~~

The library provides helper functions for building TOU period configurations:

build_tou_period()
""""""""""""""""""

.. code-block:: python

    def build_tou_period(
        season_months: Union[List[int], range],
        week_days: List[str],
        start_hour: int,
        start_minute: int,
        end_hour: int,
        end_minute: int,
        price_min: float,
        price_max: float,
        decimal_point: int = 5
    ) -> Dict[str, Any]

Creates a TOU period configuration dictionary.

**Parameters:**

* ``season_months``: List of months (1-12) when this period applies
* ``week_days``: List of day names (e.g., ``["Monday", "Tuesday"]``)
* ``start_hour``: Start hour (0-23)
* ``start_minute``: Start minute (0-59)
* ``end_hour``: End hour (0-23)
* ``end_minute``: End minute (0-59)
* ``price_min``: Minimum electricity price ($/kWh)
* ``price_max``: Maximum electricity price ($/kWh)
* ``decimal_point``: Number of decimal places for price encoding (default: 5)

**Returns:**

Dictionary with encoded TOU period data ready for MQTT transmission.

encode_price()
""""""""""""""

.. code-block:: python

    def encode_price(price: float, decimal_point: int = 5) -> int

Encodes a floating-point price into an integer for transmission.

**Example:**

.. code-block:: python

    from nwp500 import encode_price
    
    # Encode $0.45000 per kWh
    encoded = encode_price(0.45, decimal_point=5)
    # Returns: 45000

decode_price()
""""""""""""""

.. code-block:: python

    def decode_price(encoded_price: int, decimal_point: int = 5) -> float

Decodes an integer price back to floating-point.

**Example:**

.. code-block:: python

    from nwp500 import decode_price
    
    # Decode price from device
    price = decode_price(45000, decimal_point=5)
    # Returns: 0.45

encode_week_bitfield()
""""""""""""""""""""""

.. code-block:: python

    def encode_week_bitfield(day_names: List[str]) -> int

Encodes a list of day names into a bitfield.

**Valid day names:**

* ``"Sunday"`` (bit 0)
* ``"Monday"`` (bit 1)
* ``"Tuesday"`` (bit 2)
* ``"Wednesday"`` (bit 3)
* ``"Thursday"`` (bit 4)
* ``"Friday"`` (bit 5)
* ``"Saturday"`` (bit 6)

**Example:**

.. code-block:: python

    from nwp500 import encode_week_bitfield
    
    # Weekdays only
    bitfield = encode_week_bitfield([
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
    ])
    # Returns: 0b0111110 = 62

decode_week_bitfield()
""""""""""""""""""""""

.. code-block:: python

    def decode_week_bitfield(bitfield: int) -> List[str]

Decodes a bitfield back into a list of day names.

**Example:**

.. code-block:: python

    from nwp500 import decode_week_bitfield
    
    # Decode weekday bitfield
    days = decode_week_bitfield(62)
    # Returns: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

Usage Examples
==============

Example 1: Simple TOU Schedule
------------------------------

Configure two rate periods - off-peak and peak pricing:

.. code-block:: python

    import asyncio
    from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient, build_tou_period

    async def configure_simple_tou():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            # Get device
            api_client = NavienAPIClient(auth_client=auth_client)
            device = await api_client.get_first_device()
            
            # Connect MQTT and get controller serial
            mqtt_client = NavienMqttClient(auth_client)
            await mqtt_client.connect()
            
            # Request device info to get controller serial number
            feature_future = asyncio.Future()
            
            def capture_feature(feature):
                if not feature_future.done():
                    feature_future.set_result(feature)
            
            await mqtt_client.subscribe_device_feature(device, capture_feature)
            await mqtt_client.request_device_info(device)
            feature = await asyncio.wait_for(feature_future, timeout=15)
            controller_serial = feature.controllerSerialNumber
            
            # Define off-peak period (midnight to 2 PM, weekdays)
            off_peak = build_tou_period(
                season_months=range(1, 13),  # All months
                week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                start_hour=0,
                start_minute=0,
                end_hour=14,
                end_minute=59,
                price_min=0.12,   # $0.12/kWh
                price_max=0.12,
                decimal_point=5
            )
            
            # Define peak period (3 PM to 8 PM, weekdays)
            peak = build_tou_period(
                season_months=range(1, 13),
                week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                start_hour=15,
                start_minute=0,
                end_hour=20,
                end_minute=59,
                price_min=0.35,   # $0.35/kWh
                price_max=0.35,
                decimal_point=5
            )
            
            # Configure TOU schedule
            await mqtt_client.configure_tou_schedule(
                device=device,
                controller_serial_number=controller_serial,
                periods=[off_peak, peak],
                enabled=True
            )
            
            print("TOU schedule configured successfully")
            await mqtt_client.disconnect()

    asyncio.run(configure_simple_tou())

Example 2: Complex Seasonal Schedule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure different rates for summer and winter:

.. code-block:: python

    async def configure_seasonal_tou():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            api_client = NavienAPIClient(auth_client=auth_client)
            device = await api_client.get_first_device()
            
            mqtt_client = NavienMqttClient(auth_client)
            await mqtt_client.connect()
            
            # ... get controller_serial (same as Example 1) ...
            
            # Summer off-peak (June-September, all day except 2-8 PM)
            summer_off_peak = build_tou_period(
                season_months=[6, 7, 8, 9],
                week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                start_hour=0,
                start_minute=0,
                end_hour=13,
                end_minute=59,
                price_min=0.15,
                price_max=0.15,
                decimal_point=5
            )
            
            # Summer peak (June-September, 2-8 PM)
            summer_peak = build_tou_period(
                season_months=[6, 7, 8, 9],
                week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                start_hour=14,
                start_minute=0,
                end_hour=20,
                end_minute=59,
                price_min=0.45,
                price_max=0.45,
                decimal_point=5
            )
            
            # Winter rates (October-May)
            winter_off_peak = build_tou_period(
                season_months=[10, 11, 12, 1, 2, 3, 4, 5],
                week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                start_hour=0,
                start_minute=0,
                end_hour=13,
                end_minute=59,
                price_min=0.10,
                price_max=0.10,
                decimal_point=5
            )
            
            winter_peak = build_tou_period(
                season_months=[10, 11, 12, 1, 2, 3, 4, 5],
                week_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                start_hour=17,
                start_minute=0,
                end_hour=21,
                end_minute=59,
                price_min=0.28,
                price_max=0.28,
                decimal_point=5
            )
            
            # Configure all periods
            await mqtt_client.configure_tou_schedule(
                device=device,
                controller_serial_number=controller_serial,
                periods=[summer_off_peak, summer_peak, winter_off_peak, winter_peak],
                enabled=True
            )
            
            await mqtt_client.disconnect()

    asyncio.run(configure_seasonal_tou())

Example 3: Retrieve Current TOU Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Query the device for its current TOU configuration:

.. code-block:: python

    from nwp500 import decode_week_bitfield, decode_price

    async def check_tou_settings():
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            api_client = NavienAPIClient(auth_client=auth_client)
            device = await api_client.get_first_device()
            
            mqtt_client = NavienMqttClient(auth_client)
            await mqtt_client.connect()
            
            # ... get controller_serial (same as Example 1) ...
            
            # Set up response handler
            response_topic = f"cmd/{device.device_info.device_type}/{mqtt_client.config.client_id}/res/tou/rd"
            
            def on_tou_response(topic: str, message: dict):
                response = message.get("response", {})
                enabled = response.get("reservationUse")
                periods = response.get("reservation", [])
                
                print(f"TOU Enabled: {enabled}")
                print(f"Number of periods: {len(periods)}")
                
                for i, period in enumerate(periods, 1):
                    days = decode_week_bitfield(period.get("week", 0))
                    price_min = decode_price(
                        period.get("priceMin", 0),
                        period.get("decimalPoint", 0)
                    )
                    price_max = decode_price(
                        period.get("priceMax", 0),
                        period.get("decimalPoint", 0)
                    )
                    
                    print(f"\nPeriod {i}:")
                    print(f"  Days: {', '.join(days)}")
                    print(f"  Time: {period['startHour']:02d}:{period['startMinute']:02d} "
                          f"- {period['endHour']:02d}:{period['endMinute']:02d}")
                    print(f"  Price: ${price_min:.5f} - ${price_max:.5f}/kWh")
            
            await mqtt_client.subscribe(response_topic, on_tou_response)
            
            # Request current settings
            await mqtt_client.request_tou_settings(device, controller_serial)
            
            # Wait for response
            await asyncio.sleep(5)
            await mqtt_client.disconnect()

    asyncio.run(check_tou_settings())

Example 4: Toggle TOU On/Off
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enable or disable TOU operation:

.. code-block:: python

    async def toggle_tou(enable: bool):
        async with NavienAuthClient("user@example.com", "password") as auth_client:
            api_client = NavienAPIClient(auth_client=auth_client)
            device = await api_client.get_first_device()
            
            mqtt_client = NavienMqttClient(auth_client)
            await mqtt_client.connect()
            
            # Enable or disable TOU
            await mqtt_client.set_tou_enabled(device, enabled=enable)
            
            print(f"TOU {'enabled' if enable else 'disabled'}")
            await mqtt_client.disconnect()

    # Enable TOU
    asyncio.run(toggle_tou(True))

    # Disable TOU
    asyncio.run(toggle_tou(False))

Example 5: Retrieve Schedule from OpenEI API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This example demonstrates the complete workflow of retrieving utility rate 
data from the OpenEI API and configuring it on your device:

.. code-block:: python

    import asyncio
    import aiohttp
    from nwp500 import NavienAPIClient, NavienAuthClient, NavienMqttClient, build_tou_period

    OPENEI_API_URL = "https://api.openei.org/utility_rates"
    OPENEI_API_KEY = "DEMO_KEY"  # Get your own key at openei.org

    async def fetch_openei_rates(zip_code: str, api_key: str):
        """Fetch utility rates from OpenEI API."""
        params = {
            "version": 7,
            "format": "json",
            "api_key": api_key,
            "detail": "full",
            "address": zip_code,
            "sector": "Residential",
            "orderby": "startdate",
            "direction": "desc",
            "limit": 100,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(OPENEI_API_URL, params=params) as response:
                response.raise_for_status()
                return await response.json()

    def select_tou_rate_plan(rate_data):
        """Select first approved residential TOU plan."""
        for plan in rate_data.get("items", []):
            if (
                plan.get("approved")
                and plan.get("sector") == "Residential"
                and "energyweekdayschedule" in plan
                and "energyratestructure" in plan
            ):
                return plan
        return None

    def convert_openei_to_tou_periods(rate_plan):
        """Convert OpenEI rate structure to Navien TOU periods."""
        weekday_schedule = rate_plan["energyweekdayschedule"][0]
        rate_structure = rate_plan["energyratestructure"][0]
        
        # Map period indices to rates
        period_rates = {}
        for idx, tier in enumerate(rate_structure):
            period_rates[idx] = tier.get("rate", 0.0)
        
        # Find continuous time blocks
        periods = []
        current_period = None
        start_hour = 0
        
        for hour in range(24):
            period_idx = weekday_schedule[hour]
            
            if period_idx != current_period:
                if current_period is not None:
                    # Save previous period
                    periods.append({
                        "start_hour": start_hour,
                        "end_hour": hour - 1,
                        "end_minute": 59,
                        "rate": period_rates.get(current_period, 0.0),
                    })
                current_period = period_idx
                start_hour = hour
        
        # Last period
        periods.append({
            "start_hour": start_hour,
            "end_hour": 23,
            "end_minute": 59,
            "rate": period_rates.get(current_period, 0.0),
        })
        
        # Convert to TOU format
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        return [
            build_tou_period(
                season_months=range(1, 13),
                week_days=weekdays,
                start_hour=p["start_hour"],
                start_minute=0,
                end_hour=p["end_hour"],
                end_minute=p["end_minute"],
                price_min=p["rate"],
                price_max=p["rate"],
                decimal_point=5,
            )
            for p in periods
        ]

    async def configure_openei_schedule():
        """Main function to retrieve and configure TOU from OpenEI."""
        zip_code = "94103"  # San Francisco example
        
        # Fetch and parse OpenEI data
        rate_data = await fetch_openei_rates(zip_code, OPENEI_API_KEY)
        rate_plan = select_tou_rate_plan(rate_data)
        
        if not rate_plan:
            print("No suitable TOU rate plan found")
            return
        
        print(f"Using plan: {rate_plan['name']}")
        print(f"Utility: {rate_plan['utility']}")
        
        tou_periods = convert_openei_to_tou_periods(rate_plan)
        
        # Configure on device
        async with NavienAuthClient("user@example.com", "password") as auth:
            api_client = NavienAPIClient(auth_client=auth)
            device = await api_client.get_first_device()
            
            mqtt_client = NavienMqttClient(auth)
            await mqtt_client.connect()
            
            # Get controller serial (see Example 1 for full code)
            # ... obtain controller_serial ...
            
            # Configure the schedule
            await mqtt_client.configure_tou_schedule(
                device=device,
                controller_serial_number=controller_serial,
                periods=tou_periods,
                enabled=True,
            )
            
            print(f"Configured {len(tou_periods)} TOU periods from OpenEI")
            await mqtt_client.disconnect()

    asyncio.run(configure_openei_schedule())

**Key Points:**

* The OpenEI API requires a free API key (register at openei.org)
* The ``DEMO_KEY`` is rate-limited and suitable for testing only
* Rate structures vary by utility - this example handles simple TOU plans
* Complex tiered rates may require additional logic to flatten into periods
* The example uses weekday schedules; extend for weekends as needed
* Set ``ZIP_CODE`` environment variable to search your location

**Required Dependencies:**

.. code-block:: bash

    pip install aiohttp

**Complete Working Example:**

See ``examples/tou_openei_example.py`` for a fully working implementation 
with error handling, weekend support, and detailed console output.

MQTT Message Format
-------------------

TOU Control Topic
~~~~~~~~~~~~~~~~~

To configure TOU settings, publish to:

.. code-block:: text

    cmd/{deviceType}/{macAddress}/ctrl/tou/rd

Message payload:

.. code-block:: json

    {
      "cmd": "tou",
      "controllerId": "controller-serial-number",
      "operation": {
        "reservationUse": 2,
        "reservation": [
          {
            "season": 4095,
            "week": 62,
            "startHour": 0,
            "startMinute": 0,
            "endHour": 14,
            "endMinute": 59,
            "priceMin": 12000,
            "priceMax": 12000,
            "decimalPoint": 5
          }
        ]
      },
      "requestTopic": "cmd/{deviceType}/{macAddress}/ctrl/tou/rd",
      "responseTopic": "cmd/{deviceType}/{clientId}/res/tou/rd"
    }

Field Descriptions
""""""""""""""""""

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - Field
     - Type
     - Description
   * - ``reservationUse``
     - integer
     - ``0`` = disabled, ``2`` = enabled
   * - ``season``
     - integer
     - Bitfield of months (bit 0 = Jan, ... bit 11 = Dec). ``4095`` = all months
   * - ``week``
     - integer
     - Bitfield of days (bit 0 = Sun, ... bit 6 = Sat)
   * - ``startHour``
     - integer
     - Start hour (0-23)
   * - ``startMinute``
     - integer
     - Start minute (0-59)
   * - ``endHour``
     - integer
     - End hour (0-23)
   * - ``endMinute``
     - integer
     - End minute (0-59)
   * - ``priceMin``
     - integer
     - Encoded minimum price (see ``encode_price()``)
   * - ``priceMax``
     - integer
     - Encoded maximum price (see ``encode_price()``)
   * - ``decimalPoint``
     - integer
     - Number of decimal places in price encoding

TOU Response Topic
~~~~~~~~~~~~~~~~~~

The device responds on:

.. code-block:: text

    cmd/{deviceType}/{clientId}/res/tou/rd

Response payload matches the control payload format.

TOU Status in Device State
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The device status includes TOU-related fields:

.. code-block:: json

    {
      "touStatus": 1,
      "touOverrideStatus": 0
    }

* ``touStatus``: ``1`` if TOU scheduling is active, ``0`` if inactive
* ``touOverrideStatus``: ``1`` if user has temporarily overridden TOU schedule

See :doc:`../protocol/device_status` for more details.

Best Practices
--------------

1. **Obtain controller serial number first**

   The controller serial number is required for TOU operations. Request it via device info before configuring TOU.

2. **Limit number of periods**

   The device supports up to 16 TOU periods. Design schedules efficiently to stay within this limit.

3. **Use appropriate decimal precision**

   Use ``decimal_point=5`` for most rate plans, which provides precision down to $0.00001/kWh.

4. **Validate overlapping periods**

   Ensure time periods don't overlap within the same day and month combination.

5. **Test with simulation**

   Use ``set_tou_enabled(False)`` to disable TOU temporarily for testing without losing the schedule.

6. **Monitor response topics**

   Always subscribe to response topics before sending commands to confirm successful configuration.

7. **Handle timeouts gracefully**

   Use ``asyncio.wait_for()`` with appropriate timeouts when waiting for device responses.

Limitations
-----------

* Maximum 16 TOU periods per configuration
* Time resolution limited to minutes (no seconds)
* Price encoding limited by decimal point precision
* Cannot specify different rates for individual days within a period
* No support for variable rate structures (e.g., tiered rates) - only flat rate per period

Further Reading
---------------

* :doc:`../python_api/api_client` - API client documentation and ``get_tou_info()`` method
* :doc:`../python_api/mqtt_client` - MQTT client and TOU configuration methods
* :doc:`../protocol/mqtt_protocol` - MQTT message formats including TOU commands
* :doc:`../protocol/device_status` - Device status fields including ``touStatus``
* `OpenEI Utility Rates API <https://openei.org/services/doc/rest/util_rates/?version=7>`__ - Official OpenEI API documentation
* `OpenEI IURDB <https://apps.openei.org/IURDB/>`__ - Interactive Utility Rate Database

Related Examples
----------------

* ``examples/tou_schedule_example.py`` - Complete working example of manual TOU configuration
* ``examples/tou_openei_example.py`` - Retrieve TOU schedules from OpenEI API and configure device

For questions or issues related to TOU functionality, please refer to the project repository.
