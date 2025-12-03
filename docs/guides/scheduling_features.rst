Advanced Scheduling Guide
=========================

This guide documents advanced scheduling capabilities of the NWP500 and clarifies the interaction between different scheduling systems.

Current Scheduling Systems
--------------------------

The NWP500 supports four independent scheduling systems that work together:

1. **Reservations** (Scheduled Programs)
2. **Time of Use (TOU)** (Price-Based Scheduling)
3. **Vacation Mode** (Automatic Suspension)
4. **Anti-Legionella** (Periodic Maintenance)

Understanding How They Interact
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These systems operate with different priorities and interaction rules:

.. list-table::
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
     - Overrides all; only anti-legionella and freeze protection run
   * - Anti-Legionella
     - Periodic cycle
     - Temperature boost
     - Highest (mandatory maintenance)
     - Runs even during vacation; interrupts other modes

Reservations (Scheduled Programs) - Detailed Reference
------------------------------------------------------

Reservations allow you to change the device's operating mode and temperature at specific times of day.

Capabilities and Limitations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Supported**:
- Weekly patterns (Monday-Sunday, any combination)
- Multiple entries (up to ~16 entries, device-dependent)
- Two-second time precision
- Mode changes (Heat Pump, Electric, Energy Saver, High Demand)
- Temperature setpoint changes (95-150°F)
- Per-entry enable/disable

**Not Supported (Currently)**:
- Monthly patterns (e.g., "first Tuesday of month")
- Holiday calendars
- Relative times (e.g., "2 hours before sunset")
- Weather-based triggers
- Usage-based thresholds

Reservation Entry Structure
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each reservation entry controls one scheduled action:

.. code-block:: python

    {
        "enable": 1,            # 1=enabled, 2=disabled
        "week": 62,             # Bitfield: bit 0=Sunday, bit 1=Monday, etc.
                                # 62 = 0b111110 = Monday-Friday
        "hour": 6,              # 0-23 (24-hour format)
        "min": 30,              # 0-59
        "mode": 3,              # 1=Heat Pump, 2=Electric, 3=Energy Saver, 4=High Demand
        "param": 120            # Temperature in half-degrees Celsius
                                # Formula: fahrenheit = (param / 2.0) * 9/5 + 32
                                # 120 = 60°C × 2 = 140°F
    }

**Week Bitfield Encoding**:

The ``week`` field uses 7 bits for days of week:

.. code-block:: text

    Bit Position:  0      1       2       3       4      5      6
    Day:          Sun    Mon     Tue     Wed     Thu    Fri    Sat
    Bit Value:    1      2       4       8       16     32     64
    
    Examples:
    - Monday-Friday (work week):  2+4+8+16+32 = 62   (0b111110)
    - Weekends only:              1+64 = 65           (0b1000001)
    - Every day:                  127                 (0b1111111)
    - Mon/Wed/Fri only:           2+8+32 = 42         (0b101010)

**Temperature Parameter Encoding**:

The ``param`` field stores temperature in **half-degrees Celsius**:

.. code-block:: text

    Conversion: fahrenheit = (param / 2.0) * 9/5 + 32
    Inverse:    param = (fahrenheit - 32) * 5/9 * 2
    
    Temperature Examples:
    95°F → 70 (35°C × 2)
    120°F → 98 (48.9°C × 2)
    130°F → 110 (54.4°C × 2)
    140°F → 120 (60°C × 2)
    150°F → 132 (65.6°C × 2)

**Mode Selection Strategy**:

- **Heat Pump (1)**: Lowest cost, slowest recovery, best for off-peak periods or overnight
- **Energy Saver (3)**: Default hybrid mode, balanced efficiency/recovery, recommended for all-day use
- **High Demand (4)**: Faster recovery, higher cost, useful for scheduled peak demand times (e.g., morning showers)
- **Electric (2)**: Emergency only, very high cost, fastest recovery, maximum 72-hour operation limit

Example Use Cases
^^^^^^^^^^^^^^^^^

**Scenario 1: Morning Peak Demand**

Heat water to high temperature before morning showers:

.. code-block:: python

    # 6:30 AM weekdays: switch to High Demand mode at 140°F
    morning_peak = {
        "enable": 1,
        "week": 62,              # Monday-Friday
        "hour": 6,
        "min": 30,
        "mode": 4,               # High Demand
        "param": 120             # 140°F
    }

**Scenario 2: Work Hours Energy Saving**

During work hours (when nobody home), reduce heating:

.. code-block:: python

    # 9:00 AM weekdays: switch to Heat Pump only
    work_hours_eco = {
        "enable": 1,
        "week": 62,              # Monday-Friday
        "hour": 9,
        "min": 0,
        "mode": 1,               # Heat Pump (most efficient)
        "param": 100             # 120°F (lower setpoint)
    }

**Scenario 3: Evening Preparation**

Restore comfort before evening return:

.. code-block:: python

    # 5:00 PM weekdays: switch back to Energy Saver at 140°F
    evening_prep = {
        "enable": 1,
        "week": 62,              # Monday-Friday
        "hour": 17,
        "min": 0,
        "mode": 3,               # Energy Saver (balanced)
        "param": 120             # 140°F
    }

**Scenario 4: Weekend Comfort**

Maintain comfort throughout weekend:

.. code-block:: python

    # 8:00 AM weekends: switch to High Demand at 150°F
    weekend_morning = {
        "enable": 1,
        "week": 65,              # Saturday + Sunday
        "hour": 8,
        "min": 0,
        "mode": 4,               # High Demand
        "param": 130             # 150°F (maximum)
    }

Time of Use (TOU) Scheduling - Advanced Details
-----------------------------------------------

TOU scheduling is more complex than reservations, allowing price-aware heating optimization.

How TOU Works
^^^^^^^^^^^^^

1. Device receives multiple time periods, each with a price range (min/max)
2. During low-price periods: Device uses heat pump only (or less aggressive heating)
3. During high-price periods: Device reduces heating or switches to lower efficiency to save electricity
4. During peak periods: Device may pre-charge tank before peak to minimize peak-time heating

TOU Period Structure
^^^^^^^^^^^^^^^^^^^^

Each TOU period defines a time window with price information:

.. code-block:: python

    {
        "season": 448,           # Bitfield for months (bit 0=Jan, ..., bit 11=Dec)
                                 # 448 = 0b111000000 = June, July, August (summer)
        "week": 62,              # Bitfield for weekdays (same as reservations)
                                 # 62 = Monday-Friday
        "startHour": 9,          # 0-23
        "startMinute": 0,        # 0-59
        "endHour": 17,           # 0-23
        "endMinute": 0,          # 0-59
        "priceMin": 10,          # Minimum price (encoded, typically cents)
        "priceMax": 25,          # Maximum price (encoded, typically cents)
        "decimalPoint": 2        # Price decimal places (2 = price is priceMin/100)
    }

**Season Bitfield Encoding**:

Months are encoded as bits (similar to days):

.. code-block:: text

    Bit Position:  0   1   2   3   4   5   6   7   8   9   10  11
    Month:        Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec
    Bit Value:     1   2   4   8  16  32  64 128 256 512 1024 2048
    
    Examples:
    - Summer (Jun-Aug):     64+128+256 = 448      (0b111000000)
    - Winter (Dec-Feb):     1+2+2048 = 2051       (0b100000000011)
    - Year-round:           4095                  (0b111111111111)

**Price Encoding**:

Prices are encoded as integers with separate decimal point indicator:

.. code-block:: python

    # Example: Encode $0.12/kWh with decimal_point=2
    priceMin = 12              # Represents $0.12 when decimal_point=2
    
    # Example: Encode $0.125/kWh with decimal_point=3
    priceMin = 125             # Represents $0.125 when decimal_point=3

Maximum 16 TOU Periods
^^^^^^^^^^^^^^^^^^^^^^

The device supports up to 16 different price periods. Design your schedule to fit:

- **Simple**: 3-4 periods (off-peak, shoulder, on-peak)
- **Moderate**: 6-8 periods (split by season and weekday/weekend)
- **Complex**: 12-16 periods (full tariff with seasonal and weekday variations)

Example: 3-Period Summer Schedule
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Summer (Jun-Jul-Aug), 3-period schedule
    
    # Off-peak: 9 PM - 9 AM weekdays
    off_peak_summer = {
        "season": 448,           # Jun, Jul, Aug
        "week": 62,              # Mon-Fri
        "startHour": 21,         # 9 PM
        "startMinute": 0,
        "endHour": 9,            # 9 AM next day (wraps)
        "endMinute": 0,
        "priceMin": 8,           # $0.08/kWh
        "priceMax": 10,          # $0.10/kWh
        "decimalPoint": 2
    }
    
    # Shoulder: 9 AM - 2 PM weekdays
    shoulder_summer = {
        "season": 448,
        "week": 62,
        "startHour": 9,
        "startMinute": 0,
        "endHour": 14,           # 2 PM
        "endMinute": 0,
        "priceMin": 12,          # $0.12/kWh
        "priceMax": 18,          # $0.18/kWh
        "decimalPoint": 2
    }
    
    # Peak: 2 PM - 9 PM weekdays
    peak_summer = {
        "season": 448,
        "week": 62,
        "startHour": 14,         # 2 PM
        "startMinute": 0,
        "endHour": 21,           # 9 PM
        "endMinute": 0,
        "priceMin": 20,          # $0.20/kWh
        "priceMax": 35,          # $0.35/kWh
        "decimalPoint": 2
    }

Vacation Mode - Extended Use Details
------------------------------------

Vacation mode suspends heating for up to 99 days while maintaining critical functions.

Vacation Behavior
^^^^^^^^^^^^^^^^^

When vacation mode is active:

1. **Heating SUSPENDED**: No heat pump or electric heating cycles
2. **Freeze Protection**: Still active - if temperature drops below 43°F, electric heating activates briefly
3. **Anti-Legionella**: Still runs on schedule - disinfection cycles continue
4. **Automatic Resumption**: Heating automatically resumes 9 hours before vacation end date
5. **All Other Schedules**: Reservations and TOU are suspended during vacation

Vacation Duration Calculation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

    Duration:    0-99 days
    - 0 days   = Vacation mode disabled (resume heating immediately)
    - 1 day    = Heat resumes ~24 hours from now
    - 7 days   = Vacation until next week, resume ~7 days from now
    - 14 days  = Two-week vacation
    - 99 days  = Approximately 3 months (maximum)

When to Use Vacation Mode
^^^^^^^^^^^^^^^^^^^^^^^^^

- Extended absences (weeklong trips or longer)
- Seasonal properties (winterized/unopened for season)
- Emergency situations requiring complete shutdown
- Energy conservation for long maintenance periods

**NOT Recommended For**:
- Weekend trips (use reservations instead)
- Work-day absences (use Energy Saver + TOU instead)
- Daily night-time suspension (use reservations with Heat Pump mode)

Anti-Legionella Cycles - Maintenance Details
--------------------------------------------

Anti-legionella feature periodically heats water to 158°F (70°C) for disinfection.

Mandatory Operation
^^^^^^^^^^^^^^^^^^^

Anti-legionella cycles run even when:
- Vacation mode is active
- Device is in standby
- User has requested low-power operation

Period Configuration
^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Period (days)
     - Purpose
   * - 1-3 (not typical)
     - Rare: high-contamination risk environments
   * - 7
     - Standard: high-risk installations or hardwater areas
   * - 14
     - Common: residential with typical water quality
   * - 30
     - Relaxed: commercial buildings with annual testing
   * - 90
     - Minimal: well-maintained commercial systems with water treatment

Default: 14 days

Legionella Risk Factors
^^^^^^^^^^^^^^^^^^^^^^^

Anti-legionella becomes more critical in:
- Hard water areas (mineral deposits harbor bacteria)
- Systems left unused for days (stagnant water)
- Warm climates (25-45°C ideal for legionella growth)
- Recirculation systems (warm water in pipes)

See Also
--------

* :doc:`reservations` - Quick start for reservation setup
* :doc:`time_of_use` - TOU pricing details and OpenEI integration
* :doc:`../protocol/data_conversions` - Understanding temperature and power fields
* :doc:`auto_recovery` - Handling temporary connectivity issues
