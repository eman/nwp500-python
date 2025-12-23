======================
Command Line Interface
======================

The ``nwp500`` CLI provides a command-line interface for monitoring and
controlling Navien NWP500 water heaters without writing Python code.

.. code-block:: bash

   # Python module
   python3 -m nwp500.cli [global-options] <command> [command-options]

   # Or if installed
   nwp-cli [global-options] <command> [command-options]

Overview
========

The CLI supports:

* **Real-time monitoring** - Continuous device status updates (logs to CSV)
* **Device control** - Power, mode, temperature, vacation mode
* **Device information** - Status, firmware, features, serial number
* **Instant hot water** - Trigger hot button for immediate hot water
* **Energy management** - Historical usage data, demand response, TOU settings
* **Scheduling** - Reservations and time-of-use configuration
* **Maintenance** - Air filter reset, recirculation control, water program mode

Authentication
==============

The CLI supports multiple authentication methods:

Environment Variables (Recommended)
------------------------------------

.. code-block:: bash

   export NAVIEN_EMAIL="your@email.com"
   export NAVIEN_PASSWORD="your_password"

   python3 -m nwp500.cli status

Command Line Arguments
----------------------

.. code-block:: bash

   python3 -m nwp500.cli \
       --email "your@email.com" \
       --password "your_password" \
       status

Token Caching
-------------

The CLI automatically caches authentication tokens in ``~/.navien_tokens.json``
to avoid repeated sign-ins. Tokens are refreshed automatically when expired.

Global Options
==============

.. option:: --email EMAIL

   Navien account email. Overrides ``NAVIEN_EMAIL`` environment variable.

.. option:: --password PASSWORD

   Navien account password. Overrides ``NAVIEN_PASSWORD`` environment variable.

.. option:: --version

   Show version information and exit.

.. option:: -v, --verbose

   Enable verbose logging output (log level: INFO).

.. option:: -vv, --very-verbose

   Enable very verbose logging output (log level: DEBUG).

Commands
========

Status & Information Commands
-----------------------------

status
^^^^^^

Get current device status (one-time query).

.. code-block:: bash

   python3 -m nwp500.cli status

**Output:** Device status including water temperature, target temperature, mode,
power consumption, tank charge percentage, and component states.

**Example:**

.. code-block:: json

   {
     "dhwTemperature": 138.5,
     "dhwTargetTemp": 140,
     "dhwChargePer": 85,
     "currentInstPower": 1250,
     "operationMode": "energy-saver",
     "compressorStatus": 1,
     "heatPumpStatus": 1,
     "upperHeaterStatus": 0,
     "lowerHeaterStatus": 0
   }

info
^^^^

Show comprehensive device information (firmware, model, capabilities, serial).

.. code-block:: bash

   python3 -m nwp500.cli info

**Output:** Device name, MAC address, firmware versions, features supported,
temperature ranges, and capabilities.

serial
^^^^^^

Get controller serial number (useful for troubleshooting and TOU configuration).

.. code-block:: bash

   python3 -m nwp500.cli serial

**Output:** Controller serial number (plain text).

**Example:**

.. code-block:: text

   NV123ABC456789

Power Control Commands
----------------------

power
^^^^^

Turn device on or off.

.. code-block:: bash

   # Turn on
   python3 -m nwp500.cli power on

   # Turn off
   python3 -m nwp500.cli power off

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli power <on|off>

**Output:** Confirmation message and updated device status.

Temperature & Mode Commands
----------------------------

mode
^^^^

Set operation mode.

.. code-block:: bash

   # Heat Pump Only (most efficient)
   python3 -m nwp500.cli mode heat-pump

   # Electric Only (fastest recovery)
   python3 -m nwp500.cli mode electric

   # Energy Saver (recommended, balanced)
   python3 -m nwp500.cli mode energy-saver

   # High Demand (maximum capacity)
   python3 -m nwp500.cli mode high-demand

   # Vacation Mode
   python3 -m nwp500.cli mode vacation

   # Standby
   python3 -m nwp500.cli mode standby

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli mode <mode>

**Available Modes:**

* ``standby`` - Device off but ready
* ``heat-pump`` - Heat pump only (0)
* ``electric`` - Electric heating only (2)
* ``energy-saver`` - Hybrid/balanced mode (3) **recommended**
* ``high-demand`` - Maximum heating capacity (4)
* ``vacation`` - Extended vacancy mode (5)

**Output:** Confirmation message and updated device status.

temp
^^^^

Set target DHW (Domestic Hot Water) temperature.

.. code-block:: bash

   # Set to 140°F
   python3 -m nwp500.cli temp 140

   # Set to 130°F
   python3 -m nwp500.cli temp 130

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli temp <temperature>

**Notes:**

* Temperature specified in Fahrenheit (typically 115-150°F)
* Check device capabilities with ``info`` command for valid range
* CLI automatically converts to device message format

**Output:** Confirmation message and updated device status.

Vacation & Maintenance Commands
--------------------------------

vacation
^^^^^^^^

Enable vacation mode for N days (reduces water heating to minimize energy use).

.. code-block:: bash

   # Set vacation for 7 days
   python3 -m nwp500.cli vacation 7

   # Set vacation for 30 days
   python3 -m nwp500.cli vacation 30

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli vacation <days>

**Output:** Confirmation message and updated device status.

hot-button
^^^^^^^^^^

Trigger hot button for instant hot water (recirculation pump).

.. code-block:: bash

   python3 -m nwp500.cli hot-button

**Output:** Confirmation message.

recirc
^^^^^^

Set recirculation pump mode.

.. code-block:: bash

   # Always on
   python3 -m nwp500.cli recirc 1

   # Button triggered
   python3 -m nwp500.cli recirc 2

   # Scheduled
   python3 -m nwp500.cli recirc 3

   # Temperature triggered
   python3 -m nwp500.cli recirc 4

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli recirc <mode>

**Available Modes:**

* ``1`` - ALWAYS (always running)
* ``2`` - BUTTON (manual trigger only)
* ``3`` - SCHEDULE (based on schedule)
* ``4`` - TEMPERATURE (based on temperature)

**Output:** Confirmation message and updated device status.

reset-filter
^^^^^^^^^^^^

Reset air filter maintenance timer.

.. code-block:: bash

   python3 -m nwp500.cli reset-filter

**Output:** Confirmation message.

water-program
^^^^^^^^^^^^^^

Enable water program reservation scheduling mode.

.. code-block:: bash

   python3 -m nwp500.cli water-program

**Output:** Confirmation message.

Scheduling Commands
-------------------

reservations
^^^^^^^^^^^^

View and update reservation schedule.

.. code-block:: bash

   # Get current reservations
   python3 -m nwp500.cli reservations get

   # Set reservations from JSON
   python3 -m nwp500.cli reservations set '[{"hour": 6, "min": 0, ...}]'

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli reservations get
   python3 -m nwp500.cli reservations set <json> [--disabled]

**Options:**

.. option:: --disabled

   Create reservation in disabled state.

**Output (get):** Current reservation schedule configuration.

**Example Output:**

.. code-block:: json

   {
     "reservationUse": 1,
     "reservationEnabled": true,
     "reservations": [
       {
         "number": 1,
         "enabled": true,
         "days": [1, 1, 1, 1, 1, 0, 0],
         "time": "06:00",
         "mode": 3,
         "temperatureF": 140
       }
     ]
   }

Energy & Utility Commands
--------------------------

energy
^^^^^^

Query historical energy usage data by month.

.. code-block:: bash

   # Get October 2024
   python3 -m nwp500.cli energy --year 2024 --months 10

   # Get multiple months
   python3 -m nwp500.cli energy --year 2024 --months 8,9,10

   # Get full year
   python3 -m nwp500.cli energy --year 2024 --months 1,2,3,4,5,6,7,8,9,10,11,12

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli energy --year <year> --months <month-list>

**Options:**

.. option:: --year YEAR

   Year to query (e.g., 2024). **Required.**

.. option:: --months MONTHS

   Comma-separated list of months (1-12). **Required.**

**Output:** Energy usage breakdown by heat pump vs. electric heating.

**Example Output:**

.. code-block:: json

   {
     "total_wh": 1234567,
     "heat_pump_wh": 932098,
     "heat_pump_hours": 245,
     "electric_wh": 302469,
     "electric_hours": 67,
     "by_day": [...]
   }

tou
^^^

Configure time-of-use (TOU) pricing schedule.

.. code-block:: bash

   # Get current TOU configuration
   python3 -m nwp500.cli tou get

   # Enable TOU optimization
   python3 -m nwp500.cli tou set on

   # Disable TOU optimization
   python3 -m nwp500.cli tou set off

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli tou get
   python3 -m nwp500.cli tou set <on|off>

**Output (get):** Utility name, schedule name, ZIP code, and pricing intervals.

**Output (set):** Confirmation message and updated device status.

dr
^^

Enable or disable utility demand response.

.. code-block:: bash

   # Enable demand response
   python3 -m nwp500.cli dr enable

   # Disable demand response
   python3 -m nwp500.cli dr disable

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli dr <enable|disable>

**Output:** Confirmation message and updated device status.

Monitoring Commands
-------------------

monitor
^^^^^^^

Monitor device status in real-time and log to CSV file.

.. code-block:: bash

   # Monitor with default output file (nwp500_status.csv)
   python3 -m nwp500.cli monitor

   # Monitor with custom output file
   python3 -m nwp500.cli monitor -o my_data.csv

   # Monitor with verbose logging
   python3 -m nwp500.cli -v monitor

**Syntax:**

.. code-block:: bash

   python3 -m nwp500.cli monitor [-o OUTPUT_FILE]

**Options:**

.. option:: -o OUTPUT_FILE, --output OUTPUT_FILE

   Output CSV filename (default: ``nwp500_status.csv``).

**Output:** CSV file with timestamp, temperature, mode, power, and other metrics.

**Example CSV:**

.. code-block:: text

   timestamp,water_temp,target_temp,mode,power_w,tank_charge_pct
   2024-12-23 12:34:56,138.5,140,energy-saver,1250,85
   2024-12-23 12:35:26,138.7,140,energy-saver,1240,85
   2024-12-23 12:35:56,138.9,140,energy-saver,1230,86

Complete Examples
=================

Example 1: Check Status
-----------------------

.. code-block:: bash

   export NAVIEN_EMAIL="your@email.com"
   export NAVIEN_PASSWORD="your_password"

   python3 -m nwp500.cli status

Example 2: Change Mode and Verify
----------------------------------

.. code-block:: bash

   python3 -m nwp500.cli mode energy-saver

Example 3: Morning Boost Script
--------------------------------

.. code-block:: bash

   #!/bin/bash
   # Boost temperature in the morning

   python3 -m nwp500.cli mode high-demand
   python3 -m nwp500.cli temp 150

Example 4: Get Last 3 Months Energy
------------------------------------

.. code-block:: bash

   #!/bin/bash
   YEAR=$(date +%Y)
   MONTH=$(date +%-m)
   PREV1=$((MONTH - 1))
   PREV2=$((MONTH - 2))

   python3 -m nwp500.cli energy --year $YEAR --months "$PREV2,$PREV1,$MONTH"

Example 5: Vacation Setup
---------------------------

.. code-block:: bash

   #!/bin/bash
   # Set vacation mode for 14 days

   python3 -m nwp500.cli vacation 14

Example 6: Continuous Monitoring
---------------------------------

.. code-block:: bash

   #!/bin/bash
   # Monitor with custom output file

   python3 -m nwp500.cli monitor -o ~/navien_logs/daily_$(date +%Y%m%d).csv

Example 7: Cron Job for Daily Status
-------------------------------------

.. code-block:: bash

   # Add to crontab: crontab -e
   # Run daily at 6 AM
   0 6 * * * /usr/bin/python3 -m nwp500.cli status >> /var/log/navien_daily.log 2>&1

Example 8: Smart Scheduling with Reservations
-----------------------------------------------

.. code-block:: bash

   #!/bin/bash
   # Set reservation schedule: 6 AM - 10 PM at 140°F on weekdays

   python3 -m nwp500.cli reservations set \
     '[{"hour": 6, "min": 0, "mode": 3, "temp": 140, "days": [1,1,1,1,1,0,0]}]'

Troubleshooting
===============

Authentication Errors
---------------------

.. code-block:: bash

   # Check if credentials are set
   echo $NAVIEN_EMAIL
   echo $NAVIEN_PASSWORD

   # Try with explicit credentials
   python3 -m nwp500.cli \
       --email "your@email.com" \
       --password "your_password" \
       status

   # Clear cached tokens
   rm ~/.navien_tokens.json

Connection Issues
-----------------

.. code-block:: bash

   # Enable verbose debug logging
   python3 -m nwp500.cli -vv status

   # Check network connectivity
   ping api.navienlink.com

No Devices Found
----------------

.. code-block:: bash

   # Verify account has devices registered
   python3 -m nwp500.cli info

   # If no output, check Navienlink app for registered devices

Command Not Found
-----------------

.. code-block:: bash

   # Use full Python module path
   python3 -m nwp500.cli --help

   # Or install package in development mode
   pip install -e .

Best Practices
==============

1. **Use environment variables for credentials:**

   .. code-block:: bash

      # In ~/.bashrc or ~/.zshrc
      export NAVIEN_EMAIL="your@email.com"
      export NAVIEN_PASSWORD="your_password"

2. **Create shell aliases:**

   .. code-block:: bash

      # In ~/.bashrc or ~/.zshrc
      alias navien='python3 -m nwp500.cli'
      alias navien-status='navien status'
      alias navien-monitor='navien monitor'

3. **Use scripts for common operations:**

   .. code-block:: bash

      # morning_boost.sh
      #!/bin/bash
      python3 -m nwp500.cli mode high-demand
      python3 -m nwp500.cli temp 150

      # evening_saver.sh
      #!/bin/bash
      python3 -m nwp500.cli mode heat-pump
      python3 -m nwp500.cli temp 120

4. **Log output for analysis:**

   .. code-block:: bash

      # Append to log with timestamp
      python3 -m nwp500.cli status >> ~/navien_$(date +%Y%m%d).log

5. **Use cron for automation:**

   .. code-block:: bash

      # Morning boost: 6 AM
      0 6 * * * python3 -m nwp500.cli mode high-demand

      # Night economy: 10 PM
      0 22 * * * python3 -m nwp500.cli mode heat-pump

      # Daily status: 6 PM
      0 18 * * * python3 -m nwp500.cli status >> ~/navien_log.txt

Related Documentation
=====================

* :doc:`auth_client` - Python authentication API
* :doc:`api_client` - Python REST API
* :doc:`mqtt_client` - Python MQTT API
* :doc:`../guides/mqtt_basics` - MQTT protocol guide
