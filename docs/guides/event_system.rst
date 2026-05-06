========================
Event-Driven Programming
========================

The nwp500 event system lets you react to device state changes, connection
events, and derived transitions (temperature delta, mode change, etc.) without
polling.

Two Callback Patterns
=====================

``subscribe_*()`` methods
--------------------------

These deliver parsed model objects directly to your callback:

.. code-block:: python

   def on_status(status):
       print(status.dhw_temperature)

   await mqtt.subscribe_device_status(device, on_status)
   await mqtt.request_device_status(device)

``.on()`` event emitter
------------------------

These deliver a single typed event dataclass. Use them for connection events and
derived state transitions (temperature delta, mode change, etc.):

.. code-block:: python

   from nwp500 import MqttClientEvents

   def on_status_event(event):
       status = event.status
       print(f"Temperature: {status.dhw_temperature}°F")

   mqtt.on(MqttClientEvents.STATUS_RECEIVED, on_status_event)

See :doc:`../python_api/events` for the full event dataclass reference.

Available Events
----------------

.. code-block:: python

   from nwp500 import MqttClientEvents

   for event_name in MqttClientEvents.get_all_events():
       print(f"- {event_name}")

Simple Event Handler
--------------------

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient, NavienMqttClient, MqttClientEvents
   import asyncio

   async def main():
       async with NavienAuthClient(email, password) as auth:
           api = NavienAPIClient(auth)
           device = await api.get_first_device()

           mqtt = NavienMqttClient(auth)
           await mqtt.connect()

           def on_status_event(event):
               status = event.status
               print(f"Temperature: {status.dhw_temperature}°F")
               print(f"Power: {status.current_inst_power}W")

           mqtt.on(MqttClientEvents.STATUS_RECEIVED, on_status_event)
           await mqtt.request_device_status(device)

           await asyncio.sleep(300)
           await mqtt.disconnect()

   asyncio.run(main())

Raw status subscription
-----------------------

Use a typed subscription when you want the model object directly:

.. code-block:: python

   def on_status(status):
       print(status.dhw_temperature)

   await mqtt.subscribe_device_status(device, on_status)
   await mqtt.request_device_status(device)

Event Registry
--------------

Use ``MqttClientEvents`` constants to avoid typos and get IDE autocomplete:

.. code-block:: python

   from nwp500 import MqttClientEvents, NavienMqttClient

   mqtt_client = NavienMqttClient(auth)

   def on_temp_change(event):
       print(f"Temperature: {event.old_temperature} -> {event.new_temperature}")

   def on_heating_start(event):
       print(f"Heating started at {event.status.dhw_temperature}")

   def on_error(event):
       print(f"Error: {event.error_code}")

   mqtt_client.on(MqttClientEvents.TEMPERATURE_CHANGED, on_temp_change)
   mqtt_client.on(MqttClientEvents.HEATING_STARTED, on_heating_start)
   mqtt_client.on(MqttClientEvents.ERROR_DETECTED, on_error)

   for event_name in MqttClientEvents.get_all_events():
       print(f"  - {event_name}")

See :doc:`../python_api/events` for the event dataclass reference.

Advanced Patterns
=================

Tracking significant changes
----------------------------

Filter callbacks to only act when a value changes by more than a threshold:

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

Multiple devices
----------------

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

Alert rules
-----------

Trigger actions when the device crosses a threshold:

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

Data logging
------------

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

Home automation bridge
----------------------

Publish status updates to Home Assistant or similar systems:

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

Keep handlers lightweight
--------------------------

Offload heavy work with ``asyncio.create_task`` rather than blocking in the callback:

.. code-block:: python

   def on_status(status):
       asyncio.create_task(process_status(status))

Wrap callbacks in try/except
-----------------------------

An unhandled exception in a callback won't crash the event loop, but it will
silence subsequent events for that subscription:

.. code-block:: python

   def safe_handler(status):
       try:
           process_status(status)
       except Exception as e:
           print(f"Handler error: {e}")

Async callbacks
---------------

Callbacks can be async. The client will schedule them as tasks:

.. code-block:: python

   async def async_handler(status):
       await save_to_database(status)
       await send_notification(status)

Batch processing
----------------

Buffer updates and flush periodically to reduce I/O overhead:

.. code-block:: python

   class BatchProcessor:
       def __init__(self):
           self.buffer = []

       def on_status(self, status):
           self.buffer.append(status)
           if len(self.buffer) >= 10:
               self.flush()

       def flush(self):
           save_batch_to_db(self.buffer)
           self.buffer.clear()

Related Documentation
=====================

* :doc:`../python_api/events` - Event API reference
* :doc:`../python_api/mqtt_client` - MQTT client
* :doc:`../python_api/models` - Data models
