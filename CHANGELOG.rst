=========
Changelog
=========

Version 6.1.0 (2025-12-03)
==========================

**BREAKING CHANGES**: Temperature API simplified with Fahrenheit input

This release fixes incorrect temperature conversions and provides a cleaner API
where users pass temperatures in Fahrenheit directly, with automatic conversion
to the device's internal format.

Changed
-------

- **``build_reservation_entry()``**: Now accepts ``temperature_f`` (Fahrenheit)
  instead of raw ``param`` value. The conversion to half-degrees Celsius is
  handled automatically.

  .. code-block:: python

     # OLD (removed)
     build_reservation_entry(..., param=120)
     
     # NEW
     build_reservation_entry(..., temperature_f=140.0)

- **``set_dhw_temperature()``**: Now accepts ``temperature_f: float`` (Fahrenheit)
  instead of raw integer. Valid range: 95-150°F.

  .. code-block:: python

     # OLD (removed)
     await mqtt.set_dhw_temperature(device, 120)
     
     # NEW
     await mqtt.set_dhw_temperature(device, 140.0)

Removed
-------

- **``set_dhw_temperature_display()``**: Removed. This method used an incorrect
  conversion formula (subtracting 20 instead of proper half-degrees Celsius
  encoding). Use ``set_dhw_temperature()`` with Fahrenheit directly.

Added
-----

- **``fahrenheit_to_half_celsius()``**: New utility function for converting
  Fahrenheit to the device's half-degrees Celsius format. Exported from the
  main package for advanced use cases.

  .. code-block:: python

     from nwp500 import fahrenheit_to_half_celsius
     
     param = fahrenheit_to_half_celsius(140.0)  # Returns 120

Fixed
-----

- **Temperature Encoding Bug**: Fixed ``set_dhw_temperature()`` which was using
  an incorrect "subtract 20" conversion instead of proper half-degrees Celsius
  encoding. This caused temperatures to be set incorrectly for values other
  than 140°F (where both formulas happened to give the same result).

Version 6.0.8 (2025-12-02)
==========================

Changed
-------

- **Maintenance Release**: Version bump for PyPI release

Version 6.0.7 (2025-11-30)
==========================

Added
-----

- **Documentation**: Added TOU (Time-of-Use) enable/disable command payload formats to protocol documentation

Version 6.0.6 (2025-11-24)
==========================

Added
-----

- **Field Descriptions**: Added comprehensive Field descriptions to ``DeviceStatus`` and ``DeviceFeature`` models with full documentation details including units, ranges, and usage context

Fixed
-----

- **Example Code**: Fixed ``device_status_callback.py`` example to use snake_case attribute names consistently
- **Field Descriptions**: Clarified distinctions between similar fields:
  
  - ``dhw_temperature_setting`` vs ``dhw_target_temperature_setting`` descriptions
  - ``freeze_protection_temp`` descriptions differ between DeviceStatus and DeviceFeature
  - ``eco_use`` descriptions differ between DeviceStatus (current state) and DeviceFeature (capability)

Version 6.0.5 (2025-11-21)
==========================

Fixed
-----

- **CRITICAL Temperature Conversion Bug**: Corrected temperature conversion formula for 8 sensor fields that were displaying values ~100°F higher than expected. The v6.0.4 change incorrectly used division by 5 (pentacelsius) instead of division by 10 (decicelsius) for these fields:
  
  - ``tank_upper_temperature`` - Water tank upper sensor
  - ``tank_lower_temperature`` - Water tank lower sensor
  - ``discharge_temperature`` - Compressor discharge temperature (refrigerant)
  - ``suction_temperature`` - Compressor suction temperature (refrigerant)
  - ``evaporator_temperature`` - Evaporator coil temperature (refrigerant)
  - ``ambient_temperature`` - Ambient air temperature at heat pump
  - ``target_super_heat`` - Target superheat setpoint
  - ``current_super_heat`` - Measured superheat value
  
  **Impact**: These fields now correctly display temperatures in expected ranges:
  
  - Tank temperatures: ~120°F (close to DHW temperature, not ~220°F)
  - Discharge temperature: 120-180°F (not 220-280°F)
  - Suction, evaporator, ambient: Now showing physically realistic values
  
  **Technical details**: Changed from ``PentaCelsiusToF`` (÷5) back to ``DeciCelsiusToF`` (÷10). The correct formula is ``(raw_value / 10.0) * 9/5 + 32``.

Changed
-------

- **Documentation**: Updated ``data_conversions.rst`` and ``device_status.rst`` to reflect correct ``DeciCelsiusToF`` conversion for refrigerant circuit and tank temperature sensors

Version 6.0.4 (2025-11-21)
==========================

Fixed
-----

- **Temperature Conversion Accuracy**: Corrected temperature conversion logic based on analysis of the decompiled mobile application. Previous conversions used approximations; new logic uses exact formulas from the app:
  
  - Replaced ``Add20`` validator with ``HalfCelsiusToF`` for fields transmitted as half-degrees Celsius
  - Replaced ``DeciCelsiusToF`` with ``PentaCelsiusToF`` for fields scaled by factor of 5
  - Affects multiple temperature sensor readings for improved accuracy

- **CLI Output Formatting**: Fixed formatting issues in command-line interface output

Changed
-------

- **Documentation**: Updated temperature conversion documentation to use precise 9/5 fraction instead of 1.8 approximation for clarity

Added
-----

- **Test Coverage**: Added ``tests/test_models.py`` to verify temperature conversion correctness

Version 6.0.3 (2025-11-20)
==========================

**BREAKING CHANGES**: Migration from custom dataclass-based models to Pydantic BaseModel implementations with automatic field validation and alias handling.

Removed
-------

- Removed legacy dataclass implementations for models (DeviceInfo, Location, Device, FirmwareInfo, DeviceStatus, DeviceFeature, EnergyUsage*). All models now inherit from ``NavienBaseModel`` (Pydantic).
- Removed manual ``from_dict`` constructors relying on camelCase key mapping logic.
- Removed field metadata conversion system (``meta()`` + ``apply_field_conversions()``) in favor of Pydantic ``BeforeValidator`` pipeline.

Changed
-------

- Models now use snake_case attribute names consistently; camelCase keys from API/MQTT are mapped automatically via Pydantic ``alias_generator=to_camel``.
- Boolean device fields now validated via ``DeviceBool`` Annotated type (device value 2 -> True, 0/1 -> False) replacing manual conversion code.
- Temperature offset (+20), scale division (/10) and decicelsius-to-Fahrenheit conversions implemented with lightweight ``BeforeValidator`` functions (``Add20``, ``Div10``, ``DeciCelsiusToF``) instead of post-processing.
- Enum parsing now handled directly by Pydantic; unknown values default safely via explicit Field defaults instead of try/except conversion loops.
- Field names updated (examples & docs) to snake_case: e.g. ``operationMode`` -> ``operation_mode``, ``dhwTemperatureSetting`` -> ``dhw_temperature_setting``.
- API typo handled using Field alias (``heLowerOnTDiffempSetting`` -> ``he_lower_on_diff_temp_setting``) rather than custom dictionary mutation.
- DeviceStatus conversion now performed on parse instead of separate transformation step, improving performance and reducing memory copies.
- Improved validation error messages from Pydantic on malformed payloads.
- Simplified energy usage model accessors; removed manual percentage methods duplication.

Added
-----

- Introduced ``NavienBaseModel`` configuring alias generation, population by name, and ignoring unknown fields for forward compatibility.
- Added structured Annotated types: ``DeviceBool``, ``Add20``, ``Div10``, ``DeciCelsiusToF`` for declarative conversion definitions.
- Added consistent default enum values directly in field declarations (e.g. ``operation_mode=STANDBY``).

Migration Guide (v6.0.2 -> v6.0.3)
----------------------------------

1. Replace any imports of dataclass models with Pydantic versions (paths unchanged). No code change required if you only accessed attributes.
2. Remove calls to ``Model.from_dict(data)``: Either use ``Model.model_validate(data)`` or continue calling ``from_dict`` where still provided (thin wrapper for backward compatibility on some classes). Preferred: ``DeviceStatus.model_validate(raw_payload)``.
3. Update attribute access to snake_case. Common mappings:
   - ``deviceInfo.macAddress`` -> ``device.device_info.mac_address``
   - ``deviceStatus.operationMode`` -> ``status.operation_mode``
   - ``deviceStatus.dhwTemperatureSetting`` -> ``status.dhw_temperature_setting``
   - ``deviceStatus.currentInletTemperature`` -> ``status.current_inlet_temperature``
4. Remove manual conversion code. Raw numeric values are converted automatically; stop adding +20 or dividing by 10 in user code.
5. Stop performing boolean normalization (``value == 2``) manually; attributes already return proper bools.
6. For enum handling, remove try/except wrappers; rely on defaulted fields (e.g. ``operation_mode`` defaults to ``STANDBY``).
7. If you previously mutated raw payload keys to snake_case, eliminate that transformation step.
8. If you logged intermediate converted dictionaries, you can access ``model.model_dump()`` for a fully converted representation.
9. Replace any custom validation logic with Pydantic validators or continue using existing patterns; most prior validation code is now unnecessary.
10. Energy usage: Access percentages via properties unchanged; object types now Pydantic models.

Quick Example
~~~~~~~~~~~~~

.. code-block:: python

   # OLD (v6.0.2)
   raw = mqtt_payload["deviceStatus"]
   converted = apply_field_conversions(DeviceStatus, raw)
   status = DeviceStatus(**converted)
   print(converted["dhwTemperatureSetting"] + 20)  # manual offset

   # NEW (v6.0.3)
   status = DeviceStatus.model_validate(mqtt_payload["deviceStatus"])
   print(status.dhw_temperature_setting)  # already includes +20 offset

   # OLD boolean and enum handling
   is_heating = converted["currentHeatUse"] == 2
   mode = CurrentOperationMode(converted["operationMode"]) if converted["operationMode"] in (0,32,64,96) else CurrentOperationMode.STANDBY

   # NEW simplified
   is_heating = status.current_heat_use
   mode = status.operation_mode

Benefits
~~~~~~~~

- Declarative conversions reduce 400+ lines of imperative transformation logic.
- Improved performance (single parse vs copy + transform).
- Automatic camelCase key mapping; less brittle than manual dict key copying.
- Rich validation errors for debugging malformed device messages.
- Cleaner, shorter model definitions with clearer intent.
- Easier extension: add new fields with conversion by combining Annotated + validator.

Version 6.0.2 (2025-11-15)
==========================

Fixed
-----

- DNS resolution in containerized environments using ThreadedResolver
- Updated AWS IoT library version
- Device status field conversions

Changed
-------

- Refactored ThreadedResolver session creation into helper method

Version 6.0.1 (2025-11-06)
==========================

Fixed
-----

- Minor bug fixes and improvements

Version 6.0.0 (2025-11-02)
==========================

**BREAKING CHANGES**: Removed constructor callbacks and backward compatibility re-exports

Removed
-------

- **Constructor Callbacks**: Removed ``on_connection_interrupted`` and ``on_connection_resumed`` constructor parameters from ``NavienMqttClient``
  
  .. code-block:: python
  
     # OLD (removed in v6.0.0)
     mqtt_client = NavienMqttClient(
         auth_client,
         on_connection_interrupted=on_interrupted,
         on_connection_resumed=on_resumed,
     )
     
     # NEW (use event emitter pattern)
     mqtt_client = NavienMqttClient(auth_client)
     mqtt_client.on("connection_interrupted", on_interrupted)
     mqtt_client.on("connection_resumed", on_resumed)

- **Backward Compatibility Re-exports**: Removed exception re-exports from ``api_client`` and ``auth`` modules
  
  .. code-block:: python
  
     # OLD (removed in v6.0.0)
     from nwp500.api_client import APIError
     from nwp500.auth import AuthenticationError, TokenRefreshError
     
     # NEW (import from exceptions module)
     from nwp500.exceptions import APIError, AuthenticationError, TokenRefreshError
     
     # OR (import from package root - recommended)
     from nwp500 import APIError, AuthenticationError, TokenRefreshError

- **Rationale**: Library is young with no external clients. Removing backward compatibility
  allows for cleaner architecture and prevents accumulation of legacy patterns.

Changed
-------

- **Migration Benefits**:
  
  - Multiple listeners per event (not just one callback)
  - Consistent API with other events (temperature_changed, mode_changed, etc.)
  - Dynamic listener management (add/remove listeners at runtime)
  - Async handler support
  - Priority-based execution
  - Cleaner imports (exceptions from one module)

- Updated ``examples/command_queue_demo.py`` to use event emitter pattern
- Updated ``examples/reconnection_demo.py`` to use event emitter pattern
- Updated ``examples/device_status_callback.py`` to import exceptions from correct module
- Updated ``examples/device_status_callback_debug.py`` to import exceptions from correct module
- Updated ``examples/device_feature_callback.py`` to import exceptions from correct module
- Updated ``examples/test_api_client.py`` to import exceptions from correct module
- Removed misleading "legacy state" comments from connection tracking code

Version 5.0.2 (2025-10-31)
==========================

Fixed
-----

- **MQTT Future Cancellation**: Fixed InvalidStateError exceptions during disconnect
  
  - Added asyncio.shield() to protect concurrent.futures.Future objects from cancellation
  - Applied consistent cancellation handling across all MQTT operations (connect, disconnect, subscribe, unsubscribe, publish)
  - AWS CRT callbacks can now complete independently without raising InvalidStateError
  - Added debug logging when operations are cancelled for better diagnostics
  - Ensures clean shutdown without spurious exception messages

Version 5.0.1 (2025-10-27)
==========================

Changed
-------

- **Maintenance Release**: Removed deprecated backward compatibility code

  - Removed ``CMD_*`` backward compatibility aliases from ``constants.py``
  - Removed ``cli.py`` backward compatibility wrapper module
  - Updated setup.cfg entry point to use ``nwp500.cli.__main__:run`` directly
  - Updated all examples to use ``CommandCode`` enum instead of ``CMD_*`` aliases
  - Updated examples to use standalone functions (``build_tou_period``, ``encode_price``, ``decode_price``, ``encode_week_bitfield``, ``decode_week_bitfield``) instead of ``NavienAPIClient.*`` static methods
  - Updated documentation to reference standalone functions
  - Fixed deprecated method name (``set_dhw_operation_setting`` → ``set_dhw_mode``)
  - Removed broken relative links from ``README.rst``
  - Added Read the Docs and GitHub links to ``README.rst`` header

Version 5.0.0 (2025-10-27)
==========================

**BREAKING CHANGES**: This release introduces a comprehensive enterprise exception architecture. 
See migration guide below for details on updating your code.

Added
-----

- **Enterprise Exception Architecture**: Complete exception hierarchy for better error handling

  - Created ``exceptions.py`` module with comprehensive exception hierarchy
  - Added ``Nwp500Error`` as base exception for all library errors
  - Added MQTT-specific exceptions: ``MqttError``, ``MqttConnectionError``, ``MqttNotConnectedError``, 
    ``MqttPublishError``, ``MqttSubscriptionError``, ``MqttCredentialsError``
  - Added validation exceptions: ``ValidationError``, ``ParameterValidationError``, ``RangeValidationError``
  - Added device exceptions: ``DeviceError``, ``DeviceNotFoundError``, ``DeviceOfflineError``, 
    ``DeviceOperationError``
  - All exceptions now include ``error_code``, ``details``, and ``retriable`` attributes
  - Added ``to_dict()`` method to all exceptions for structured logging
  - Added comprehensive test suite in ``tests/test_exceptions.py``
  - **Added comprehensive exception handling example** (``examples/exception_handling_example.py``)
  - **Updated key examples** to demonstrate new exception handling patterns

Changed
-------

- **Exception Handling Improvements**:

  - All exception wrapping now uses exception chaining (``raise ... from e``) to preserve stack traces
  - Replaced 19+ instances of ``RuntimeError("Not connected to MQTT broker")`` with ``MqttNotConnectedError``
  - Replaced ``ValueError`` in validation code with ``RangeValidationError`` and ``ParameterValidationError``
  - Replaced ``ValueError`` for credentials with ``MqttCredentialsError``
  - Replaced ``RuntimeError`` for connection issues with ``MqttConnectionError``
  - Enhanced ``AwsCrtError`` wrapping in MQTT code with proper exception chaining
  - Moved authentication exceptions from ``auth.py`` to ``exceptions.py``
  - Moved ``APIError`` from ``api_client.py`` to ``exceptions.py``
  - **CLI now handles specific exception types** with better error messages and user guidance

Migration Guide (v4.x to v5.0)
-------------------------------

**Breaking Changes Summary**:

The library now uses specific exception types instead of generic ``RuntimeError`` and ``ValueError``. 
This improves error handling but requires updates to exception handling code.

**1. MQTT Connection Errors**

.. code-block:: python

    # OLD CODE (v4.x) - will break
    try:
        await mqtt_client.request_device_status(device)
    except RuntimeError as e:
        if "Not connected" in str(e):
            await mqtt_client.connect()

    # NEW CODE (v5.0+)
    from nwp500 import MqttNotConnectedError, MqttError
    
    try:
        await mqtt_client.request_device_status(device)
    except MqttNotConnectedError:
        # Handle not connected - attempt reconnection
        await mqtt_client.connect()
        await mqtt_client.request_device_status(device)
    except MqttError as e:
        # Handle other MQTT errors
        logger.error(f"MQTT error: {e}")

**2. Validation Errors**

.. code-block:: python

    # OLD CODE (v4.x) - will break
    try:
        set_vacation_mode(device, days=35)
    except ValueError as e:
        print(f"Invalid input: {e}")

    # NEW CODE (v5.0+)
    from nwp500 import RangeValidationError, ValidationError
    
    try:
        set_vacation_mode(device, days=35)
    except RangeValidationError as e:
        # Access structured error information
        print(f"Invalid {e.field}: must be {e.min_value}-{e.max_value}")
        print(f"You provided: {e.value}")
    except ValidationError as e:
        # Handle other validation errors
        print(f"Validation error: {e}")

**3. AWS Credentials Errors**

.. code-block:: python

    # OLD CODE (v4.x) - will break
    try:
        mqtt_client = NavienMqttClient(auth_client)
    except ValueError as e:
        if "credentials" in str(e).lower():
            # handle missing credentials

    # NEW CODE (v5.0+)
    from nwp500 import MqttCredentialsError
    
    try:
        mqtt_client = NavienMqttClient(auth_client)
    except MqttCredentialsError as e:
        # Handle missing or invalid AWS credentials
        logger.error(f"Credentials error: {e}")
        await re_authenticate()

**4. Catching All Library Errors**

.. code-block:: python

    # NEW CODE (v5.0+) - catch all library exceptions
    from nwp500 import Nwp500Error
    
    try:
        # Any library operation
        await mqtt_client.request_device_status(device)
    except Nwp500Error as e:
        # All nwp500 exceptions inherit from Nwp500Error
        logger.error(f"Library error: {e.to_dict()}")
        
        # Check if retriable
        if e.retriable:
            await retry_operation()

**5. Enhanced Error Information**

All exceptions now include structured information:

.. code-block:: python

    from nwp500 import MqttPublishError
    
    try:
        await mqtt_client.publish(topic, payload)
    except MqttPublishError as e:
        # Access structured error information
        error_info = e.to_dict()
        # {
        #     'error_type': 'MqttPublishError',
        #     'message': 'Publish failed',
        #     'error_code': 'AWS_ERROR_...',
        #     'details': {},
        #     'retriable': True
        # }
        
        # Log for monitoring/alerting
        logger.error("Publish failed", extra=error_info)
        
        # Implement retry logic
        if e.retriable:
            await asyncio.sleep(1)
            await mqtt_client.publish(topic, payload)

**Quick Migration Strategy**:

1. Import new exception types: ``from nwp500 import MqttNotConnectedError, MqttError, ValidationError``
2. Replace ``except RuntimeError`` with ``except MqttNotConnectedError`` for connection checks
3. Replace ``except ValueError`` with ``except ValidationError`` for parameter validation
4. Use ``except Nwp500Error`` to catch all library errors
5. Test error handling paths thoroughly

**Benefits of New Architecture**:

- Specific exception types for specific errors (no more string matching)
- Preserved stack traces with exception chaining (``from e``)
- Structured error information via ``to_dict()``
- Retriable flag for implementing retry logic
- Better integration with monitoring/logging systems
- Type-safe error handling
- Clearer API documentation

Version 4.8.0 (2025-10-27)
==========================

Added
-----

- **Token Restoration Support**: Enable session persistence across application restarts

  - Added ``stored_tokens`` parameter to ``NavienAuthClient.__init__()`` for restoring saved tokens
  - Added ``AuthTokens.to_dict()`` method for serializing tokens (includes ``issued_at`` timestamp)
  - Enhanced ``AuthTokens.from_dict()`` to support both API responses (camelCase) and stored data (snake_case)
  - Modified ``NavienAuthClient.__aenter__()`` to skip authentication when valid stored tokens are provided
  - Automatically refreshes expired JWT tokens or re-authenticates if AWS credentials expired
  - Added 7 new tests for token serialization, deserialization, and restoration flows
  - Added ``examples/token_restoration_example.py`` demonstrating save/restore workflow
  - Updated authentication documentation with token restoration guide

- **Benefits**: Reduces API load, improves startup time, prevents rate limiting for frequently restarting applications (e.g., Home Assistant)

Version 4.7.1 (2025-10-27)
==========================

Changed
-------

- **Patch Release**: No code changes, updated version format to full semantic versioning

Version 4.7 (2025-10-27)
========================

Added
-----

- **MQTT Reconnection**: Two-tier reconnection strategy with unlimited retries
  
  - Implemented quick reconnection (attempts 1-9) for fast recovery from transient network issues
  - Implemented deep reconnection (every 10th attempt) with full connection rebuild and credential refresh
  - Changed default ``max_reconnect_attempts`` from 10 to -1 (unlimited retries)
  - Added ``deep_reconnect_threshold`` configuration parameter (default: 10)
  - Added ``has_stored_credentials`` property to ``NavienAuthClient``
  - Added ``re_authenticate()`` method to ``NavienAuthClient`` for credential-based re-authentication
  - Added ``resubscribe_all()`` method to ``MqttSubscriptionManager`` for subscription recovery
  - Deep reconnection now performs token refresh and falls back to full re-authentication if needed
  - Deep reconnection automatically re-establishes all subscriptions after rebuild
  - Connection now continues retrying indefinitely instead of giving up after 10 attempts

Improved
--------

- **Exception Handling**: Replaced 25 catch-all exception handlers with specific exception types
  
  - ``mqtt_client.py``: Uses ``AwsCrtError``, ``AuthenticationError``, ``TokenRefreshError``, ``RuntimeError``, ``ValueError``, ``TypeError``, ``AttributeError``
  - ``mqtt_reconnection.py``: Uses ``AwsCrtError``, ``RuntimeError``, ``ValueError``, ``TypeError``
  - ``mqtt_connection.py``: Uses ``AwsCrtError``, ``RuntimeError``, ``ValueError``
  - ``mqtt_subscriptions.py``: Uses ``AwsCrtError``, ``RuntimeError``, ``TypeError``, ``AttributeError``, ``KeyError``, ``ValueError``
  - ``mqtt_periodic.py``: Uses ``AwsCrtError``, ``RuntimeError``
  - ``events.py``: Retains ``Exception`` for user callbacks (documented as legitimate use case)
  - Added exception handling guidelines to ``.github/copilot-instructions.md``

- **Code Quality**: Multiple readability and safety improvements
  
  - Simplified nested conditions by extracting to local variables
  - Added ``hasattr()`` checks before accessing ``AwsCrtError.name`` attribute
  - Optimized ``resubscribe_all()`` to break after first failure per topic (reduces redundant error logs)
  - Fixed subscription failure tracking to use sets for unique topic counting
  - Improved code clarity with intermediate variables for complex boolean expressions

Fixed
-----

- **MQTT Reconnection**: Eliminated duplicate "Connection interrupted" log messages
  
  - Removed duplicate logging from ``mqtt_client.py`` (kept in ``mqtt_reconnection.py``)

Version 3.1.4 (2025-10-26)
==========================

Fixed
-----

- **MQTT Reconnection**: Fixed MQTT reconnection failures due to expired AWS credentials
  
  - Added AWS credential expiration tracking (``_aws_expires_at`` field in ``AuthTokens``)
  - Added ``are_aws_credentials_expired`` property to check AWS credential validity
  - Modified ``ensure_valid_token()`` to prioritize AWS credential expiration check
  - Triggers full re-authentication (not just token refresh) when AWS credentials expire
  - Preserves AWS credential expiration timestamps during token refresh
  - Prevents reconnection failures when connection interrupts after AWS credentials expire but before JWT tokens expire
  - Resolves AWS_ERROR_HTTP_WEBSOCKET_UPGRADE_FAILURE errors during reconnection attempts
  - Improved test coverage for auth module from 31% to 60% with comprehensive test suite

Version 3.1.3 (2025-10-24)
==========================

Fixed
-----

- **MQTT Reconnection**: Improved MQTT reconnection reliability with active reconnection
  
  - **Breaking Internal Change**: ``MqttReconnectionHandler`` now requires ``reconnect_func`` parameter (not Optional)
  - Implemented active reconnection that always recreates MQTT connection on interruption
  - Removed unreliable passive fallback to AWS IoT SDK automatic reconnection
  - Added automatic connection state checking during reconnection attempts
  - Now emits ``reconnection_failed`` event when max reconnection attempts are exhausted
  - Improved error handling and logging during reconnection process
  - Better recovery from WebSocket connection interruptions (AWS_ERROR_MQTT_UNEXPECTED_HANGUP)
  - Resolves issues where connection would fail to recover after network interruptions
  - Note: Public API unchanged - ``NavienMqttClient`` continues to work as before
  - Compatible with existing auto-recovery examples (``auto_recovery_example.py``, ``simple_auto_recovery.py``)

Version 3.1.2 (2025-01-23)
==========================

Fixed
-----

- **Authentication**: Fixed 401 authentication errors with automatic token refresh
  
  - Add automatic token refresh on 401 Unauthorized responses in API client
  - Preserve AWS credentials when refreshing tokens (required for MQTT)
  - Save refreshed tokens to cache after successful API calls
  - Add retry logic to prevent infinite retry loops
  - Validate refresh_token exists before attempting refresh
  - Use specific exception types (TokenRefreshError, AuthenticationError) in error handling
  - Prevents masking unexpected errors during token refresh
  - Resolves 'API request failed: 401' error when using cached tokens

Version 3.1.1 (2025-01-22)
==========================

Fixed
-----

- **MQTT Client**: Fixed connection interrupted callback signature for AWS SDK
  
  - Updated callback to match latest AWS IoT SDK signature: ``(connection, error, **kwargs)``
  - Fixed type annotations in ``MqttConnection`` for proper type checking
  - Resolves mypy type checking errors and ensures AWS SDK compatibility
  - Fixed E501 line length linting issue in connection interruption handler

Version 3.0.0 (Unreleased)
==========================

**Breaking Changes**

- **REMOVED**: ``OperationMode`` enum has been removed
  
  - This enum was deprecated in v2.0.0 and has now been fully removed
  - Use ``DhwOperationSetting`` for user-configured mode preferences (values 1-6)
  - Use ``CurrentOperationMode`` for real-time operational states (values 0, 32, 64, 96)
  - Migration was supported throughout the v2.x series

- **REMOVED**: Migration helper functions and deprecation infrastructure
  
  - Removed ``migrate_operation_mode_usage()`` function
  - Removed ``enable_deprecation_warnings()`` function
  - Removed migration documentation files (MIGRATION.md, BREAKING_CHANGES_V3.md)
  - All functionality available through ``DhwOperationSetting`` and ``CurrentOperationMode``

Version 2.0.0 (Unreleased)
==========================

**Breaking Changes (Planned for v3.0.0)**

- **DEPRECATION**: ``OperationMode`` enum is deprecated and will be removed in v3.0.0

  
  - Use ``DhwOperationSetting`` for user-configured mode preferences (values 1-6)
  - Use ``CurrentOperationMode`` for real-time operational states (values 0, 32, 64, 96)
  - See ``MIGRATION.md`` for detailed migration guide

Added
-----

- **Enhanced Type Safety**: Split ``OperationMode`` into semantically distinct enums

  - ``DhwOperationSetting``: User-configured mode preferences (HEAT_PUMP, ELECTRIC, ENERGY_SAVER, HIGH_DEMAND, VACATION, POWER_OFF)
  - ``CurrentOperationMode``: Real-time operational states (STANDBY, HEAT_PUMP_MODE, HYBRID_EFFICIENCY_MODE, HYBRID_BOOST_MODE)
  - Prevents accidental comparison of user preferences with real-time states
  - Better IDE support with more specific enum types

- **Migration Support**: Comprehensive tools for smooth migration

  - ``migrate_operation_mode_usage()`` helper function with programmatic guidance
  - ``MIGRATION.md`` with step-by-step migration instructions
  - Value mappings and common usage pattern examples
  - Backward compatibility preservation during transition

- **Documentation Updates**: Updated all documentation to reflect new enum structure

  - ``DEVICE_STATUS_FIELDS.rst`` updated with new enum types
  - Code examples use new enums with proper imports
  - Clear distinction between configuration vs real-time status

Changed
-------

- **DeviceStatus Model**: Updated to use specific enum types

  - ``operationMode`` field now uses ``CurrentOperationMode`` type
  - ``dhwOperationSetting`` field now uses ``DhwOperationSetting`` type
  - Maintains backward compatibility through value preservation

- **Example Scripts**: Updated to demonstrate new enum usage

  - ``event_emitter_demo.py`` updated to use ``CurrentOperationMode``
  - Fixed incorrect enum references (HEAT_PUMP_ONLY → HEAT_PUMP_MODE)
  - All examples remain functional with new type system

Deprecated
----------

- **OperationMode enum**: Will be removed in v3.0.0

  - All functionality preserved for backward compatibility
  - Migration guide available in ``MIGRATION.md``
  - Helper function ``migrate_operation_mode_usage()`` provides guidance
  - Original enum remains available during transition period

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
