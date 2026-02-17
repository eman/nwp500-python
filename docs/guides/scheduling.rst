=======================
Scheduling & Automation
=======================

The NWP500 supports four independent scheduling systems that work
together to manage water heating. This guide covers all of them:
reservations, time of use (TOU), vacation mode, and anti-legionella.

.. contents:: On This Page
   :local:
   :depth: 2

Overview
========

.. list-table:: Scheduling System Comparison
   :header-rows: 1
   :widths: 20 20 20 20 20

   * - System
     - Trigger Type
     - Scope
     - Priority
     - Override Behavior
   * - Reservations
     - Time-based (daily/weekly)
     - Mode/Temperature changes
     - Medium
     - TOU and Vacation suspend reservations
   * - TOU
     - Time + Price periods
     - Heating behavior optimization
     - Low-Medium
     - Vacation suspends TOU; Reservations override
   * - Vacation
     - Duration-based
     - Complete suspension with maintenance ops
     - Highest (blocks heating)
     - Overrides all; only anti-legionella and
       freeze protection run
   * - Anti-Legionella
     - Periodic cycle
     - Temperature boost
     - Highest (mandatory maintenance)
     - Runs even during vacation;
       interrupts other modes

All scheduling data is stored on the device and executes locally,
so schedules continue to work even if the internet connection is lost.

Reservations
============

Reservations (also called "scheduled programs") automatically change
your water heater's operating mode and temperature at specific times.

Quick Example
-------------

.. code-block:: python

   import asyncio
   from nwp500 import (
       NavienAuthClient,
       NavienAPIClient,
       NavienMqttClient,
       build_reservation_entry,
   )

   async def main():
       async with NavienAuthClient(
           "email@example.com", "password"
       ) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           entry = build_reservation_entry(
               enabled=True,
               days=["Monday", "Tuesday", "Wednesday",
                     "Thursday", "Friday"],
               hour=6,
               minute=30,
               mode_id=4,         # High Demand
               temperature=60.0   # In user's preferred unit
           )

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()
           await mqtt.control.update_reservations(
               device, [entry], enabled=True
           )
           await mqtt.disconnect()

   asyncio.run(main())

CLI Usage
---------

View current schedule:

.. code-block:: bash

   # Table format (default)
   nwp-cli reservations get

   # JSON format
   nwp-cli reservations get --json

Add a reservation:

.. code-block:: bash

   nwp-cli reservations add \
     --days "MO,TU,WE,TH,FR" \
     --hour 6 --minute 30 \
     --mode 4 --temp 60

Delete a reservation by index (1-based):

.. code-block:: bash

   nwp-cli reservations delete 2

Update a reservation (partial — only specified fields change):

.. code-block:: bash

   # Change temperature only
   nwp-cli reservations update 1 --temp 55

   # Change days and time
   nwp-cli reservations update 1 --days "SA,SU" --hour 8 --minute 0

   # Disable without deleting
   nwp-cli reservations update 1 --disable

Set an entire schedule from JSON:

.. code-block:: bash

   nwp-cli reservations set \
     '[{"hour": 6, "min": 0, "mode": 3, "temp": 60,
        "days": ["MO","TU","WE","TH","FR"]}]'

.. note::

   The ``--days`` option accepts 2-letter abbreviations
   (``MO``, ``TU``, ``WE``, ``TH``, ``FR``, ``SA``, ``SU``),
   full day names (``Monday``, ``Tuesday``, …), or a mix of both.

   Temperatures always use the device's configured unit system.
   The CLI auto-detects whether the device is set to Celsius or
   Fahrenheit.

Pydantic Models
---------------

The library provides ``ReservationEntry`` and ``ReservationSchedule``
models for type-safe reservation handling.

**ReservationEntry** — A single reservation slot:

.. code-block:: python

   from nwp500 import ReservationEntry

   entry = ReservationEntry(
       enable=2, week=62, hour=6, min=30, mode=4, param=120
   )
   entry.enabled       # True
   entry.days          # ['Tue', 'Wed', 'Thu', 'Fri', 'Sat']
   entry.time          # '06:30'
   entry.temperature   # 60.0 (in preferred unit)
   entry.unit          # '°C' or '°F'
   entry.mode_name     # 'High Demand'

**ReservationSchedule** — The full schedule (auto-decodes hex):

.. code-block:: python

   from nwp500 import ReservationSchedule

   # From a device MQTT response (hex-encoded)
   schedule = ReservationSchedule(
       reservationUse=2,
       reservation="023e061e0478"
   )
   schedule.enabled       # True
   schedule.reservation   # [ReservationEntry(...)]

   # From a list of entries
   schedule = ReservationSchedule(
       reservationUse=2,
       reservation=[
           ReservationEntry(
               enable=2, week=62, hour=6, min=30,
               mode=4, param=120
           )
       ]
   )

   # Serialize back to raw fields (for protocol use)
   for entry in schedule.reservation:
       raw = entry.model_dump(
           include={"enable", "week", "hour", "min",
                    "mode", "param"}
       )

Entry Format
------------

Each reservation entry has these fields:

``enable`` (integer)
   Uses the standard device boolean convention:

   * ``1`` — disabled (stored but won't execute)
   * ``2`` — enabled (reservation will execute)

``week`` (integer)
   Bitfield for days of the week (Monday-first):

   .. list-table::
      :header-rows: 1
      :widths: 15 15 15 15 15 15 15

      * - Mon
        - Tue
        - Wed
        - Thu
        - Fri
        - Sat
        - Sun
      * - bit 6 (64)
        - bit 5 (32)
        - bit 4 (16)
        - bit 3 (8)
        - bit 2 (4)
        - bit 1 (2)
        - bit 7 (128)

   Common values:

   * Weekdays (Mon–Fri): ``124`` (0b01111100)
   * Weekends (Sat+Sun): ``130`` (0b10000010)
   * Every day: ``254`` (0b11111110)
   * Tue–Sat: ``62`` (0b00111110)

``hour`` (integer)
   Hour in 24-hour format (0–23).

``min`` (integer)
   Minute (0–59).

``mode`` (integer)
   DHW operation mode:

   * ``1`` — Heat Pump Only
   * ``2`` — Electric Heater Only
   * ``3`` — Energy Saver (Eco)
   * ``4`` — High Demand
   * ``5`` — Vacation Mode
   * ``6`` — Power Off

``param`` (integer)
   Target temperature in **half-degrees Celsius**:

   * Formula: ``celsius = param / 2.0``
   * Examples: 70 → 35 °C (95 °F), 120 → 60 °C (140 °F)
   * Valid range: 35 °C to 65.5 °C (95 °F to 150 °F)

   When using ``build_reservation_entry()``, pass the temperature in
   the user's preferred unit and the conversion is automatic.

Helper Functions
----------------

**build_reservation_entry()** — Create a properly formatted entry:

.. code-block:: python

   from nwp500 import build_reservation_entry

   entry = build_reservation_entry(
       enabled=True,
       days=["Monday", "Tuesday", "Wednesday",
             "Thursday", "Friday"],
       hour=6,
       minute=30,
       mode_id=4,
       temperature=60.0   # In user's preferred unit
   )
   # {'enable': 2, 'week': 124, 'hour': 6, 'min': 30,
   #  'mode': 4, 'param': 120}

The ``days`` parameter accepts:

* Full names: ``"Monday"``, ``"Tuesday"``, …
* 2-letter abbreviations: ``"MO"``, ``"TU"``, ``"WE"``, ``"TH"``,
  ``"FR"``, ``"SA"``, ``"SU"``
* Integer indices: ``0`` (Monday) through ``6`` (Sunday)
* Any mix of the above

**encode_week_bitfield()** / **decode_week_bitfield()**:

.. code-block:: python

   from nwp500.encoding import (
       encode_week_bitfield,
       decode_week_bitfield,
   )

   encode_week_bitfield(["MO", "TU", "WE", "TH", "FR"])
   # 124

   encode_week_bitfield([5, 6])   # Saturday + Sunday
   # 130

   decode_week_bitfield(62)
   # ['Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

Managing Reservations
---------------------

**Important:** The device protocol requires sending the **full list**
of reservations for every update. Individual add/delete/update
operations work by fetching the current schedule, modifying it, and
sending the full list back.

Low-Level Method (``NavienMqttClient``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``update_reservations()`` when you need full control or are managing
multiple entries at once:

.. code-block:: python

   from nwp500.mqtt import NavienMqttClient
   from nwp500.encoding import build_reservation_entry

   reservations = [
       build_reservation_entry(
           enabled=True,
           days=["MO", "TU", "WE", "TH", "FR"],
           hour=6, minute=30,
           mode_id=4, temperature=60.0
       ),
       build_reservation_entry(
           enabled=True,
           days=["SA", "SU"],
           hour=8, minute=0,
           mode_id=3, temperature=55.0
       ),
   ]
   await mqtt.control.update_reservations(
       device, reservations, enabled=True
   )

**Disable reservations** (entries are preserved on the device):

.. code-block:: python

   await mqtt.control.update_reservations(
       device, [], enabled=False
   )

**Request current schedule:**

.. code-block:: python

   await mqtt.control.request_reservations(device)

**Read the current schedule using models:**

.. code-block:: python

   from nwp500 import ReservationSchedule

   # Subscribe to responses
   def on_reservations(schedule: ReservationSchedule) -> None:
       print(f"Enabled: {schedule.enabled}")
       for entry in schedule.reservation:
           print(f"  {entry.time} - {', '.join(entry.days)}"
                 f" - {entry.temperature}{entry.unit}"
                 f" - {entry.mode_name}")

   await mqtt.subscribe_device_feature(
       device, on_reservations, path="reservations"
   )
   await mqtt.control.request_reservations(device)

CLI Helpers
^^^^^^^^^^^

The CLI provides convenience commands:

**List current reservations:**

.. code-block:: bash

   nwp-cli reservations get      # Formatted table
   nwp-cli reservations get --json  # JSON output

**Add a single reservation:**

.. code-block:: bash

   nwp-cli reservations add --days MO,TU,WE,TH,FR \
     --hour 6 --minute 30 --mode 4 --temperature 60

**Update an existing reservation:**

.. code-block:: bash

   nwp-cli reservations update --mode 3 --temperature 58 1

**Delete a reservation:**

.. code-block:: bash

   nwp-cli reservations delete 1

Library Helpers
^^^^^^^^^^^^^^^^

The library provides convenience functions that abstract the
read-modify-write pattern for individual reservation entries.

**fetch_reservations()** — Retrieve the current schedule:

.. code-block:: python

   from nwp500 import fetch_reservations

   schedule = await fetch_reservations(mqtt, device)
   if schedule is not None:
       print(f"Schedule enabled: {schedule.enabled}")
       for entry in schedule.reservation:
           print(f"  {entry.time} {', '.join(entry.days)}"
                 f" — {entry.temperature}{entry.unit}"
                 f" — {entry.mode_name}")

**add_reservation()** — Append a new entry to the schedule:

.. code-block:: python

   from nwp500 import add_reservation

   await add_reservation(
       mqtt, device,
       enabled=True,
       days=["MO", "TU", "WE", "TH", "FR"],
       hour=6,
       minute=30,
       mode=4,           # High Demand
       temperature=60.0, # In user's preferred unit
   )

**delete_reservation()** — Remove an entry by 1-based index:

.. code-block:: python

   from nwp500 import delete_reservation

   await delete_reservation(mqtt, device, index=2)

**update_reservation()** — Modify specific fields of an existing entry.
Only the keyword arguments you supply are changed; all others are kept:

.. code-block:: python

   from nwp500 import update_reservation

   # Change temperature only
   await update_reservation(mqtt, device, 1, temperature=55.0)

   # Change days and time
   await update_reservation(mqtt, device, 1, days=["SA", "SU"], hour=8, minute=0)

   # Disable without deleting
   await update_reservation(mqtt, device, 1, enabled=False)

These helpers raise :class:`ValueError` for out-of-range arguments,
:class:`~nwp500.exceptions.RangeValidationError` or
:class:`~nwp500.exceptions.ValidationError` for device-protocol
violations, and :class:`TimeoutError` if the device does not respond.


Mode Selection Strategy
-----------------------

Choose the right mode for each time period:

* **Heat Pump (1)** — Lowest cost, slowest recovery. Best for
  off-peak or overnight.
* **Energy Saver (3)** — Balanced hybrid mode. Good for all-day use.
* **High Demand (4)** — Fast recovery, higher cost. Use for scheduled
  peak demand (e.g., morning showers).
* **Electric (2)** — Emergency only. Very high cost, fastest recovery.
  72-hour operation limit.

Common Patterns
---------------

**Weekday vs. weekend:**

.. code-block:: python

   reservations = [
       build_reservation_entry(
           enabled=True,
           days=[0, 1, 2, 3, 4],   # Mon-Fri
           hour=5, minute=30,
           mode_id=4, temperature=60.0
       ),
       build_reservation_entry(
           enabled=True,
           days=[5, 6],             # Sat, Sun
           hour=8, minute=0,
           mode_id=3, temperature=55.0
       ),
   ]

**Energy optimization (4-period weekday):**

.. code-block:: python

   reservations = [
       # 6 AM: High Demand for morning showers
       build_reservation_entry(
           enabled=True, days=["MO","TU","WE","TH","FR"],
           hour=6, minute=0, mode_id=4, temperature=60.0
       ),
       # 9 AM: Switch to Energy Saver
       build_reservation_entry(
           enabled=True, days=["MO","TU","WE","TH","FR"],
           hour=9, minute=0, mode_id=3, temperature=50.0
       ),
       # 5 PM: Heat Pump before peak pricing
       build_reservation_entry(
           enabled=True, days=["MO","TU","WE","TH","FR"],
           hour=17, minute=0, mode_id=1, temperature=55.0
       ),
       # 10 PM: Back to Energy Saver overnight
       build_reservation_entry(
           enabled=True, days=["MO","TU","WE","TH","FR"],
           hour=22, minute=0, mode_id=3, temperature=50.0
       ),
   ]

**Vacation automation:**

.. code-block:: python

   reservations = [
       # Friday 8 PM: Enter vacation mode
       build_reservation_entry(
           enabled=True, days=["FR"],
           hour=20, minute=0, mode_id=5, temperature=50.0
       ),
       # Sunday 2 PM: Return to Energy Saver
       build_reservation_entry(
           enabled=True, days=["SU"],
           hour=14, minute=0, mode_id=3, temperature=55.0
       ),
   ]

Important Notes
---------------

* The device can store up to ~16 reservation entries.
* Reservations execute at the exact minute specified; the device
  checks every minute.
* If the device is powered off, reservations will not execute.
* Reservations persist through power cycles and internet outages.
* Reservations are suspended when vacation mode or TOU is active.


Time of Use (TOU)
==================

TOU scheduling allows price-aware heating optimization based on your
utility's electricity rate structure. For the full TOU guide including
OpenEI integration, see :doc:`time_of_use`.

TOU Period Structure
--------------------

Each TOU period defines a time window with price information:

.. code-block:: python

   {
       "season": 448,        # Bitfield for months
                              # (bit 0=Jan … bit 11=Dec)
                              # 448 = Jun+Jul+Aug
       "week": 124,          # Bitfield for weekdays
                              # (same as reservations)
                              # 124 = Mon-Fri
       "startHour": 9,
       "startMinute": 0,
       "endHour": 17,
       "endMinute": 0,
       "priceMin": 10,       # Minimum price (encoded)
       "priceMax": 25,       # Maximum price (encoded)
       "decimalPoint": 2     # Decimal places
                              # (2 = price/100 for dollars)
   }

Season Bitfield
---------------

Months are encoded as a 12-bit field:

.. list-table::
   :header-rows: 1
   :widths: 8 8 8 8 8 8 8 8 8 8 8 8

   * - Jan
     - Feb
     - Mar
     - Apr
     - May
     - Jun
     - Jul
     - Aug
     - Sep
     - Oct
     - Nov
     - Dec
   * - 1
     - 2
     - 4
     - 8
     - 16
     - 32
     - 64
     - 128
     - 256
     - 512
     - 1024
     - 2048

* Summer (Jun–Aug): ``32 + 64 + 128 = 224``
* Winter (Dec–Feb): ``1 + 2 + 2048 = 2051``
* Year-round: ``4095``

How TOU Works
-------------

1. Device receives time periods with price ranges.
2. **Low-price periods**: Device uses heat pump only.
3. **High-price periods**: Device reduces heating or switches to
   lower-efficiency mode.
4. **Peak periods**: Device may pre-charge the tank before peak to
   minimize peak-time heating.

The device supports up to 16 TOU periods. Typical setups:

* **Simple**: 3–4 periods (off-peak, shoulder, on-peak)
* **Moderate**: 6–8 periods (split by season and weekday/weekend)
* **Complex**: 12–16 periods (full seasonal tariff)

Example: Summer 3-Period Schedule
---------------------------------

.. code-block:: python

   # Off-peak: 9 PM – 9 AM weekdays
   off_peak = {
       "season": 224, "week": 31,
       "startHour": 21, "startMinute": 0,
       "endHour": 9, "endMinute": 0,
       "priceMin": 8, "priceMax": 10, "decimalPoint": 2
   }

   # Shoulder: 9 AM – 2 PM weekdays
   shoulder = {
       "season": 224, "week": 31,
       "startHour": 9, "startMinute": 0,
       "endHour": 14, "endMinute": 0,
       "priceMin": 12, "priceMax": 18, "decimalPoint": 2
   }

   # Peak: 2 PM – 9 PM weekdays
   peak = {
       "season": 224, "week": 31,
       "startHour": 14, "startMinute": 0,
       "endHour": 21, "endMinute": 0,
       "priceMin": 20, "priceMax": 35, "decimalPoint": 2
   }


Vacation Mode
=============

Vacation mode suspends heating for up to 99 days while maintaining
critical functions.

Behavior
--------

When vacation mode is active:

1. **Heating suspended** — no heat pump or electric heating cycles.
2. **Freeze protection** — still active. If temperature drops below
   43 °F (6 °C), electric heating activates briefly.
3. **Anti-legionella** — still runs on schedule.
4. **Automatic resumption** — heating resumes 9 hours before the
   vacation end date.
5. **Other schedules suspended** — reservations and TOU are paused.

Duration: 0–99 days (0 = disabled, resumes immediately).

When to Use
-----------

**Recommended for:**

* Extended absences (week-long trips or longer)
* Seasonal properties
* Emergency shutdown
* Long maintenance periods

**Not recommended for:**

* Weekend trips — use reservations instead
* Work-day absences — use Energy Saver + TOU
* Daily night-time suspension — use reservations with Heat Pump mode


Anti-Legionella
===============

Anti-legionella periodically heats water to 70 °C (158 °F) for
disinfection. This is a mandatory safety feature that runs even during
vacation mode.

CLI Usage
---------

.. code-block:: bash

   # Enable with a 14-day cycle
   nwp-cli anti-legionella enable --period 14

   # Disable
   nwp-cli anti-legionella disable

   # Check current status
   nwp-cli anti-legionella status

Period Configuration
--------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Period (days)
     - Use Case
   * - 1–3
     - High-contamination risk environments
   * - 7
     - High-risk installations or hard-water areas
   * - 14
     - Standard residential (default)
   * - 30
     - Commercial buildings with annual testing
   * - 90
     - Well-maintained commercial systems with water treatment

Risk Factors
------------

Anti-legionella is especially important when:

* Hard water areas (mineral deposits harbor bacteria)
* Systems left unused for days (stagnant water)
* Warm climates (25–45 °C ideal for legionella growth)
* Recirculation systems (warm water sitting in pipes)


See Also
========

* :doc:`time_of_use` — Full TOU guide with OpenEI integration
* :doc:`../python_api/device_control` — Device control API reference
* :doc:`../python_api/mqtt_client` — MQTT client API reference
* :doc:`../protocol/data_conversions` — Temperature and power field
  conversions
* :doc:`auto_recovery` — Handling temporary connectivity issues
