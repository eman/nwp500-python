========================
Event-Driven Programming
========================

This guide demonstrates how to build event-driven applications using the
nwp500 library's event system.

Overview
========

The event system allows you to:

* React to device state changes in real-time
* Build responsive, reactive applications
* Separate concerns (monitoring, logging, alerting)
* Handle multiple devices with a unified interface

Benefits
--------

**Compared to polling:**

* Lower latency - react immediately to changes
* More efficient - no wasted requests
* Cleaner code - declarative callbacks vs loops
* Better scalability - handle multiple devices easily

**Use cases:**

* Home automation triggers
* Alert systems
* Data logging and analytics
* UI updates
* Integration with other systems

Basic Usage
===========

Simple Event Handler
--------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient
   import asyncio

   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           # Define event handler
           def on_status_update(status):
               print(f"Temperature: {status.dhw_temperature}°F")
               print(f"Power: {status.current_inst_power}W")

           # Subscribe to status updates
           await mqtt.subscribe_device_status(device, on_status_update)
           await mqtt.request_device_status(device)

           # Monitor for 5 minutes
           await asyncio.sleep(300)
           await mqtt.disconnect()

   asyncio.run(main())

Advanced Patterns
=================

Pattern 1: State Tracking
--------------------------

Track state changes and react only when values change significantly.

.. code-block:: python

   class DeviceMonitor:
       def __init__(self, device, mqtt):
           self.device = device
           self.mqtt = mqtt
           self.last_temp = None
           self.last_power = None

       async def start(self):
           await self.mqtt.subscribe_device_status(
               self.device,
               self.on_status
           )
           await self.mqtt.request_device_status(self.device)

       def on_status(self, status):
           # Temperature changed by more than 2°F
           if self.last_temp is None or abs(status.dhw_temperature - self.last_temp) >= 2:
               print(f"Temperature changed: {self.last_temp}°F → {status.dhw_temperature}°F")
               self.last_temp = status.dhw_temperature

           # Power changed by more than 100W
           if self.last_power is None or abs(status.current_inst_power - self.last_power) >= 100:
               print(f"Power changed: {self.last_power}W → {status.current_inst_power}W")
               self.last_power = status.current_inst_power

   # Usage
   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           monitor = DeviceMonitor(device, mqtt)
           await monitor.start()

           await asyncio.sleep(3600)  # Monitor for 1 hour

Pattern 2: Multi-Device Monitoring
-----------------------------------

Monitor multiple devices with individual callbacks.

.. code-block:: python

   class MultiDeviceMonitor:
       def __init__(self, mqtt):
           self.mqtt = mqtt
           self.devices = {}

       async def add_device(self, device):
           device_id = device.device_info.mac_address

           # Create device-specific callback
           def callback(status):
               self.on_device_status(device_id, status)

           # Subscribe
           await self.mqtt.subscribe_device_status(device, callback)
           await self.mqtt.request_device_status(device)

           self.devices[device_id] = {
               'device': device,
               'callback': callback,
               'last_status': None
           }

       def on_device_status(self, device_id, status):
           device_data = self.devices[device_id]
           device_name = device_data['device'].device_info.device_name

           print(f"[{device_name}]")
           print(f"  Temperature: {status.dhw_temperature}°F")
           print(f"  Power: {status.current_inst_power}W")
           print()

           device_data['last_status'] = status

   # Usage
   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           devices = await api.list_devices()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           monitor = MultiDeviceMonitor(mqtt)

           # Add all devices
           for device in devices:
               await monitor.add_device(device)

           # Monitor indefinitely
           while True:
               await asyncio.sleep(60)

Pattern 3: Alert System
------------------------

Build an alert system that triggers on specific conditions.

.. code-block:: python

   from datetime import datetime
   from typing import Callable, List

   class AlertRule:
       def __init__(self, name: str, condition: Callable, action: Callable):
           self.name = name
           self.condition = condition
           self.action = action

       def check(self, status):
           if self.condition(status):
               self.action(status)

   class AlertSystem:
       def __init__(self, device, mqtt):
           self.device = device
           self.mqtt = mqtt
           self.rules: List[AlertRule] = []

       def add_rule(self, rule: AlertRule):
           self.rules.append(rule)

       async def start(self):
           await self.mqtt.subscribe_device_status(
               self.device,
               self.on_status
           )
           await self.mqtt.start_periodic_requests(
               self.device,
               period_seconds=60
           )

       def on_status(self, status):
           for rule in self.rules:
               rule.check(status)

   # Define alert actions
   def send_email(subject, body):
       print(f"EMAIL: {subject}\n{body}")
       # Implement email sending

   def send_sms(message):
       print(f"SMS: {message}")
       # Implement SMS sending

   def log_alert(message):
       timestamp = datetime.now().isoformat()
       print(f"[{timestamp}] ALERT: {message}")

   # Usage
   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           alerts = AlertSystem(device, mqtt)

           # Define alert rules
           alerts.add_rule(AlertRule(
               name="Low Temperature",
               condition=lambda s: s.dhw_temperature < 110,
               action=lambda s: send_email(
                   "Low Water Temperature",
                   f"Temperature dropped to {s.dhw_temperature}°F"
               )
           ))

           alerts.add_rule(AlertRule(
               name="High Power",
               condition=lambda s: s.current_inst_power > 2000,
               action=lambda s: log_alert(
                   f"High power usage: {s.current_inst_power}W"
               )
           ))

           alerts.add_rule(AlertRule(
               name="Error Detected",
               condition=lambda s: s.error_code != 0,
               action=lambda s: send_sms(
                   f"Device error: {s.error_code}"
               )
           ))

           await alerts.start()

           # Monitor indefinitely
           while True:
               await asyncio.sleep(3600)

Pattern 4: Data Logger
-----------------------

Log device data to a database or file.

.. code-block:: python

   import sqlite3
   from datetime import datetime

   class DataLogger:
       def __init__(self, device, mqtt, db_path="navien_data.db"):
           self.device = device
           self.mqtt = mqtt
           self.db_path = db_path
           self.setup_database()

       def setup_database(self):
           conn = sqlite3.connect(self.db_path)
           cursor = conn.cursor()
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS status_log (
                   timestamp TEXT,
                   device_mac TEXT,
                   temperature REAL,
                   target_temp REAL,
                   power REAL,
                   mode TEXT,
                   operation_mode TEXT,
                   error_code INTEGER
               )
           """)
           conn.commit()
           conn.close()

       async def start(self):
           await self.mqtt.subscribe_device_status(
               self.device,
               self.log_status
           )
           await self.mqtt.start_periodic_requests(
               self.device,
               period_seconds=300  # Log every 5 minutes
           )

       def log_status(self, status):
           timestamp = datetime.now().isoformat()
           device_mac = self.device.device_info.mac_address

           conn = sqlite3.connect(self.db_path)
           cursor = conn.cursor()
           cursor.execute("""
               INSERT INTO status_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           """, (
               timestamp,
               device_mac,
               status.dhw_temperature,
               status.dhw_temperature_setting,
               status.current_inst_power,
               status.dhw_operation_setting.name,
               status.operation_mode.name,
               status.error_code
           ))
           conn.commit()
           conn.close()

           print(f"[{timestamp}] Logged status for {device_mac}")

   # Usage
   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           logger = DataLogger(device, mqtt)
           await logger.start()

           # Log indefinitely
           while True:
               await asyncio.sleep(3600)

Pattern 5: Home Automation Integration
---------------------------------------

Integrate with Home Assistant, OpenHAB, or custom systems.

.. code-block:: python

   import aiohttp

   class HomeAssistantBridge:
       def __init__(self, device, mqtt, ha_url, ha_token):
           self.device = device
           self.mqtt = mqtt
           self.ha_url = ha_url
           self.ha_token = ha_token

       async def start(self):
           await self.mqtt.subscribe_device_status(
               self.device,
               self.publish_to_ha
           )
           await self.mqtt.start_periodic_requests(
               self.device,
               period_seconds=30
           )

       async def publish_to_ha(self, status):
           """Publish device status to Home Assistant MQTT."""
           device_mac = self.device.device_info.mac_address

           # Prepare state data
           state_data = {
               'temperature': status.dhw_temperature,
               'target_temperature': status.dhw_temperature_setting,
               'power': status.current_inst_power,
               'mode': status.dhw_operation_setting.name,
               'state': status.operation_mode.name,
               'error': status.error_code
           }

           # Publish to HA
           async with aiohttp.ClientSession() as session:
               headers = {
                   'Authorization': f'Bearer {self.ha_token}',
                   'Content-Type': 'application/json'
               }

               url = f"{self.ha_url}/api/states/sensor.navien_{device_mac}"

               async with session.post(url, headers=headers, json={
                   'state': status.dhw_temperature,
                   'attributes': state_data
               }) as resp:
                   if resp.status == 200:
                       print(f"Published to Home Assistant")
                   else:
                       print(f"HA publish failed: {resp.status}")

   # Usage
   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           bridge = HomeAssistantBridge(
               device,
               mqtt,
               ha_url="http://homeassistant.local:8123",
               ha_token="your_long_lived_token"
           )

           await bridge.start()

           # Run indefinitely
           while True:
               await asyncio.sleep(3600)

Best Practices
==============

1. **Keep handlers lightweight:**

   .. code-block:: python

      # GOOD: Fast handler
      def on_status(status):
          asyncio.create_task(process_status(status))

      # BAD: Slow handler (blocks event loop)
      def on_status(status):
          time.sleep(5)  # BAD
          process_status(status)

2. **Handle errors in callbacks:**

   .. code-block:: python

      def safe_handler(status):
          try:
              process_status(status)
          except Exception as e:
              print(f"Handler error: {e}")
              # Don't let errors crash the event loop

3. **Unsubscribe when done:**

   .. code-block:: python

      # Track callback references
      callback = lambda s: print(s.dhw_temperature)

      await mqtt.subscribe_device_status(device, callback)

      # Later, unsubscribe
      # (if the MQTT client supports it)

4. **Use async callbacks when possible:**

   .. code-block:: python

      async def async_handler(status):
          # Can await async operations
          await save_to_database(status)
          await send_notification(status)

5. **Batch updates to reduce overhead:**

   .. code-block:: python

      class BatchProcessor:
          def __init__(self):
              self.buffer = []

          def on_status(self, status):
              self.buffer.append(status)

              if len(self.buffer) >= 10:
                  self.flush()

          def flush(self):
              # Process batch
              save_batch_to_db(self.buffer)
              self.buffer.clear()

Related Documentation
=====================

* :doc:`../python_api/events` - Event API reference
* :doc:`../python_api/mqtt_client` - MQTT client
* :doc:`../python_api/models` - Data models
