=====================
Reservation Schedules
=====================

Overview
========

Reservations (also called "scheduled programs") allow you to automatically
change your water heater's operating mode and temperature at specific times
of day. This is useful for:

* **Morning preparation**: Switch to High Demand mode before your morning
  shower
* **Energy optimization**: Use Energy Saver mode during the day when demand
  is low
* **Weekend schedules**: Different settings for weekdays vs. weekends
* **Vacation mode**: Automatically enable vacation mode during extended
  absences

Reservations are stored on the device itself and execute locally, so they
continue to work even if your internet connection is lost.

Quick Example
=============

Here's a simple example that sets up a weekday morning reservation:

.. code-block:: python

   import asyncio
   from nwp500 import (
       NavienAuthClient,
       NavienAPIClient,
       NavienMqttClient
   )

   async def main():
       async with NavienAuthClient(
           "email@example.com",
           "password"
       ) as auth:
           # Get device
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           # Build reservation entry
           weekday_morning = NavienAPIClient.build_reservation_entry(
               enabled=True,
               days=["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday"],
               hour=6,
               minute=30,
               mode_id=4,  # High Demand
               temperature_f=140.0  # Temperature in Fahrenheit
           )

           # Send to device
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           await mqtt.update_reservations(
               device,
               [weekday_morning],
               enabled=True
           )
           await mqtt.disconnect()

   asyncio.run(main())

Reservation Entry Format
=========================

Each reservation entry is a dictionary with the following fields:

JSON Schema
-----------

.. code-block:: json

   {
       "enable": 1,
       "week": 62,
       "hour": 6,
       "min": 30,
       "mode": 4,
       "param": 120
   }

Field Descriptions
------------------

``enable`` (integer, required)
   Enable flag for this reservation entry:
   
   * ``1`` - Enabled (reservation will execute)
   * ``2`` - Disabled (reservation is stored but won't execute)

``week`` (integer, required)
   Bitfield representing days of the week when this reservation should run.
   Each bit corresponds to a day:
   
   * Bit 0 (value 1): Sunday
   * Bit 1 (value 2): Monday
   * Bit 2 (value 4): Tuesday
   * Bit 3 (value 8): Wednesday
   * Bit 4 (value 16): Thursday
   * Bit 5 (value 32): Friday
   * Bit 6 (value 64): Saturday
   
   **Examples:**
   
   * Weekdays only: ``62`` (binary: 0111110 = Mon+Tue+Wed+Thu+Fri)
   * Weekends only: ``65`` (binary: 1000001 = Sun+Sat)
   * Every day: ``127`` (binary: 1111111 = all days)
   * Monday only: ``2`` (binary: 0000010)

``hour`` (integer, required)
   Hour when reservation should execute (24-hour format, 0-23).

``min`` (integer, required)
   Minute when reservation should execute (0-59).

``mode`` (integer, required)
   DHW operation mode to switch to. Valid mode IDs:
   
   * ``1`` - Heat Pump Only
   * ``2`` - Electric Heater Only
   * ``3`` - Energy Saver (Eco Mode)
   * ``4`` - High Demand
   * ``5`` - Vacation Mode
   * ``6`` - Power Off

``param`` (integer, required)
   Mode-specific parameter value. For temperature modes (1-4), this is the
   target water temperature encoded in **half-degrees Celsius**:
   
   * Conversion formula: ``fahrenheit = (param / 2.0) * 9/5 + 32``
   * Inverse formula: ``param = (fahrenheit - 32) * 5/9 * 2``
   
   **Temperature Examples:**
   
   * 95°F display → ``param = 70`` (35°C × 2)
   * 120°F display → ``param = 98`` (48.9°C × 2)
   * 130°F display → ``param = 109`` (54.4°C × 2)
   * 140°F display → ``param = 120`` (60°C × 2)
   * 150°F display → ``param = 131`` (65.6°C × 2)
   
   For non-temperature modes (Vacation, Power Off), the param value is
   typically ignored but should be set to a valid temperature value
   (e.g., ``98`` for 120°F) for consistency.

   **Note:** When using ``build_reservation_entry()``, you don't need to
   calculate the param value manually - just pass ``temperature_f`` in
   Fahrenheit and the conversion is handled automatically.

Helper Functions
================

The library provides helper functions to make building reservations easier.

Building Reservation Entries
-----------------------------

Use ``build_reservation_entry()`` to create properly formatted entries.
The function accepts temperature in Fahrenheit and handles the conversion
to the device's internal format automatically:

.. code-block:: python

   from nwp500 import build_reservation_entry

   # Weekday morning - High Demand mode at 140°F
   entry = build_reservation_entry(
       enabled=True,
       days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
       hour=6,
       minute=30,
       mode_id=4,  # High Demand
       temperature_f=140.0  # Temperature in Fahrenheit
   )
   # Returns: {'enable': 1, 'week': 62, 'hour': 6, 'min': 30,
   #           'mode': 4, 'param': 120}

   # Weekend - Energy Saver mode at 120°F
   entry2 = build_reservation_entry(
       enabled=True,
       days=["Saturday", "Sunday"],
       hour=8,
       minute=0,
       mode_id=3,  # Energy Saver
       temperature_f=120.0
   )

   # You can also use day indices (0=Sunday, 6=Saturday)
   entry3 = build_reservation_entry(
       enabled=True,
       days=[1, 2, 3, 4, 5],  # Monday-Friday
       hour=18,
       minute=0,
       mode_id=1,  # Heat Pump Only
       temperature_f=130.0
   )

Temperature Conversion Utility
-------------------------------

For advanced use cases, you can use ``fahrenheit_to_half_celsius()`` directly:

.. code-block:: python

   from nwp500 import fahrenheit_to_half_celsius

   param = fahrenheit_to_half_celsius(140.0)  # Returns 120
   param = fahrenheit_to_half_celsius(120.0)  # Returns 98
   param = fahrenheit_to_half_celsius(95.0)   # Returns 70

Encoding Week Bitfields
------------------------

To manually encode days into a bitfield:

.. code-block:: python

   from nwp500.encoding import encode_week_bitfield

   # From day names
   weekdays = encode_week_bitfield(
       ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
   )
   # Returns: 62

   # From day indices (0-6, Sunday=0)
   weekends = encode_week_bitfield([0, 6])
   # Returns: 65 (Sunday + Saturday)

   # Mixed case and whitespace are handled
   days = encode_week_bitfield(["monday", " Tuesday ", "WEDNESDAY"])
   # Returns: 14

Decoding Week Bitfields
------------------------

To decode a bitfield back to day names:

.. code-block:: python

   from nwp500.encoding import decode_week_bitfield

   days = decode_week_bitfield(62)
   # Returns: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

   days = decode_week_bitfield(127)
   # Returns: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
   #           'Friday', 'Saturday']

Managing Reservations
======================

Updating Reservations
---------------------

Send a new reservation schedule to the device:

.. code-block:: python

   async def update_schedule():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           # Build multiple reservation entries
           reservations = [
               # Weekday morning: High Demand at 140°F
               build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=6,
                   minute=30,
                   mode_id=4,
                   temperature_f=140.0
               ),
               # Weekday evening: Energy Saver at 130°F
               build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=18,
                   minute=0,
                   mode_id=3,
                   temperature_f=130.0
               ),
               # Weekend: Heat Pump Only at 120°F
               build_reservation_entry(
                   enabled=True,
                   days=["Saturday", "Sunday"],
                   hour=8,
                   minute=0,
                   mode_id=1,
                   temperature_f=120.0
               ),
           ]

           # Send to device
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           await mqtt.update_reservations(
               device,
               reservations,
               enabled=True  # Enable reservation system
           )
           await mqtt.disconnect()

Reading Current Reservations
-----------------------------

Request the current reservation schedule from the device:

.. code-block:: python

   import asyncio
   from typing import Any
   from nwp500 import decode_week_bitfield

   async def read_schedule():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           # Subscribe to reservation responses
           response_topic = (
               f"cmd/{device.device_info.device_type}/"
               f"{mqtt.config.client_id}/res/rsv/rd"
           )

           def on_reservation_response(
               topic: str,
               message: dict[str, Any]
           ) -> None:
               response = message.get("response", {})
               use = response.get("reservationUse", 0)
               entries = response.get("reservation", [])

               print(f"Reservation System: "
                     f"{'Enabled' if use == 1 else 'Disabled'}")
               print(f"Number of entries: {len(entries)}")

               for idx, entry in enumerate(entries, 1):
                   days = decode_week_bitfield(
                       entry.get("week", 0)
                   )
                   hour = entry.get("hour", 0)
                   minute = entry.get("min", 0)
                   mode = entry.get("mode", 0)
                   # Convert from half-degrees Celsius to Fahrenheit
                   raw_param = entry.get("param", 0)
                   display_temp = (raw_param / 2.0) * 9/5 + 32

                   print(f"\nEntry {idx}:")
                   print(f"  Time: {hour:02d}:{minute:02d}")
                   print(f"  Days: {', '.join(days)}")
                   print(f"  Mode: {mode}")
                   print(f"  Temp: {display_temp:.1f}°F")

           await mqtt.subscribe(response_topic, on_reservation_response)

           # Request current schedule
           await mqtt.request_reservations(device)

           # Wait for response
           await asyncio.sleep(5)
           await mqtt.disconnect()

Disabling Reservations
-----------------------

To disable the reservation system while keeping entries stored:

.. code-block:: python

   async def disable_reservations():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           # Keep existing entries but disable execution
           await mqtt.update_reservations(
               device,
               [],  # Empty list keeps existing entries
               enabled=False  # Disable reservation system
           )

           await mqtt.disconnect()

Clearing All Reservations
--------------------------

To completely clear the reservation schedule:

.. code-block:: python

   async def clear_reservations():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           # Send empty list with disabled flag
           await mqtt.update_reservations(
               device,
               [],
               enabled=False
           )

           await mqtt.disconnect()

Common Patterns
===============

Weekday vs. Weekend Schedules
------------------------------

Different settings for work days and weekends:

.. code-block:: python

   reservations = [
       # Weekday morning: early start, high demand
       build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],  # Mon-Fri
           hour=5,
           minute=30,
           mode_id=4,  # High Demand
           temperature_f=140.0
       ),
       # Weekend morning: later start, energy saver
       build_reservation_entry(
           enabled=True,
           days=[0, 6],  # Sun, Sat
           hour=8,
           minute=0,
           mode_id=3,  # Energy Saver
           temperature_f=130.0
       ),
   ]

Energy Optimization Schedule
-----------------------------

Minimize energy use during peak hours:

.. code-block:: python

   reservations = [
       # Morning prep: 6:00 AM - High Demand for showers
       build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=6,
           minute=0,
           mode_id=4,
           temperature_f=140.0
       ),
       # Day: 9:00 AM - Switch to Energy Saver
       build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=9,
           minute=0,
           mode_id=3,
           temperature_f=120.0
       ),
       # Evening: 5:00 PM - Heat Pump Only (before peak pricing)
       build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=17,
           minute=0,
           mode_id=1,
           temperature_f=130.0
       ),
       # Night: 10:00 PM - Back to Energy Saver
       build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=22,
           minute=0,
           mode_id=3,
           temperature_f=120.0
       ),
   ]

Vacation Mode Automation
-------------------------

Automatically enable vacation mode during a trip:

.. code-block:: python

   # Enable vacation mode at start of trip
   start_vacation = build_reservation_entry(
       enabled=True,
       days=["Friday"],  # Leaving Friday evening
       hour=20,
       minute=0,
       mode_id=5,  # Vacation Mode
       temperature_f=120.0  # Temperature doesn't matter for vacation mode
   )

   # Return to normal operation when you get back
   end_vacation = build_reservation_entry(
       enabled=True,
       days=["Sunday"],  # Returning Sunday afternoon
       hour=14,
       minute=0,
       mode_id=3,  # Energy Saver
       temperature_f=130.0
   )

   reservations = [start_vacation, end_vacation]

Important Notes
===============

Temperature Conversion
-----------------------

When using ``build_reservation_entry()``, pass temperatures in Fahrenheit
using the ``temperature_f`` parameter. The function automatically converts
to the device's internal format (half-degrees Celsius).

The valid temperature range is 95°F to 150°F.

For reading reservation responses from the device, the ``param`` field
contains the raw half-degrees Celsius value. Convert to Fahrenheit with:

.. code-block:: python

   fahrenheit = (param / 2.0) * 9/5 + 32

Device Limits
-------------

* The device can store a limited number of reservation entries (typically
  around 10-20)
* Entries are stored in order and execute based on time and day matching
* If multiple entries match the same time, the last one sent takes
  precedence
* Reservations execute in the device's local time zone

Execution Timing
----------------

* Reservations execute at the exact minute specified
* The device checks for matching reservations every minute
* If the device is powered off, reservations will not execute (use mode 6
  in a reservation to power off)
* Reservations persist through power cycles and internet outages

Complete Example
================

Full working example with error handling and response monitoring:

.. code-block:: python

   #!/usr/bin/env python3
   """Complete reservation management example."""

   import asyncio
   import os
   import sys
   from typing import Any

   from nwp500 import (
       NavienAPIClient,
       NavienAuthClient,
       NavienMqttClient,
       build_reservation_entry,
       decode_week_bitfield,
   )


   async def main() -> None:
       # Get credentials
       email = os.getenv("NAVIEN_EMAIL")
       password = os.getenv("NAVIEN_PASSWORD")

       if not email or not password:
           print("Error: Set NAVIEN_EMAIL and NAVIEN_PASSWORD")
           sys.exit(1)

       async with NavienAuthClient(email, password) as auth:
           # Get device
           api = NavienAPIClient(auth)
           device = await api.get_first_device()
           if not device:
               print("No devices found")
               return

           print(f"Managing reservations for: "
                 f"{device.device_info.device_name}")

           # Build comprehensive schedule
           reservations = [
               # Weekday morning
               build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=6,
                   minute=30,
                   mode_id=4,  # High Demand
                   temperature_f=140.0
               ),
               # Weekday day
               build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=9,
                   minute=0,
                   mode_id=3,  # Energy Saver
                   temperature_f=120.0
               ),
               # Weekend morning
               build_reservation_entry(
                   enabled=True,
                   days=["Saturday", "Sunday"],
                   hour=8,
                   minute=0,
                   mode_id=3,  # Energy Saver
                   temperature_f=130.0
               ),
           ]

           # Connect to MQTT
           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           # Set up response handler
           response_topic = (
               f"cmd/{device.device_info.device_type}/"
               f"{mqtt.config.client_id}/res/rsv/rd"
           )

           response_received = asyncio.Event()

           def on_response(topic: str, message: dict[str, Any]) -> None:
               response = message.get("response", {})
               use = response.get("reservationUse", 0)
               entries = response.get("reservation", [])

               print(f"\nReservation System: "
                     f"{'Enabled' if use == 1 else 'Disabled'}")
               print(f"Active entries: {len(entries)}\n")

               for idx, entry in enumerate(entries, 1):
                   days = decode_week_bitfield(
                       entry["week"]
                   )
                   # Convert from half-degrees Celsius to Fahrenheit
                   temp_f = (entry['param'] / 2.0) * 9/5 + 32
                   print(f"Entry {idx}: {entry['hour']:02d}:"
                         f"{entry['min']:02d} - Mode {entry['mode']} - "
                         f"{temp_f:.1f}°F - "
                         f"{', '.join(days)}")

               response_received.set()

           await mqtt.subscribe(response_topic, on_response)

           # Send new schedule
           print("\nUpdating reservation schedule...")
           await mqtt.update_reservations(
               device,
               reservations,
               enabled=True
           )
           print("Update sent")

           # Request confirmation
           print("\nRequesting current schedule...")
           await mqtt.request_reservations(device)

           # Wait for response
           try:
               await asyncio.wait_for(
                   response_received.wait(),
                   timeout=10.0
               )
           except asyncio.TimeoutError:
               print("Warning: No response received within 10 seconds")

           await mqtt.disconnect()
           print("\nDone")


   if __name__ == "__main__":
       try:
           asyncio.run(main())
       except KeyboardInterrupt:
           print("\nCancelled")

See Also
========

* :doc:`/guides/time_of_use` - Time-of-Use pricing optimization
* :doc:`/python_api/mqtt_client` - MQTT client API reference
* :doc:`/protocol/mqtt_protocol` - MQTT protocol details
* :doc:`/python_api/api_client` - API client reference (includes
  ``build_reservation_entry()``)
