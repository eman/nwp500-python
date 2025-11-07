======================
Command Line Interface
======================

The ``nwp500`` CLI provides a command-line interface for monitoring and
controlling Navien water heaters without writing Python code.

.. code-block:: bash

   # Python module
   python3 -m nwp500.cli [options]

   # Or if installed
   navien-cli [options]

Overview
========

The CLI supports:

* **Real-time monitoring** - Continuous device status updates
* **Device status** - One-time status queries
* **Power control** - Turn device on/off
* **Mode control** - Change operation mode (Heat Pump, Electric, etc.)
* **Temperature control** - Set target temperature
* **Energy queries** - Get historical energy usage
* **Reservations** - View and update schedule
* **Time-of-Use** - Configure TOU settings
* **Device information** - Firmware, features, capabilities

Authentication
==============

The CLI supports multiple authentication methods:

Environment Variables (Recommended)
------------------------------------

.. code-block:: bash

   export NAVIEN_EMAIL="your@email.com"
   export NAVIEN_PASSWORD="your_password"

   python3 -m nwp500.cli --status

Command Line Arguments
----------------------

.. code-block:: bash

   python3 -m nwp500.cli \
       --email "your@email.com" \
       --password "your_password" \
       --status

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

   Enable debug logging output.

Commands
========

Monitoring Commands
-------------------

monitor (default)
^^^^^^^^^^^^^^^^^

Real-time continuous monitoring of device status.

.. code-block:: bash

   # Monitor with JSON output (default)
   python3 -m nwp500.cli

   # Monitor with formatted text output
   python3 -m nwp500.cli --output text

   # Monitor with compact output
   python3 -m nwp500.cli --output compact

**Options:**

.. option:: --output FORMAT

   Output format: ``json``, ``text``, or ``compact`` (default: ``json``)

**Example Output (text format):**

.. code-block:: text

   [12:34:56] Navien Water Heater Status
   ═══════════════════════════════════════
   Temperature:      138.0°F (Target: 140.0°F)
   Power:            1250W
   Mode:             ENERGY_SAVER
   State:            HEAT_PUMP
   Energy:           85.5%
   
   Components:
   ENABLED: Heat Pump Running
   DISABLED: Upper Heater
   DISABLED: Lower Heater
   
   [12:35:01] Temperature changed: 139.0°F

--status
^^^^^^^^

Get current device status (one-time query).

.. code-block:: bash

   python3 -m nwp500.cli --status

**Output:** Complete device status with temperatures, power, mode, and
component states.

--status-raw
^^^^^^^^^^^^

Get raw device status without conversions.

.. code-block:: bash

   python3 -m nwp500.cli --status-raw

**Output:** Raw JSON status data as received from device (no temperature
conversions or formatting).

Device Information Commands
---------------------------

--device-info
^^^^^^^^^^^^^

Get comprehensive device information.

.. code-block:: bash

   python3 -m nwp500.cli --device-info

**Output:** Device name, MAC address, connection status, firmware versions,
and location.

--device-feature
^^^^^^^^^^^^^^^^

Get device features and capabilities.

.. code-block:: bash

   python3 -m nwp500.cli --device-feature

**Output:** Supported features, temperature limits, firmware versions, serial
number.

**Example Output:**

.. code-block:: text

   Device Features:
     Serial Number: ABC123456789
     Controller FW: 184614912
     WiFi FW: 34013184
     
     Temperature Range: 100°F - 150°F
     
     Supported Features:
       ENABLED: Energy Monitoring
       ENABLED: Anti-Legionella
       ENABLED: Reservations
       ENABLED: Heat Pump Mode
       ENABLED: Electric Mode
       ENABLED: Energy Saver Mode
       ENABLED: High Demand Mode

--get-controller-serial
^^^^^^^^^^^^^^^^^^^^^^^

Get controller serial number (required for TOU commands).

.. code-block:: bash

   python3 -m nwp500.cli --get-controller-serial

**Output:** Controller serial number.

Control Commands
----------------

--power-on
^^^^^^^^^^

Turn device on.

.. code-block:: bash

   python3 -m nwp500.cli --power-on

   # Get status after power on
   python3 -m nwp500.cli --power-on --status

--power-off
^^^^^^^^^^^

Turn device off.

.. code-block:: bash

   python3 -m nwp500.cli --power-off

   # Get status after power off
   python3 -m nwp500.cli --power-off --status

--set-mode MODE
^^^^^^^^^^^^^^^

Change operation mode.

.. code-block:: bash

   # Heat Pump Only (most efficient)
   python3 -m nwp500.cli --set-mode heat-pump

   # Electric Only (fastest recovery)
   python3 -m nwp500.cli --set-mode electric

   # Energy Saver (recommended, balanced)
   python3 -m nwp500.cli --set-mode energy-saver

   # High Demand (maximum capacity)
   python3 -m nwp500.cli --set-mode high-demand

   # Vacation mode for 7 days
   python3 -m nwp500.cli --set-mode vacation --vacation-days 7

   # Get status after mode change
   python3 -m nwp500.cli --set-mode energy-saver --status

**Available Modes:**

* ``heat-pump`` - Heat pump only (1)
* ``electric`` - Electric only (2)
* ``energy-saver`` - Energy Saver/Hybrid (3) **recommended**
* ``high-demand`` - High Demand (4)
* ``vacation`` - Vacation mode (5) - requires ``--vacation-days``

**Options:**

.. option:: --vacation-days DAYS

   Number of vacation days (required when ``--set-mode vacation``).

--set-dhw-temp TEMPERATURE
^^^^^^^^^^^^^^^^^^^^^^^^^^

Set target DHW temperature.

.. code-block:: bash

   # Set to 140°F
   python3 -m nwp500.cli --set-dhw-temp 140

   # Set to 130°F and get status
   python3 -m nwp500.cli --set-dhw-temp 130 --status

.. important::
   Temperature is specified as **display value** (what you see on the device).
   The CLI automatically converts to message value (display - 20°F).

Energy Commands
---------------

--get-energy
^^^^^^^^^^^^

Query historical energy usage data.

.. code-block:: bash

   # Get current month
   python3 -m nwp500.cli --get-energy \
       --energy-year 2024 \
       --energy-months "10"

   # Get multiple months
   python3 -m nwp500.cli --get-energy \
       --energy-year 2024 \
       --energy-months "8,9,10"

   # Get full year
   python3 -m nwp500.cli --get-energy \
       --energy-year 2024 \
       --energy-months "1,2,3,4,5,6,7,8,9,10,11,12"

**Options:**

.. option:: --energy-year YEAR

   Year to query (e.g., 2024).

.. option:: --energy-months MONTHS

   Comma-separated list of months (1-12).

**Example Output:**

.. code-block:: text

   Energy Usage Report
   ═══════════════════
   
   Total Usage: 1,234,567 Wh (1,234.6 kWh)
   Heat Pump: 75.5% (932,098 Wh, 245 hours)
   Electric:  24.5% (302,469 Wh, 67 hours)
   
   Daily Breakdown - October 2024:
     Day 1:  42,345 Wh (HP: 32,100 Wh, HE: 10,245 Wh)
     Day 2:  38,921 Wh (HP: 30,450 Wh, HE: 8,471 Wh)
     Day 3:  45,678 Wh (HP: 35,200 Wh, HE: 10,478 Wh)
     ...

Reservation Commands
--------------------

--get-reservations
^^^^^^^^^^^^^^^^^^

Get current reservation schedule.

.. code-block:: bash

   python3 -m nwp500.cli --get-reservations

**Output:** Current reservation schedule configuration.

--set-reservations FILE
^^^^^^^^^^^^^^^^^^^^^^^

Update reservation schedule from JSON file.

.. code-block:: bash

   python3 -m nwp500.cli --set-reservations schedule.json \
       --reservations-enabled

**Options:**

.. option:: --reservations-enabled

   Enable reservation schedule (use ``--reservations-disabled`` to disable).

.. option:: --reservations-disabled

   Disable reservation schedule.

**JSON Format:**

.. code-block:: json

   [
       {
           "startHour": 6,
           "startMinute": 0,
           "endHour": 22,
           "endMinute": 0,
           "weekDays": [1, 1, 1, 1, 1, 0, 0],
           "temperature": 120
       },
       {
           "startHour": 8,
           "startMinute": 0,
           "endHour": 20,
           "endMinute": 0,
           "weekDays": [0, 0, 0, 0, 0, 1, 1],
           "temperature": 130
       }
   ]

Time-of-Use Commands
--------------------

--get-tou
^^^^^^^^^

Get Time-of-Use configuration (requires controller serial).

.. code-block:: bash

   # First get controller serial
   python3 -m nwp500.cli --get-controller-serial
   # Output: ABC123456789

   # Then query TOU (done automatically by CLI)
   python3 -m nwp500.cli --get-tou

**Output:** TOU utility, schedule name, ZIP code, and pricing intervals.

--set-tou-enabled STATE
^^^^^^^^^^^^^^^^^^^^^^^

Enable or disable TOU optimization.

.. code-block:: bash

   # Enable TOU
   python3 -m nwp500.cli --set-tou-enabled on

   # Disable TOU
   python3 -m nwp500.cli --set-tou-enabled off

   # Get status after change
   python3 -m nwp500.cli --set-tou-enabled on --status

Complete Examples
=================

Example 1: Quick Status Check
------------------------------

.. code-block:: bash

   #!/bin/bash
   export NAVIEN_EMAIL="your@email.com"
   export NAVIEN_PASSWORD="your_password"

   python3 -m nwp500.cli --status

Example 2: Change Mode and Verify
----------------------------------

.. code-block:: bash

   #!/bin/bash
   
   # Set to Energy Saver and check status
   python3 -m nwp500.cli \
       --set-mode energy-saver \
       --status

Example 3: Morning Boost Script
--------------------------------

.. code-block:: bash

   #!/bin/bash
   # Boost temperature in the morning
   
   python3 -m nwp500.cli \
       --set-mode high-demand \
       --set-dhw-temp 150 \
       --status
   
   echo "Morning boost activated!"

Example 4: Energy Report
-------------------------

.. code-block:: bash

   #!/bin/bash
   # Get last 3 months energy usage
   
   YEAR=$(date +%Y)
   M1=$(date +%-m)
   M2=$((M1 - 1))
   M3=$((M1 - 2))
   
   python3 -m nwp500.cli --get-energy \
       --energy-year $YEAR \
       --energy-months "$M3,$M2,$M1" \
       > energy_report.txt
   
   echo "Energy report saved to energy_report.txt"

Example 5: Vacation Mode Setup
-------------------------------

.. code-block:: bash

   #!/bin/bash
   # Set vacation mode for 14 days
   
   python3 -m nwp500.cli \
       --set-mode vacation \
       --vacation-days 14 \
       --status
   
   echo "Vacation mode set for 14 days"

Example 6: Continuous Monitoring
---------------------------------

.. code-block:: bash

   #!/bin/bash
   # Monitor device with formatted output
   
   python3 -m nwp500.cli --output text

Example 7: Cron Job for Daily Status
-------------------------------------

.. code-block:: bash

   # Add to crontab: crontab -e
   # Run daily at 6 AM
   0 6 * * * /usr/bin/python3 -m nwp500.cli --status >> /var/log/navien_daily.log 2>&1

Example 8: Temperature Alert Script
------------------------------------

.. code-block:: bash

   #!/bin/bash
   # Check temperature and alert if too low
   
   STATUS=$(python3 -m nwp500.cli --status 2>&1)
   TEMP=$(echo "$STATUS" | grep -oP 'dhwTemperature.*?\K\d+')
   
   if [ "$TEMP" -lt 120 ]; then
       echo "WARNING: Water temperature is $TEMP°F (below 120°F)"
       # Send notification, email, etc.
   fi

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
       --status

   # Clear cached tokens
   rm ~/.navien_tokens.json

Connection Issues
-----------------

.. code-block:: bash

   # Enable debug logging
   python3 -m nwp500.cli --verbose --status

No Devices Found
----------------

.. code-block:: bash

   # Verify account has devices registered
   python3 -m nwp500.cli --device-info

Command Not Found
-----------------

.. code-block:: bash

   # Use full Python module path
   python3 -m nwp500.cli --help

   # Or install package
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
      alias navien-status='navien --status'
      alias navien-monitor='navien --output text'

3. **Use scripts for common operations:**

   .. code-block:: bash

      # morning_boost.sh
      #!/bin/bash
      python3 -m nwp500.cli --set-mode high-demand --set-dhw-temp 150

      # vacation.sh
      #!/bin/bash
      python3 -m nwp500.cli --set-mode vacation --vacation-days ${1:-7}

4. **Combine commands efficiently:**

   .. code-block:: bash

      # Make change and verify in one command
      python3 -m nwp500.cli --set-mode energy-saver --status

5. **Use cron for automation:**

   .. code-block:: bash

      # Morning boost: 6 AM
      0 6 * * * python3 -m nwp500.cli --set-mode high-demand
      
      # Night economy: 10 PM
      0 22 * * * python3 -m nwp500.cli --set-mode heat-pump
      
      # Daily status report: 6 PM
      0 18 * * * python3 -m nwp500.cli --status >> ~/navien_log.txt

Related Documentation
=====================

* :doc:`auth_client` - Python authentication API
* :doc:`api_client` - Python REST API
* :doc:`mqtt_client` - Python MQTT API
* :doc:`models` - Data models
