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
               param=120   # 140°F display (120 + 20)
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
   target water temperature with a **20°F offset**:
   
   * Display temperature = ``param + 20``
   * Message value = Display temperature - 20
   
   **Temperature Examples:**
   
   * 120°F display → ``param = 100``
   * 130°F display → ``param = 110``
   * 140°F display → ``param = 120``
   * 150°F display → ``param = 130``
   
   For non-temperature modes (Vacation, Power Off), the param value is
   typically ignored but should be set to a valid temperature offset
   (e.g., ``100``) for consistency.

Helper Functions
================

The library provides helper functions to make building reservations easier.

Building Reservation Entries
-----------------------------

Use ``build_reservation_entry()`` to create properly formatted entries:

.. code-block:: python

   from nwp500 import NavienAPIClient

   # Weekday morning - High Demand mode at 140°F
   entry = NavienAPIClient.build_reservation_entry(
       enabled=True,
       days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
       hour=6,
       minute=30,
       mode_id=4,  # High Demand
       param=120   # 140°F (120 + 20)
   )
   # Returns: {'enable': 1, 'week': 62, 'hour': 6, 'min': 30,
   #           'mode': 4, 'param': 120}

   # Weekend - Energy Saver mode at 120°F
   entry2 = NavienAPIClient.build_reservation_entry(
       enabled=True,
       days=["Saturday", "Sunday"],
       hour=8,
       minute=0,
       mode_id=3,  # Energy Saver
       param=100   # 120°F (100 + 20)
   )

   # You can also use day indices (0=Sunday, 6=Saturday)
   entry3 = NavienAPIClient.build_reservation_entry(
       enabled=True,
       days=[1, 2, 3, 4, 5],  # Monday-Friday
       hour=18,
       minute=0,
       mode_id=1,  # Heat Pump Only
       param=110   # 130°F (110 + 20)
   )

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
               NavienAPIClient.build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=6,
                   minute=30,
                   mode_id=4,
                   param=120
               ),
               # Weekday evening: Energy Saver at 130°F
               NavienAPIClient.build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=18,
                   minute=0,
                   mode_id=3,
                   param=110
               ),
               # Weekend: Heat Pump Only at 120°F
               NavienAPIClient.build_reservation_entry(
                   enabled=True,
                   days=["Saturday", "Sunday"],
                   hour=8,
                   minute=0,
                   mode_id=1,
                   param=100
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
                   days = NavienAPIClient.decode_week_bitfield(
                       entry.get("week", 0)
                   )
                   hour = entry.get("hour", 0)
                   minute = entry.get("min", 0)
                   mode = entry.get("mode", 0)
                   display_temp = entry.get("param", 0) + 20

                   print(f"\nEntry {idx}:")
                   print(f"  Time: {hour:02d}:{minute:02d}")
                   print(f"  Days: {', '.join(days)}")
                   print(f"  Mode: {mode}")
                   print(f"  Temp: {display_temp}°F")

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
       NavienAPIClient.build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],  # Mon-Fri
           hour=5,
           minute=30,
           mode_id=4,  # High Demand
           param=120   # 140°F
       ),
       # Weekend morning: later start, energy saver
       NavienAPIClient.build_reservation_entry(
           enabled=True,
           days=[0, 6],  # Sun, Sat
           hour=8,
           minute=0,
           mode_id=3,  # Energy Saver
           param=110   # 130°F
       ),
   ]

Energy Optimization Schedule
-----------------------------

Minimize energy use during peak hours:

.. code-block:: python

   reservations = [
       # Morning prep: 6:00 AM - High Demand for showers
       NavienAPIClient.build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=6,
           minute=0,
           mode_id=4,
           param=120
       ),
       # Day: 9:00 AM - Switch to Energy Saver
       NavienAPIClient.build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=9,
           minute=0,
           mode_id=3,
           param=100
       ),
       # Evening: 5:00 PM - Heat Pump Only (before peak pricing)
       NavienAPIClient.build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=17,
           minute=0,
           mode_id=1,
           param=110
       ),
       # Night: 10:00 PM - Back to Energy Saver
       NavienAPIClient.build_reservation_entry(
           enabled=True,
           days=[1, 2, 3, 4, 5],
           hour=22,
           minute=0,
           mode_id=3,
           param=100
       ),
   ]

Vacation Mode Automation
-------------------------

Automatically enable vacation mode during a trip:

.. code-block:: python

   # Enable vacation mode at start of trip
   start_vacation = NavienAPIClient.build_reservation_entry(
       enabled=True,
       days=["Friday"],  # Leaving Friday evening
       hour=20,
       minute=0,
       mode_id=5,  # Vacation Mode
       param=100   # Temperature doesn't matter for vacation mode
   )

   # Return to normal operation when you get back
   end_vacation = NavienAPIClient.build_reservation_entry(
       enabled=True,
       days=["Sunday"],  # Returning Sunday afternoon
       hour=14,
       minute=0,
       mode_id=3,  # Energy Saver
       param=110   # 130°F
   )

   reservations = [start_vacation, end_vacation]

Important Notes
===============

Temperature Offset
------------------

The ``param`` field uses a **20°F offset** from the display temperature:

* If you want the display to show 140°F, use ``param=120``
* If you see ``param=100`` in a response, it means 120°F display
* This offset applies to all temperature-based modes (Heat Pump, Electric,
  Energy Saver, High Demand)

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
       NavienMqttClient
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
               NavienAPIClient.build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=6,
                   minute=30,
                   mode_id=4,  # High Demand
                   param=120   # 140°F
               ),
               # Weekday day
               NavienAPIClient.build_reservation_entry(
                   enabled=True,
                   days=["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday"],
                   hour=9,
                   minute=0,
                   mode_id=3,  # Energy Saver
                   param=100   # 120°F
               ),
               # Weekend morning
               NavienAPIClient.build_reservation_entry(
                   enabled=True,
                   days=["Saturday", "Sunday"],
                   hour=8,
                   minute=0,
                   mode_id=3,  # Energy Saver
                   param=110   # 130°F
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
                   days = NavienAPIClient.decode_week_bitfield(
                       entry["week"]
                   )
                   print(f"Entry {idx}: {entry['hour']:02d}:"
                         f"{entry['min']:02d} - Mode {entry['mode']} - "
                         f"{entry['param'] + 20}°F - "
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
