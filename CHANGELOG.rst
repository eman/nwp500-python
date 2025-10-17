=========
Changelog
=========

Version 1.2.2 (2025-10-17)
==========================

Fixed
-----

- Release version 1.2.2

Version 0.2 (Unreleased)
========================

Added
-----

- **Local/CI Linting Synchronization**: Complete tooling to ensure consistent linting results

  - Multiple sync methods: tox (recommended), direct scripts, pre-commit hooks, Makefile commands
  - CI-identical scripts: ``scripts/lint.py`` and ``scripts/format.py`` mirror ``tox -e lint`` and ``tox -e format``
  - Pre-commit hooks configuration for automatic checking
  - Comprehensive documentation: ``LINTING_SETUP.md``, ``DEVELOPMENT.md``, ``FIX_LINTING.md``
  - Makefile commands: ``make ci-lint``, ``make ci-format``, ``make ci-check``
  - Standardized ruff configuration across all environments
  - Eliminates "passes locally but fails in CI" issues
  - Cross-platform support (Linux, macOS, Windows, containers)
  
  - All MQTT operations (connect, disconnect, subscribe, unsubscribe, publish) use ``asyncio.wrap_future()`` to convert AWS SDK Futures to asyncio Futures
  - Eliminates "blocking I/O detected" warnings in Home Assistant and other async applications
  - Fully compatible with async event loops without blocking other operations
  - More efficient than executor-based approaches (no thread pool usage)
  - No API changes required - existing code works without modification
  - Maintains full performance and reliability of the underlying AWS IoT SDK
  - Safe for use in Home Assistant custom integrations and other async applications
  - Updated documentation with non-blocking implementation details

- **Event Emitter Pattern (Phase 1)**: Event-driven architecture for device state changes
  
  - ``EventEmitter`` base class with multiple listeners per event
  - Async and sync handler support
  - Priority-based execution order (higher priority executes first)
  - One-time listeners with ``once()`` method
  - Dynamic listener management with ``on()``, ``off()``, ``remove_all_listeners()``
  - Event statistics tracking (``listener_count()``, ``event_count()``)
  - ``wait_for()`` pattern for waiting on specific events
  - Thread-safe event emission from MQTT callback threads
  - Automatic state change detection for device monitoring
  - 11 events emitted automatically: ``status_received``, ``feature_received``, ``temperature_changed``, ``mode_changed``, ``power_changed``, ``heating_started``, ``heating_stopped``, ``error_detected``, ``error_cleared``, ``connection_interrupted``, ``connection_resumed``
  - NavienMqttClient now inherits from EventEmitter
  - Full backward compatibility with existing callback API
  - 19 unit tests with 93% code coverage
  - Example: ``event_emitter_demo.py``
  - Documentation: ``EVENT_EMITTER.rst``, ``EVENT_QUICK_REFERENCE.rst``, ``EVENT_ARCHITECTURE.rst``

- **Authentication**: Simplified constructor-based authentication
  
  - ``NavienAuthClient`` now requires ``user_id`` and ``password`` in constructor
  - Automatic authentication when entering async context manager
  - No need to call ``sign_in()`` manually
  - Breaking change: credentials are now required parameters
  - Updated all 18 example files to use new pattern
  - Updated all documentation with new authentication examples

- **MQTT Command Queue**: Automatic command queuing when disconnected
  
  - Commands sent while disconnected are automatically queued
  - Queue processed in FIFO order when connection is restored
  - Configurable queue size (default: 100 commands)
  - Automatic oldest-command-dropping when queue is full
  - Enabled by default for reliability
  - ``queued_commands_count`` property for monitoring
  - ``clear_command_queue()`` method for manual management
  - Integrates seamlessly with automatic reconnection
  - Example: ``command_queue_demo.py``
  - Documentation: ``COMMAND_QUEUE.rst``

- **MQTT Reconnection**: Automatic reconnection with exponential backoff
  
  - Automatic reconnection on connection interruption
  - Configurable exponential backoff (default: 1s, 2s, 4s, 8s, ... up to 120s)
  - Configurable max attempts (default: 10)
  - Connection state properties: ``is_reconnecting``, ``reconnect_attempts``
  - User callbacks for connection interruption and resumption events
  - Manual disconnect detection to prevent unwanted reconnection
  - ``MqttConnectionConfig`` with reconnection settings
  - Example: ``reconnection_demo.py``
  - Documentation: Added reconnection section to MQTT_CLIENT.rst

- **MQTT Client**: Complete implementation of real-time device communication
  
  - WebSocket MQTT connection to AWS IoT Core
  - Device subscription and message handling
  - Status request methods (device info, device status)
  - Control commands for device management
  - Topic pattern matching with wildcard support
  - Connection lifecycle management (connect, disconnect, reconnect)

- **Device Control**: Fully implemented and verified control commands
  
  - Power control (on/off) with correct command codes
  - DHW mode control (Heat Pump, Electric, Energy Saver, High Demand)
  - DHW temperature control with 20°F offset handling
  - App connection signaling
  - Helper method for display-value temperature control

- **Typed Callbacks**: 100% coverage of all MQTT response types
  
  - ``subscribe_device_status()`` - Automatic parsing of status messages into ``DeviceStatus`` objects
  - ``subscribe_device_feature()`` - Automatic parsing of feature messages into ``DeviceFeature`` objects
  - ``subscribe_energy_usage()`` - Automatic parsing of energy usage responses into ``EnergyUsageResponse`` objects
  - Type-safe callbacks with IDE autocomplete support
  - Comprehensive error handling and logging
  - Example scripts demonstrating usage patterns

- **Energy Usage API (EMS)**: Historical energy consumption data
  
  - ``request_energy_usage()`` - Query daily energy usage for specified month(s)
  - ``EnergyUsageResponse`` dataclass with daily breakdown
  - ``EnergyUsageTotal`` with percentage calculations
  - ``MonthlyEnergyData`` with per-day access methods
  - ``EnergyUsageData`` for individual day/month metrics
  - Heat pump vs. electric element usage tracking
  - Operating time statistics (hours)
  - Energy consumption data (Watt-hours)
  - Efficiency percentage calculations

- **Data Models**: Comprehensive type-safe models
  
  - ``DeviceStatus`` dataclass with 125 sensor and operational fields
  - ``DeviceFeature`` dataclass with 46 capability and configuration fields
  - ``EnergyUsageResponse`` dataclass for historical energy data
  - ``EnergyUsageTotal`` with aggregated statistics and percentages
  - ``MonthlyEnergyData`` with daily breakdown per month
  - ``EnergyUsageData`` for individual day/month metrics
  - ``OperationMode`` enum including STANDBY state (value 0)
  - ``TemperatureUnit`` enum (Celsius/Fahrenheit)
  - MQTT command structures
  - Authentication tokens and user info

- **API Client**: High-level REST API client
  
  - Device listing and information retrieval
  - Firmware information queries
  - Time-of-Use (TOU) schedule management
  - Push notification token management
  - Async context manager support
  - Automatic session management

- **Authentication**: AWS Cognito integration
  
  - Sign-in with email/password
  - Access token management
  - Token refresh functionality
  - AWS IoT credentials extraction for MQTT
  - Async context manager support

- **Documentation**: Complete protocol and API documentation
  
  - MQTT message format specifications
  - Energy usage query API documentation (EMS data)
  - API client usage guide
  - MQTT client usage guide
  - Typed callbacks implementation guide
  - Control command reference with verified command codes
  - Example scripts for common use cases
  - Comprehensive troubleshooting guides
  - Complete energy data reference (ENERGY_DATA_SUMMARY.md)

- **Examples**: Production-ready example scripts
  
  - ``device_status_callback.py`` - Real-time status monitoring with typed callbacks
  - ``device_feature_callback.py`` - Device capabilities and firmware info
  - ``combined_callbacks.py`` - Both status and feature callbacks together
  - ``mqtt_client_example.py`` - Complete MQTT usage demonstration
  - ``energy_usage_example.py`` - Historical energy usage monitoring and analysis
  - ``reconnection_demo.py`` - MQTT automatic reconnection demonstration
  - ``auth_constructor_example.py`` - Simplified authentication pattern

Changed
-------

- **Breaking**: Python version requirement updated to 3.9+
  
  - Minimum Python version is now 3.9 (was 3.8)
  - Migrated to native type hints (PEP 585): ``dict[str, Any]`` instead of ``Dict[str, Any]``
  - Removed ``typing.Dict``, ``typing.List``, ``typing.Deque`` imports
  - Cleaner, more readable code with modern Python features
  - Added Python version classifiers (3.9-3.13) to setup.cfg
  - Updated ruff target-version to py39

- **Breaking**: ``NavienAuthClient`` constructor signature
  
  - Now requires ``user_id`` and ``password`` as first parameters
  - Old: ``NavienAuthClient()`` then ``await client.sign_in(email, password)``
  - New: ``NavienAuthClient(email, password)`` - authentication is automatic
  - Migration: Pass credentials to constructor instead of sign_in()
  - All 18 example files updated to new pattern
  - All documentation updated with new examples

- **Documentation**: Major updates across all files
  
  - Fixed all RST formatting issues (title underlines, tables)
  - Updated authentication examples in 8 documentation files
  - Fixed broken documentation links (local file paths)
  - Removed "Optional Feature" and "not required for basic operation" phrases
  - Fixed table rendering in DEVICE_STATUS_FIELDS.rst
  - Fixed JSON syntax in code examples
  - Added comprehensive reconnection documentation
  - Added comprehensive command queue documentation
  - Cleaned up backward compatibility references (new library)

Fixed
-----

- **Critical Bug**: Thread-safe reconnection task creation from MQTT callbacks
  
  - Fixed ``RuntimeError: no running event loop`` when connection is interrupted
  - Fixed ``RuntimeWarning: coroutine '_reconnect_with_backoff' was never awaited``
  - Connection interruption callbacks run in separate threads without event loops
  - Implemented ``_start_reconnect_task()`` helper method to properly create reconnection tasks
  - Uses existing ``_schedule_coroutine()`` method for thread-safe task scheduling
  - Prevents crashes during automatic reconnection after connection interruptions
  - Ensures reconnection tasks are properly awaited and executed

- **Critical Bug**: Thread-safe event emission from MQTT callbacks
  
  - Fixed ``RuntimeError: no running event loop in thread 'Dummy-1'``
  - MQTT callbacks run in separate threads created by AWS IoT SDK
  - Implemented ``_schedule_coroutine()`` method for thread-safe scheduling
  - Event loop reference captured during ``connect()`` for cross-thread access
  - Uses ``asyncio.run_coroutine_threadsafe()`` for safe event emission
  - Prevents crashes when emitting events from MQTT message handlers
  - All event emissions now work correctly from any thread

- **Bug**: Incorrect method parameter passing in temperature control
  
  - Fixed ``set_dhw_temperature_display()`` calling ``set_dhw_temperature()`` with wrong parameters
  - Was passing individual parameters (``device_id``, ``device_type``, ``additional_value``)
  - Now correctly passes ``Device`` object as expected by method signature
  - Simplified implementation to just calculate offset and delegate to base method
  - Updated docstrings to match actual method signatures

- **Enhancement**: Anonymized MAC addresses in documentation
  
  - Replaced all occurrences of real MAC address (``04786332fca0``) with placeholder (``aabbccddeeff``)
  - Updated ``API_CLIENT.rst``, ``MQTT_CLIENT.rst``, ``MQTT_MESSAGES.rst``
  - Updated built HTML documentation files
  - Protects privacy in public documentation

- **Critical Bug**: Device control command codes
  
  - Fixed incorrect command code usage causing unintended power-off
  - Power-off now uses command code ``33554433``
  - Power-on now uses command code ``33554434``
  - DHW mode control now uses command code ``33554437``
  - Discovered through network traffic analysis of official app

- **Critical Bug**: MQTT topic pattern matching with wildcards
  
  - Fixed ``_topic_matches_pattern()`` to correctly handle ``#`` wildcard
  - Topics now match when message arrives on base topic (e.g., ``cmd/52/device/res``)
  - Topics also match subtopics (e.g., ``cmd/52/device/res/extra``)
  - Added length validation to prevent index out of bounds errors
  - Enables callbacks to receive messages correctly

- **Bug**: Missing ``OperationMode.STANDBY`` enum value
  
  - Added ``STANDBY = 0`` to ``OperationMode`` enum
  - Device reports mode 0 when tank is fully charged and no heating is needed
  - Added graceful fallback for unknown enum values
  - Prevents ``ValueError`` when parsing device status

- **Bug**: Insufficient topic subscriptions
  
  - Examples now subscribe to broader topic patterns
  - Subscribe to ``cmd/{device_type}/{device_topic}/#`` to catch all command messages
  - Subscribe to ``evt/{device_type}/{device_topic}/#`` to catch all event messages
  - Ensures all device responses are received

- **Enhancement**: Robust enum conversion with fallbacks
  
  - Added try/except blocks for all enum conversions in ``DeviceStatus.from_dict()``
  - Added try/except blocks for all enum conversions in ``DeviceFeature.from_dict()``
  - Unknown operation modes default to ``STANDBY``
  - Unknown temperature types default to ``FAHRENHEIT``
  - Prevents parsing failures from unexpected values

- **Documentation**: Updated MQTT_MESSAGES.rst with correct command codes and temperature offset

Verified
--------

- **Device Control**: Real-world testing with Navien NWP500 device
  
  - Successfully changed DHW mode from Heat Pump to Energy Saver
  - Successfully changed DHW mode from Energy Saver to High Demand
  - Successfully changed DHW temperature (discovered 20°F offset between message and display)
  - Commands confirmed to reach and control physical device
  - Documented in DEVICE_CONTROL_VERIFIED.md

Version 0.1
===========

- Initial Documentation
