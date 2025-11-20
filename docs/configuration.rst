=============
Configuration
=============

This guide covers configuring the nwp500-python library for your
environment.

Credentials
===========

The library requires your Navien Smart Control credentials (email and
password used in the Navilink mobile app).

Environment Variables (Recommended)
------------------------------------

Store credentials in environment variables for security:

**Linux/macOS:**

.. code-block:: bash

   export NAVIEN_EMAIL="your-email@example.com"
   export NAVIEN_PASSWORD="your-password"

**Windows (PowerShell):**

.. code-block:: powershell

   $env:NAVIEN_EMAIL="your-email@example.com"
   $env:NAVIEN_PASSWORD="your-password"

**Windows (Command Prompt):**

.. code-block:: bat

   set NAVIEN_EMAIL=your-email@example.com
   set NAVIEN_PASSWORD=your-password

Then in your code:

.. code-block:: python

   import os
   from nwp500 import NavienAuthClient, InvalidCredentialsError

   email = os.getenv("NAVIEN_EMAIL")
   password = os.getenv("NAVIEN_PASSWORD")

   try:
       async with NavienAuthClient(email, password) as auth:
           # ...
   except InvalidCredentialsError:
       print("Invalid email or password")
       # Check credentials

Configuration File
------------------

Create a config file (keep this private!):

.. code-block:: ini

   # config.ini
   [navien]
   email = your-email@example.com
   password = your-password

Load it in your code:

.. code-block:: python

   import configparser
   from nwp500 import NavienAuthClient

   config = configparser.ConfigParser()
   config.read('config.ini')

   email = config['navien']['email']
   password = config['navien']['password']

   async with NavienAuthClient(email, password) as auth:
       # ...

.. warning::
   Never commit configuration files with credentials to version control!
   Add ``config.ini`` to your ``.gitignore`` file.

Direct in Code (Not Recommended)
---------------------------------

Only for testing:

.. code-block:: python

   from nwp500 import NavienAuthClient

   async with NavienAuthClient(
       "your-email@example.com",
       "your-password"
   ) as auth:
       # ...

Authentication Options
======================

Timeout Settings
----------------

Configure request timeouts:

.. code-block:: python

   from nwp500 import NavienAuthClient

   # Increase timeout for slow connections
   async with NavienAuthClient(
       email,
       password,
       timeout=60  # seconds
   ) as auth:
       # ...

Custom Base URL
---------------

Use a different API endpoint (for testing or proxies):

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient

   async with NavienAuthClient(email, password) as auth:
       api = NavienAPIClient(
           auth,
           base_url="https://custom.api.url/api/v2.1"
       )

MQTT Configuration
==================

The MQTT client supports various configuration options through
``MqttConnectionConfig``.

For detailed configuration guides, see:

* :doc:`guides/auto_recovery` - Connection recovery settings
* :doc:`guides/command_queue` - Offline command queuing

Basic Example
-------------

.. code-block:: python

   from nwp500 import NavienMqttClient
   from nwp500.mqtt_utils import MqttConnectionConfig

   config = MqttConnectionConfig(
       # Connection settings
       client_id="my-custom-client",
       keep_alive_secs=1200,
       
       # Enable features (see guides for details)
       auto_reconnect=True,
       enable_command_queue=True
   )

   mqtt = NavienMqttClient(auth, config=config)

Logging Configuration
=====================

The library uses Python's standard logging module:

Basic Logging
-------------

.. code-block:: python

   import logging

   # Enable all library logs
   logging.basicConfig(
       level=logging.DEBUG,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
   )

Selective Logging
-----------------

.. code-block:: python

   import logging

   # Only log from nwp500 library
   nwp_logger = logging.getLogger('nwp500')
   nwp_logger.setLevel(logging.INFO)

   # Only log MQTT messages
   mqtt_logger = logging.getLogger('nwp500.mqtt_client')
   mqtt_logger.setLevel(logging.DEBUG)

Log to File
-----------

.. code-block:: python

   import logging

   logging.basicConfig(
       level=logging.INFO,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
       handlers=[
           logging.FileHandler('navien.log'),
           logging.StreamHandler()
       ]
   )

Best Practices
==============

1. **Never hardcode credentials** - Use environment variables or config
   files
2. **Use async context managers** - Ensures proper cleanup
3. **Enable logging** - Helps debug issues
4. **Handle exceptions** - Network errors are common
5. **Rate limit API calls** - Use MQTT for real-time updates
6. **Secure config files** - Set proper file permissions (chmod 600)

Example: Production Configuration
==================================

.. code-block:: python

   import os
   import logging
   from nwp500 import NavienAuthClient, NavienMqttClient
   from nwp500.mqtt_utils import MqttConnectionConfig

   # Configure logging
   logging.basicConfig(
       level=logging.INFO,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
       handlers=[
           logging.FileHandler('/var/log/navien.log'),
           logging.StreamHandler()
       ]
   )

   # Get credentials from environment
   email = os.getenv("NAVIEN_EMAIL")
   password = os.getenv("NAVIEN_PASSWORD")

   if not email or not password:
       raise ValueError(
           "NAVIEN_EMAIL and NAVIEN_PASSWORD must be set"
       )

   # Configure MQTT with reconnection
   mqtt_config = MqttConnectionConfig(
       auto_reconnect=True,
       max_reconnect_attempts=15,
       enable_command_queue=True
   )

   async def main():
       try:
           async with NavienAuthClient(
               email,
               password,
               timeout=30
           ) as auth:
               mqtt = NavienMqttClient(auth, config=mqtt_config)
               await mqtt.connect()
               # ... your application code ...
               await mqtt.disconnect()
       except Exception as e:
           logging.error(f"Application error: {e}", exc_info=True)
           raise

Next Steps
==========

* :doc:`quickstart` - Build your first application
* :doc:`python_api/auth_client` - Authentication details
* :doc:`python_api/mqtt_client` - MQTT client configuration
* :doc:`guides/auto_recovery` - Automatic reconnection guide
