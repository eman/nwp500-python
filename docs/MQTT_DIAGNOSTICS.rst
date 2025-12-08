================================================================================
MQTT Connection Drops Investigation & Diagnostics Guide
================================================================================

.. contents::
   :depth: 2
   :local:

Overview
========

This guide provides a comprehensive toolkit for investigating and resolving AWS
MQTT connection drops (``AWS_ERROR_MQTT_UNEXPECTED_HANGUP``). It helps identify
whether drops are caused by network/environmental issues, AWS server-side limits,
or client-side configuration problems.

Quick Start
===========

30-Second Integration
---------------------

.. code-block:: python

   from nwp500 import (
       NavienAuthClient,
       NavienMqttClient,
       MqttDiagnosticsCollector,
       MqttConnectionConfig,
   )

   # Create diagnostics
   diagnostics = MqttDiagnosticsCollector(enable_verbose_logging=True)

   # Connect with hardened config
   config = MqttConnectionConfig(keep_alive_secs=60)  # Reduced from 1200
   mqtt_client = NavienMqttClient(auth_client, config=config)

   # Hook events
   mqtt_client.on('connection_interrupted',
       lambda e: diagnostics.record_connection_drop(error=e)
   )

   mqtt_client.on('connection_resumed',
       lambda rc, sp: diagnostics.record_connection_success(
           event_type='resumed', session_present=sp
       )
   )

   # Export periodically
   json_export = diagnostics.export_json()
   diagnostics.print_summary()

Pattern Analysis Reference
--------------------------

Different drop patterns indicate different root causes:

========================================  ================  ====================
Pattern                                   Likely Cause      Check/Fix
========================================  ================  ====================
Regular intervals (e.g., every 20 min)    AWS timeout       CloudWatch metrics
Irregular/random                          Network/NAT       NAT timeout, Wi-Fi
After many messages                       Rate limiting     AWS quota
During system events                      Device config     Power save, cron
========================================  ================  ====================

Diagnostics Module
==================

The ``MqttDiagnosticsCollector`` class provides telemetry:

.. code-block:: python

   from nwp500 import (
       MqttDiagnosticsCollector,
       MqttMetrics,
       ConnectionDropEvent,
       ConnectionEvent,
   )

   # Create collector
   diagnostics = MqttDiagnosticsCollector(
       max_events_retained=1000,
       enable_verbose_logging=True
   )

   # Record drop event
   await diagnostics.record_connection_drop(
       error=exception,
       active_subscriptions=10,
       queued_commands=5
   )

   # Record successful connection
   await diagnostics.record_connection_success(
       event_type='resumed',
       session_present=True,
       return_code=0
   )

   # Export metrics
   json_data = diagnostics.export_json()
   metrics = diagnostics.get_metrics()
   diagnostics.print_summary()

Key Classes
-----------

**MqttDiagnosticsCollector**
   Main telemetry collector. Tracks connection drops, recoveries, error patterns,
   session durations, and message metrics.

   Methods:

   - ``record_connection_drop(error, reconnect_attempt, active_subscriptions, queued_commands)``
   - ``record_connection_success(event_type, session_present, return_code, attempt_number)``
   - ``record_publish(queued)``
   - ``update_metrics()``
   - ``get_metrics()`` - Returns MqttMetrics object
   - ``get_recent_drops(limit)`` - Get N recent drop events
   - ``get_recent_connections(limit)`` - Get N recent connection events
   - ``export_json()`` - Export all metrics as JSON string
   - ``print_summary()`` - Print human-readable summary
   - ``on_connection_drop(callback)`` - Register drop event callback

**ConnectionDropEvent**
   Dataclass representing a single connection drop event:

   - ``timestamp`` - ISO 8601 timestamp
   - ``error_name`` - AWS error name (e.g., ``AWS_ERROR_MQTT_UNEXPECTED_HANGUP``)
   - ``error_message`` - Error message text
   - ``error_code`` - AWS error code
   - ``reconnect_attempt`` - Reconnection attempt number
   - ``duration_connected_seconds`` - How long session lasted
   - ``active_subscriptions`` - Number of active subscriptions
   - ``queued_commands`` - Commands in queue

**ConnectionEvent**
   Dataclass representing successful connection/reconnection:

   - ``timestamp`` - ISO 8601 timestamp
   - ``event_type`` - "connected", "resumed", or "deep_reconnected"
   - ``session_present`` - MQTT session was present
   - ``return_code`` - MQTT return code
   - ``attempt_number`` - Reconnection attempt number (0 for initial)
   - ``time_to_reconnect_seconds`` - Time to recover from drop

**MqttMetrics**
   Aggregate statistics:

   - Connection lifecycle: total connections, drops, recoveries
   - Session timing: min/max/average duration, current uptime
   - Error analysis: drops by error type, attempt distribution
   - Messaging: published and queued message counts

Recommended Configuration
=========================

Start with these hardened settings:

.. code-block:: python

   from nwp500.mqtt_utils import MqttConnectionConfig

   config = MqttConnectionConfig(
       # 1. Reduce keep-alive (prevents NAT idle timeout)
       keep_alive_secs=60,              # Reduced from 1200
       
       # 2. Faster reconnection for transient failures
       initial_reconnect_delay=0.5,     # 500ms (was 1s)
       max_reconnect_delay=60.0,        # 1 min (was 120s)
       
       # 3. Try deeper reconnect (token refresh) sooner
       deep_reconnect_threshold=5,      # After 5 attempts (was 10)
       
       # 4. Unlimited retries with exponential backoff
       max_reconnect_attempts=-1,
       
       # 5. Preserve commands during brief disconnections
       enable_command_queue=True,
       max_queued_commands=200,
   )

   mqtt_client = NavienMqttClient(auth_client, config=config)

Why These Settings Matter
--------------------------

**Keep-Alive (1200s → 60s)**
   Most NAT devices timeout idle connections after 300-600 seconds. Default
   1200s keep-alive allows NAT to timeout before keep-alive packets arrive,
   causing connection to die. 60s ensures packets arrive before timeout.

**Faster Reconnection (1s → 0.5s)**
   Transient network glitches often recover in <1 second. Faster initial retry
   reduces perceived latency.

**Deep Reconnect Threshold (10 → 5)**
   After 5 failed quick reconnects, try full token refresh. This recovers from
   authentication issues more quickly.

**Unlimited Retries**
   With exponential backoff, eventually recover from any transient issue without
   user intervention.

**Command Queue**
   Prevents command loss during brief disconnections. Commands are automatically
   sent when connection restored.

Phase 1: Telemetry Collection
=============================

Enable diagnostics and collect baseline data.

1.1 Instrument Your Code
-------------------------

.. code-block:: python

   from nwp500 import (
       NavienAuthClient,
       NavienMqttClient,
       MqttDiagnosticsCollector,
   )

   async def main():
       diagnostics = MqttDiagnosticsCollector(enable_verbose_logging=True)
       
       async with NavienAuthClient(email, password) as auth_client:
           await auth_client.sign_in()
           mqtt_client = NavienMqttClient(auth_client)
           
           # Hook connection events
           mqtt_client.on('connection_interrupted',
               lambda e: asyncio.create_task(
                   diagnostics.record_connection_drop(
                       error=e,
                       queued_commands=mqtt_client.queued_commands_count
                   )
               )
           )
           
           mqtt_client.on('connection_resumed',
               lambda rc, sp: asyncio.create_task(
                   diagnostics.record_connection_success(
                       event_type='resumed',
                       session_present=sp,
                       return_code=rc
                   )
               )
           )
           
           await mqtt_client.connect()
           # ... rest of application ...

1.2 Export Diagnostics Periodically
------------------------------------

.. code-block:: python

   async def periodic_export(diagnostics, interval=300):
       """Export diagnostics every 5 minutes."""
       while True:
           try:
               await asyncio.sleep(interval)
               
               # Save JSON
               json_data = diagnostics.export_json()
               with open('mqtt_diagnostics.json', 'w') as f:
                   f.write(json_data)
               
               # Print summary
               diagnostics.print_summary()
               
           except asyncio.CancelledError:
               break

   # In your main coroutine
   export_task = asyncio.create_task(periodic_export(diagnostics))

1.3 Collect Data
----------------

Run your application with diagnostics enabled for 24+ hours to establish a
baseline of drop patterns and frequencies.

Phase 2: AWS Server-Side Verification
======================================

Check AWS IoT Core metrics and logs.

2.1 CloudWatch Metrics
----------------------

1. Navigate to **AWS IoT Core** → **Monitor** → **Metrics**
2. Look for:

   - ``NumberOfConnections`` - Should remain stable
   - ``PublishIn.Success`` / ``PublishOut.Success`` - Message throughput
   - ``RejectedConnections`` - Auth/quota rejections
   - ``PublishIn.Throttle`` - Rate limiting

2.2 CloudWatch Logs
-------------------

1. Go to **Logs** → **Log groups** → Your IoT log group
2. Filter for client ID: ``clientId = "your-client-id"``
3. Look for error patterns: ``AWS_ERROR_MQTT_UNEXPECTED_HANGUP``

2.3 AWS IoT Quotas
------------------

Check these service limits (AWS IoT Core):

- **Max concurrent connections**: 500,000
- **Message throughput**: Varies by connection type
- **Max message size**: 128 KB
- **Connection lifetime**: No explicit limit, but idle timeouts apply

If approaching limits, request increase via AWS Support.

Phase 3: Network-Level Diagnostics
===================================

Monitor network connectivity and identify NAT/Wi-Fi issues.

3.1 Continuous Connectivity Testing
------------------------------------

Run alongside your application:

.. code-block:: bash

   # Ping the AWS IoT endpoint continuously
   ping a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com

   # TCP connection test
   for i in {1..100}; do
       nc -zv -w 5 a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com 443
       sleep 60
   done

3.2 Network Monitoring
----------------------

**Linux/macOS:**

.. code-block:: bash

   # Monitor network state changes
   watch -n 1 'ip addr show && echo "---" && netstat -tne'

   # Capture DNS lookups
   tcpdump -i any 'port 53' &

   # Monitor TCP retransmits
   watch -n 1 'cat /proc/net/snmp | grep -E "Tcp|IpExt"'

**Check for:**

- DNS resolution failures
- TCP retransmit spikes
- Route changes
- Interface flapping (Wi-Fi disconnects)
- Packet loss

3.3 Router/NAT Configuration
-----------------------------

- SSH into router and check system logs
- Look for: Connection timeouts, NAT table exhaustion, port reuse
- Check NAT idle timeout (typically 240-600 seconds)
- Verify TCP keep-alive is reaching NAT (every 60 seconds)

Phase 4: Environmental Issue Detection
=======================================

Correlate drops with system events.

4.1 Check System Logs
---------------------

.. code-block:: bash

   # Recent system warnings
   journalctl --since="1 hour ago" -p warn

   # Wi-Fi events
   journalctl -u NetworkManager --since="1 hour ago"

   # Power save/suspend events
   journalctl -u systemd-suspend --since="1 hour ago"

   # Cron jobs
   journalctl -u cron --since="1 hour ago"

4.2 Disable Power Save Modes
----------------------------

**macOS:**

.. code-block:: bash

   pmset -g assertions

**Linux:**

.. code-block:: bash

   # Check power settings
   cat /proc/sys/net/ipv4/tcp_keepalive_time

   # Disable aggressive power save
   sudo ethtool -s <interface> wol g

4.3 Monitor DHCP Renewals
-------------------------

.. code-block:: bash

   # Watch DHCP client logs
   tail -f /var/log/syslog | grep dhclient

   # Or with systemd-resolved
   journalctl -u systemd-resolved -f

Root Cause Analysis
===================

Pattern Identification
----------------------

**Regular Drop Intervals** (e.g., every 20 minutes)

- **Likely Cause**: AWS connection lifetime limit or scheduled event
- **What to Check**:

  - CloudWatch: Connection count, rejections
  - Timestamps: Do drops occur at same time daily?
  - AWS Device Defender logs
  - AWS quota limits

- **Fix**: Contact AWS Support if hitting limit

**Irregular/Random Drops**

- **Likely Cause**: Network intermittency, NAT timeout, Wi-Fi issues
- **What to Check**:

  - Continuous ping to AWS endpoint (packet loss?)
  - Network packet loss/retransmits
  - NAT idle timeout settings
  - Wi-Fi signal strength (RSSI)

- **Fix**: Reduce ``keep_alive_secs`` to 60-120 seconds

**Drops After Many Messages**

- **Likely Cause**: Rate limiting, message buffer overflow, AWS quota
- **What to Check**:

  - Message throughput in CloudWatch
  - AWS IoT quota (messages/second/connection)
  - MQTT message QoS and buffer settings

- **Fix**: Reduce message rate or check AWS quota

**Drops During System Events**

- **Likely Cause**: Power save mode, Wi-Fi state change, updates, cron jobs
- **What to Check**:

  - System logs (journalctl, syslog)
  - Power management settings
  - Cron jobs and scheduled tasks
  - DHCP lease renewal events

- **Fix**: Disable power save, reschedule conflicting jobs, fix Wi-Fi

Integration Examples
====================

Basic Monitoring Loop
---------------------

.. code-block:: python

   import asyncio
   from nwp500 import (
       NavienAuthClient,
       NavienMqttClient,
       MqttDiagnosticsCollector,
       MqttConnectionConfig,
   )

   async def main():
       diagnostics = MqttDiagnosticsCollector(enable_verbose_logging=False)
       
       async with NavienAuthClient(email, password) as auth_client:
           await auth_client.sign_in()
           
           config = MqttConnectionConfig(
               keep_alive_secs=60,
               initial_reconnect_delay=0.5,
               max_reconnect_delay=60.0,
               deep_reconnect_threshold=5,
               max_reconnect_attempts=-1,
               enable_command_queue=True,
           )
           
           mqtt_client = NavienMqttClient(auth_client, config=config)
           
           mqtt_client.on('connection_interrupted',
               lambda e: asyncio.create_task(
                   diagnostics.record_connection_drop(error=e)
               )
           )
           
           mqtt_client.on('connection_resumed',
               lambda rc, sp: asyncio.create_task(
                   diagnostics.record_connection_success(
                       event_type='resumed', session_present=sp
                   )
               )
           )
           
           await mqtt_client.connect()
           
           # Export task
           export_task = asyncio.create_task(
               periodic_export(diagnostics, interval=300)
           )
           
           try:
               await asyncio.sleep(3600)  # 1 hour
           finally:
               export_task.cancel()
               await mqtt_client.disconnect()

Class-Based Monitoring
----------------------

.. code-block:: python

   import asyncio
   import logging
   from pathlib import Path
   from datetime import datetime

   from nwp500 import (
       NavienAuthClient,
       NavienMqttClient,
       MqttDiagnosticsCollector,
       MqttConnectionConfig,
   )

   _logger = logging.getLogger(__name__)


   class MqttMonitor:
       """Production-ready MQTT monitor with diagnostics."""
       
       def __init__(
           self,
           email: str,
           password: str,
           output_dir: str = "./mqtt_diagnostics",
           export_interval: float = 300.0,
       ):
           self.email = email
           self.password = password
           self.output_dir = Path(output_dir)
           self.export_interval = export_interval
           self.output_dir.mkdir(exist_ok=True)
           
           self.diagnostics = MqttDiagnosticsCollector(enable_verbose_logging=True)
           self.mqtt_client = None
           self.auth_client = None
           self.running = True
       
       async def start(self) -> None:
           """Start the monitor."""
           try:
               self.auth_client = NavienAuthClient(self.email, self.password)
               await self.auth_client.sign_in()
               _logger.info("Authenticated successfully")
               
               config = MqttConnectionConfig(
                   keep_alive_secs=60,
                   initial_reconnect_delay=0.5,
                   max_reconnect_delay=60.0,
                   deep_reconnect_threshold=5,
                   max_reconnect_attempts=-1,
                   enable_command_queue=True,
               )
               
               self.mqtt_client = NavienMqttClient(self.auth_client, config=config)
               
               self.mqtt_client.on('connection_interrupted',
                   lambda e: asyncio.create_task(self._on_drop(e))
               )
               
               self.mqtt_client.on('connection_resumed',
                   lambda rc, sp: asyncio.create_task(self._on_resume(rc, sp))
               )
               
               await self.mqtt_client.connect()
               _logger.info("Connected to MQTT broker")
               
               await self._periodic_export_loop()
               
           finally:
               await self.stop()
       
       async def _on_drop(self, error: Exception) -> None:
           """Handle connection drop."""
           _logger.warning(f"Connection dropped: {error}")
           
           active_subs = (
               len(self.mqtt_client._subscription_manager.subscriptions)
               if (
                   self.mqtt_client
                   and self.mqtt_client._subscription_manager
               )
               else 0
           )
           
           await self.diagnostics.record_connection_drop(
               error=error,
               active_subscriptions=active_subs,
               queued_commands=(
                   self.mqtt_client.queued_commands_count
                   if self.mqtt_client
                   else 0
               ),
           )
       
       async def _on_resume(self, return_code: int, session_present: bool) -> None:
           """Handle connection resume."""
           _logger.info(
               f"Connection resumed: rc={return_code}, "
               f"session_present={session_present}"
           )
           
           await self.diagnostics.record_connection_success(
               event_type="resumed",
               session_present=session_present,
               return_code=return_code,
           )
       
       async def _periodic_export_loop(self) -> None:
           """Periodically export diagnostics."""
           while self.running:
               try:
                   await asyncio.sleep(self.export_interval)
                   
                   if not self.running:
                       break
                   
                   timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                   output_file = self.output_dir / f"diagnostics_{timestamp}.json"
                   
                   json_data = self.diagnostics.export_json()
                   with open(output_file, 'w') as f:
                       f.write(json_data)
                   
                   _logger.info(f"Exported diagnostics to {output_file}")
                   self.diagnostics.print_summary()
                   
               except asyncio.CancelledError:
                   break
       
       async def stop(self) -> None:
           """Stop the monitor."""
           self.running = False
           
           if self.mqtt_client:
               await self.mqtt_client.disconnect()
               _logger.info("Disconnected from MQTT")
           
           if self.auth_client:
               await self.auth_client.close()
               _logger.info("Closed auth session")


   async def main():
       """Main entry point."""
       monitor = MqttMonitor(
           email="your@email.com",
           password="your_password",
           export_interval=300.0,
       )
       
       try:
           await monitor.start()
       except KeyboardInterrupt:
           _logger.info("Interrupted by user")
           await monitor.stop()

Device Control Integration
--------------------------

.. code-block:: python

   async def control_device_with_diagnostics(
       mqtt_client,
       diagnostics,
       device,
   ):
       """Control device and track in diagnostics."""
       
       try:
           # Record publish
           diagnostics.record_publish(queued=not mqtt_client.is_connected)
           
           # Set temperature
           await mqtt_client.set_dhw_temperature(device, 140.0)
           
           if not mqtt_client.is_connected:
               _logger.info(
                   f"Device disconnected, command queued. "
                   f"Total queued: {mqtt_client.queued_commands_count}"
               )
       
       except Exception as e:
           _logger.error(f"Error controlling device: {e}")
           raise

Analyzing Exported Data
-----------------------

.. code-block:: python

   import json

   def analyze_diagnostics(json_file: str) -> None:
       """Analyze exported diagnostics."""
       
       with open(json_file) as f:
           data = json.load(f)
       
       metrics = data['metrics']
       recent_drops = data['recent_drops']
       
       print(f"Total Drops: {metrics['total_connection_drops']}")
       print(f"Successful Reconnections: {metrics['connection_recovered']}")
       print(f"Current Uptime: {metrics['current_session_uptime_seconds']:.0f}s")
       
       # Analyze drop patterns
       if recent_drops:
           print("\nRecent Drops:")
           for drop in recent_drops[-5:]:
               print(
                   f"  {drop['timestamp']}: "
                   f"{drop['error_name']} "
                   f"(duration: {drop['duration_connected_seconds']:.0f}s)"
               )
       
       # Check error distribution
       if data['aws_error_counts']:
           print("\nError Frequency:")
           for error, count in data['aws_error_counts'].items():
               print(f"  {error}: {count}")

Home Assistant Custom Component Integration
=============================================

If you're developing a Home Assistant custom component that uses the MQTT client,
consider integrating ``MqttDiagnosticsCollector`` to help users identify setup
problems and understand server behavior. This approach mirrors Home Assistant's
own diagnostics system.

Integration Pattern
-------------------

.. code-block:: python

    # In your Home Assistant custom component
    import asyncio
    from datetime import datetime
    from nwp500 import MqttDiagnosticsCollector, NavienMqttClient
    
    class NavienEntity:
        """Base Home Assistant entity with diagnostics support."""
        
        def __init__(self, hass, mqtt_client):
            self.hass = hass
            self.mqtt_client = mqtt_client
            self.diagnostics = MqttDiagnosticsCollector(
                enable_verbose_logging=False
            )
            self._setup_event_hooks()
        
        def _setup_event_hooks(self):
            """Hook diagnostics into MQTT client events."""
            self.mqtt_client.on('connection_interrupted',
                lambda e: asyncio.create_task(
                    self.diagnostics.record_connection_drop(error=e)
                )
            )
            
            self.mqtt_client.on('connection_resumed',
                lambda rc, sp: asyncio.create_task(
                    self.diagnostics.record_connection_success(
                        event_type='resumed',
                        session_present=sp,
                        return_code=rc
                    )
                )
            )

Storage Recommendation
----------------------

For Home Assistant integration, **save diagnostics data to Home Assistant's 
configuration directory** rather than separate files or logs:

.. code-block:: python

    import json
    from pathlib import Path
    
    class NavienIntegration:
        def __init__(self, hass, config_entry):
            self.hass = hass
            self.config_entry = config_entry
            # Diagnostics stored in: .homeassistant/nwp500_diagnostics.json
            self.diagnostics_path = (
                Path(self.hass.config.path())
                / "nwp500_diagnostics.json"
            )
        
        async def export_diagnostics(self):
            """Export diagnostics to Home Assistant config dir."""
            json_data = self.diagnostics.export_json()
            self.diagnostics_path.write_text(json_data)
            
            _LOGGER.debug(f"Saved diagnostics to {self.diagnostics_path}")

Why This Approach?
^^^^^^^^^^^^^^^^^^

**Home Assistant Config Directory** (Recommended)
    - Stored alongside user configuration files
    - User can easily locate and review
    - Accessible via file editor integration
    - Persists across restarts
    - Can be included in bug reports
    - **Best for**: Integration debugging, user troubleshooting

**NOT Home Assistant Data Store** (Avoid)
    - Not designed for application diagnostics
    - Data store is for persisting entity states
    - Creates unnecessary database bloat
    - Harder for users to export/inspect
    - Poor for large JSON diagnostic exports

**NOT Home Assistant Logs** (Avoid)
    - Logs rotate frequently
    - Loss of historical patterns
    - Difficult to correlate with cloud data
    - Large JSON exports clutter logs
    - Users may have log level filters

**NOT Separate Files** (Avoid in HA context)
    - Fragments data outside user's main directory
    - Harder for users to back up together
    - Complicates distribution/collection

Integration with Home Assistant Diagnostics
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Implement Home Assistant's native diagnostics protocol to expose your data:

.. code-block:: python

    # manifest.json
    {
        "domain": "navien_nwp500",
        "name": "Navien NWP500",
        "codeowners": ["@your_username"],
        "config_flow": true,
        "documentation": "https://github.com/your_repo",
        "iot_class": "cloud_polling",
        "requirements": ["nwp500>=3.0.0"],
        "version": "1.0.0"
    }
    
    # diagnostics.py
    from homeassistant.components.diagnostics import async_redact_data
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    
    async def async_get_config_entry_diagnostics(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> dict:
        """Return diagnostics for config entry."""
        
        integration = hass.data.get(DOMAIN, {}).get(
            config_entry.entry_id
        )
        
        if not integration or not integration.diagnostics:
            return {"error": "Integration not initialized"}
        
        # Export and parse diagnostics
        import json
        data = json.loads(integration.diagnostics.export_json())
        
        # Redact sensitive info (credentials, tokens, etc.)
        return async_redact_data(data, REDACT_FIELDS)

This allows users to view diagnostics directly in Home Assistant UI:
**Settings → System → Diagnostics** for your integration.

Periodic Export Schedule
^^^^^^^^^^^^^^^^^^^^^^^^

For production Home Assistant components:

.. code-block:: python

    async def setup_diagnostics_export(hass, integration):
        """Set up periodic diagnostic exports."""
        
        async def export_task():
            while True:
                await asyncio.sleep(300)  # Every 5 minutes
                
                try:
                    await integration.export_diagnostics()
                except Exception as e:
                    _LOGGER.error(f"Failed to export diagnostics: {e}")
        
        asyncio.create_task(export_task())

Example: Minimal HA Component with Diagnostics
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # __init__.py
    import asyncio
    import json
    import logging
    from pathlib import Path
    
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    
    from nwp500 import (
        NavienAuthClient,
        NavienMqttClient,
        MqttDiagnosticsCollector,
        MqttConnectionConfig,
    )
    
    _LOGGER = logging.getLogger(__name__)
    DOMAIN = "navien_nwp500"
    
    
    async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> bool:
        """Set up Navien integration."""
        
        diagnostics = MqttDiagnosticsCollector(
            enable_verbose_logging=False
        )
        
        auth_client = NavienAuthClient(
            config_entry.data["email"],
            config_entry.data["password"],
        )
        
        await auth_client.sign_in()
        
        mqtt_client = NavienMqttClient(
            auth_client,
            config=MqttConnectionConfig(
                keep_alive_secs=60,
                initial_reconnect_delay=0.5,
                max_reconnect_delay=60.0,
                deep_reconnect_threshold=5,
                enable_command_queue=True,
            ),
        )
        
        # Hook diagnostics
        mqtt_client.on('connection_interrupted',
            lambda e: asyncio.create_task(
                diagnostics.record_connection_drop(error=e)
            )
        )
        
        mqtt_client.on('connection_resumed',
            lambda rc, sp: asyncio.create_task(
                diagnostics.record_connection_success(
                    event_type='resumed',
                    session_present=sp,
                    return_code=rc,
                )
            )
        )
        
        await mqtt_client.connect()
        
        # Store for later access
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][config_entry.entry_id] = {
            "auth_client": auth_client,
            "mqtt_client": mqtt_client,
            "diagnostics": diagnostics,
        }
        
        # Start periodic export
        asyncio.create_task(
            _periodic_diagnostic_export(hass, config_entry, diagnostics)
        )
        
        return True
    
    
    async def _periodic_diagnostic_export(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        diagnostics: MqttDiagnosticsCollector,
    ) -> None:
        """Export diagnostics every 5 minutes."""
        
        output_file = (
            Path(hass.config.path())
            / f"nwp500_diagnostics_{config_entry.entry_id}.json"
        )
        
        while True:
            try:
                await asyncio.sleep(300)
                
                json_data = diagnostics.export_json()
                output_file.write_text(json_data)
                
                _LOGGER.debug(f"Exported diagnostics to {output_file}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error(f"Error exporting diagnostics: {e}")

Running the Example Script
==========================

A complete working example is provided in ``examples/mqtt_diagnostics_example.py``.

**Usage:**

.. code-block:: bash

   NAVIEN_EMAIL=your@email.com NAVIEN_PASSWORD=password \
     python3 examples/mqtt_diagnostics_example.py

**What it does:**

- Runs for 1 hour collecting baseline data
- Exports JSON every 5 minutes to ``mqtt_diagnostics_output/``
- Logs all events to ``mqtt_diagnostics.log``
- Prints human-readable summaries every 5 minutes
- Can be interrupted with Ctrl+C

Expected Outcomes
=================

Based on your root cause, you should observe:

**If Network/NAT Timeout:**

- Drops decrease significantly after reducing keep-alive
- Session durations become more consistent
- Drops coincide with your network's NAT idle timeout interval

**If AWS Server-Side:**

- Consistent drop intervals (e.g., every 24 hours)
- CloudWatch metrics show connection limit approaching
- Drops occur regardless of keep-alive adjustment

**If Client Configuration:**

- Drops improve after applying hardened settings
- Session durations increase
- Reconnection becomes more reliable

**If Environmental/Device Issue:**

- Drops correlate with specific system events
- Different keep-alive values don't improve situation
- Fix the underlying system event

Investigation Checklist
=======================

- [ ] Enable diagnostics and run for 24+ hours
- [ ] Export JSON and inspect drop patterns (regular/random/message-triggered?)
- [ ] Check AWS CloudWatch for connection metrics and quota usage
- [ ] Monitor network (ping, TCP retransmit, packet loss, interface flaps)
- [ ] Check system logs for correlated events (suspend, cron, network changes)
- [ ] Test reduced keep-alive (start at 60s, adjust based on results)
- [ ] Verify reconnection attempts are recovering successfully
- [ ] Check for NAT timeout by testing different keep-alive intervals
- [ ] Profile system resources during drops (CPU, memory, network)
- [ ] Verify AWS credentials aren't expiring (token refresh working?)

See Also
========

- :doc:`/docs/DEVICE_STATUS_FIELDS` - Device status field reference
- :doc:`/docs/MQTT_CLIENT` - MQTT client API documentation

External Resources

- `AWS IoT Core Developer Guide <https://docs.aws.amazon.com/iot/latest/developerguide/>`_
- `AWS IoT Core Quotas <https://docs.aws.amazon.com/iot/latest/developerguide/mqtt-limits.html>`_
- `TCP Keep-Alive HOWTO <https://tldp.linux.org/HOWTO/TCP-Keepalive-HOWTO/>`_
- `MQTT Specification <https://mqtt.org/mqtt-5-0-specification>`_
