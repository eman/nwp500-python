Advanced Features Explained: Weather-Responsive Heating, Demand Response, and Tank Stratification
==================================================================================================

This document provides comprehensive technical documentation for three advanced NWP500 features.

Overview of Advanced Features
-----------------------------

The NWP500 heat pump water heater implements sophisticated algorithms for grid integration, environmental responsiveness, and efficiency optimization:

1. **Weather-Responsive Heating** - Adjusts heating strategy based on ambient temperature conditions
2. **Demand Response Integration** - Responds to grid signals for demand/response events (CTA-2045)
3. **Tank Stratification Optimization** - Uses dual temperature sensors for enhanced heating efficiency

Weather-Responsive Heating
==========================

Feature Overview
----------------

The device continuously monitors ambient air temperature to optimize heat pump performance and adjust heating strategies. This enables the system to maintain comfort while adapting to seasonal conditions automatically.

Technical Implementation
------------------------

**Data Sources**:

- ``ambientTemperature`` (decicelsius_to_f): Heat pump outlet air temperature measurement
- ``outsideTemperature`` (raw integer): Weather data temperature from cloud API/device configuration
- ``evaporatorTemperature`` (decicelsius_to_f): Evaporator coil temperature during heat pump operation


How It Works
------------

**Temperature Thresholds and Heating Adjustments**:

1. **High Ambient Temperature (>70°F / 21°C)**
   - Heat pump COP (Coefficient of Performance) is high
   - Device prioritizes heat pump operation over electric heating
   - Lower superheat targets for efficient operation
   - Reduced compressor activation frequency

2. **Moderate Ambient Temperature (50-70°F / 10-21°C)**
   - Balanced hybrid approach
   - Heat pump and electric elements coordinate
   - Optimal range for most climates
   - Device operates with default efficiency settings

3. **Cold Ambient Temperature (<50°F / 10°C)**
   - Heat pump efficiency decreases significantly
   - Device pre-charges tank before peak demand periods
   - Electric heating elements engage more frequently
   - At freezing (32°F / 0°C), COP drops 40-50% from optimal

4. **Extreme Cold (<20°F / -7°C)**
   - Heat pump operation becomes inefficient
   - Device may default to electric-only mode during these periods
   - Freeze protection mechanisms activate automatically
   - Recovery time increases significantly

**Algorithm Parameters**:

The device maintains internal target superheat values that adjust based on ambient conditions. Superheat represents the temperature difference between evaporator outlet and compressor suction:

.. code-block:: text

    Ideal superheat target: 10-20°F (5.5-11°C)
    
    Ambient 90°F:  Target = 12°F (easier to achieve)
    Ambient 60°F:  Target = 15°F (standard)
    Ambient 30°F:  Target = 18°F (challenging, may not be achievable)

**Compressor Control Adjustments**:

- **High Ambient**: Lower ON/OFF temperature setpoints, reduced cycle frequency
- **Low Ambient**: Higher ON/OFF temperature setpoints, increased cycle frequency
- **Recovery Override**: Pre-charging during known demand periods (morning peak)

Practical Applications
----------------------

**Morning Peak Scenario (40°F Ambient)**:

1. Device detects low ambient temperature overnight
2. If reservation calls for 140°F by 7 AM, device may start pre-charging at 5 AM
3. Uses both heat pump and electric elements (hybrid mode)
4. Reaches 140°F with hybrid approach, avoiding delay

**Cold Spell Scenario (20°F Ambient)**:

1. Device measures 20°F ambient, knows COP is ~1.8
2. Switches to electric-only mode if heating needed
3. Avoids inefficient heat pump cycles
4. Reduces overall energy consumption despite higher per-BTU cost

**Seasonal Optimization (Summer 90°F)**:

1. Device sees high ambient temperature
2. Enables heat pump operation even for small heating demand
3. Operates compressor at lower speeds for precise temperature control
4. Achieves 3.5+ COP (for every 1 kW electrical, 3.5 kW of heat)

Integration with MQTT Status Message
------------------------------------

The ``outsideTemperature`` field is transmitted in the device status update. Python clients can monitor this field:

.. code-block:: python

    # From device status updates
    status = await mqtt_client.get_status()
    
    # Access ambient temperature data
    outdoor_temp = status.outside_temperature  # Raw integer value
    measured_ambient = status.ambient_temperature  # Heat pump inlet measurement
    evaporator_temp = status.evaporator_temperature  # Coil temperature

Demand Response Integration (CTA-2045)
======================================

Feature Overview
----------------

The NWP500 supports demand response signals per the CTA-2045 (Consumer Technology Association) standard, enabling integration with smart grid programs and demand response events.

**CTA-2045 Standard**: 

A protocol that allows utilities to send control signals to networked devices (like water heaters) to manage demand during peak periods or grid stress conditions.

Technical Implementation
------------------------
DR Event Status Field
~~~~~~~~~~~~~~~~~~~~~

**Field**: ``drEventStatus`` (bitfield)

**Type**: Integer (bitfield, each bit represents a different DR signal)

**Values**:
- ``0``: No active DR events
- Non-zero: One or more DR signals active (specific bits depend on utility implementation)

**Typical Signal Meanings**:

.. list-table::
   :header-rows: 1
   :widths: 15 15 30 40

   * - Signal
     - Typical Cost
     - Expected Duration
     - Device Response
   * - Shed (Bit 0)
     - Very High
     - 30-60 minutes
     - Stop heating, reduce temperature
   * - Reduce (Bit 1)
     - High
     - 1-4 hours
     - Reduce heating, use heat pump only
   * - Normal (Bit 2)
     - Moderate
     - Continuous
     - Standard operation
   * - Pre-charge (Bit 3)
     - Low
     - 1-2 hours
     - Pre-heat tank before event
   * - Emergency (Bit 4)
     - Critical
     - Minutes to hours
     - Immediate halt/shutdown

**Example DR Event Sequence**:

.. code-block:: text

    Time    Event                           drEventStatus   Device Action
    ----    -----                           --------------   ----------------
    2:00 PM Grid operator predicts peak                     (Normal operation)
    2:30 PM Pre-charge signal issued       0b00001000       Start heating now
    3:00 PM Peak period begins             0b00000010       Stop heating, reduce
    3:30 PM Peak continues                 0b00000010       Heat pump only (low power)
    4:00 PM Peak period ends               0b00000001       Recover tank charge
    4:30 PM Normal operation restored      0b00000000       Resume standard schedule

DR Override Status Field
~~~~~~~~~~~~~~~~~~~~~~~~

**Field**: ``drOverrideStatus`` (integer flag)

**Purpose**: Tracks user-initiated overrides of demand response commands

**Values**:
- ``0``: No override active, device responding to DR commands
- Non-zero: Override active for specified period (typically up to 72 hours)

**User Override Scenario**:

1. Grid issues "shed" command (stop all heating)
2. Device would halt heating for 1 hour
3. User needs hot water for emergency task
4. User presses "Override" in mobile app
5. Device allows heating for next 30 minutes (or configured duration)
6. ``drOverrideStatus`` set to non-zero, indicating override active
7. After override period expires, device returns to DR command compliance

Implementation in Device Firmware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Decision Tree** (inferred from status fields):

.. code-block:: text

    IF drOverrideStatus != 0:
        Allow all heating operations
        Decrement override timer
    ELSE IF drEventStatus != 0:
        Determine signal type from drEventStatus bits
        Apply corresponding power reduction
        Adjust setpoints or compressor behavior
    ELSE:
        Execute normal reservation/TOU/mode schedule

**Practical Grid Integration Benefits**:

1. **Peak Shaving**: Reduce demand during 3-7 PM peak periods, saving 20-30% during those hours
2. **Rate Optimization**: Auto-respond to time-of-use pricing signals
3. **Grid Stability**: Participate in demand response events, earn utility incentives
4. **Cost Reduction**: Shift heating to low-price periods automatically

Utility Integration Requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To use demand response with your NWP500:


Tank Temperature Sensors
------------------------

**Upper Tank Sensor** (``tankUpperTemperature``)

- **Location**: Near tank top, typically 12-18" below top
- **Measurement**: ``decicelsius_to_f`` conversion (tenths of Celsius to Fahrenheit)
- **Typical Range**: 110-160°F (43-71°C)
- **Purpose**: Indicates hot water availability for immediate draw
- **Control Target**: Used to trigger upper electric heating element and upper heat pump stage

**Lower Tank Sensor** (``tankLowerTemperature``)

- **Location**: Near tank bottom, typically 6-12" above lowest point
- **Measurement**: ``decicelsius_to_f`` conversion (tenths of Celsius to Fahrenheit)
- **Typical Range**: 95-155°F (35-68°C)
- **Purpose**: Monitors bulk tank heating progress
- **Control Target**: Used to trigger lower electric heating element and lower heat pump stage

Tank Stratification Explained
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**What Is Stratification?**

In a vertical tank, naturally occurring density differences create layers:

.. code-block:: text

    155°F (68°C) ┌─────────────┐  ← Upper sensor (HOT)
                 │   Hot zone  │  
                 │   (stratif) │  Recently heated water
    120°F (49°C) ├─────────────┤  ← Dividing line (thermocline)
                 │ Warm zone   │  Transitional temperature
                 │             │
     95°F (35°C) ├─────────────┤  ← Lower sensor (COOL)
                 │  Cool zone  │  Being heated by compressor
                 └─────────────┘

**Why Stratification Matters**:

1. **Efficiency Benefit**: Thermostat setpoints work on upper sensor only until recovery needed
2. **Recovery Speed**: Lower element heating doesn't start until really needed (stratification maintained)
3. **Cost Savings**: Avoids unnecessary full-tank heating; only heats lower section when depleted
4. **User Comfort**: Upper zone always available at target temperature for draw

Practical Stratification Scenarios
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Scenario 1: Excellent Stratification (Efficient)**

.. code-block:: text

    Time    Upper Temp    Lower Temp    Differential    Status
    ----    ----------    ----------    -----------     --------
    9:00 AM   140°F         110°F          30°F         Good stratification
    9:15 AM   138°F         110°F          28°F         Still good (light draw)
    10:00 AM  140°F         112°F          28°F         Heat pump maintains lower
    
    → Device operates efficiently: upper element/HP just maintains top, lower recovers slowly
    → User gets hot water from top layer without full-tank heating

**Scenario 2: Poor Stratification (Inefficient)**

.. code-block:: text

    Time    Upper Temp    Lower Temp    Differential    Status
    ----    ----------    ----------    -----------     --------
    3:00 PM   100°F         98°F           2°F          Bad stratification
    3:30 PM   102°F         100°F          2°F          Tank too uniform
    4:00 PM   95°F          94°F           1°F          Almost no difference
    
    → Device detects poor stratification
    → Triggers full tank heating (both elements active)
    → Inefficient: heats entire volume instead of targeted zones
    → Recovery slower due to element capacity

**Scenario 3: Failed Sensor or Mixing Issue**

.. code-block:: text

    Time    Upper Temp    Lower Temp    Differential    Status
    ----    ----------    ----------    -----------     --------
    10:00 AM  155°F        160°F          -5°F          ERROR: Lower hotter than upper!
    
    → Impossible condition: lower can't be hotter than upper
    → Indicates failed sensor or severe mixing/circulation issue
    → Device may alert or switch to safety mode

Device Control Strategy Based on Stratification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Two-Stage Heating with Stratification**:

.. list-table::
   :header-rows: 1
   :widths: 15 20 20 45

   * - Condition
     - Upper Element
     - Lower Element
     - Device Action
   * - Upper <110°F, Lower <90°F
     - OFF
     - ON (primary)
     - Heat entire tank from bottom; creates stratification
   * - Upper 110-130°F, Lower <90°F
     - OFF
     - ON
     - Maintain stratification: let upper stay ready, heat lower
   * - Upper >130°F, Lower >120°F
     - OFF
     - OFF
     - Both satisfied, coast on heat retention
   * - Upper <100°F, Lower >120°F
     - ON (priority)
     - OFF
     - Restore top zone quickly (likely hot water draw)
   * - Upper ~Upper set, Lower <100°F
     - ON
     - ON
     - Full recovery needed; both elements heating

**Stratification Efficiency Gains**:

- **Upper heating only**: 15-25% less energy vs. full tank heating
- **Lower heating only**: 20-30% longer recovery time but 40-60% lower cost per cycle
- **Optimal**: ~25-30°F differential maximizes recovery time vs. efficiency tradeoff

Heat Pump Integration with Stratification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The two-stage control extends to heat pump operation:

- **Upper Heat Pump**: Activates when upper sensor drops below setpoint (quick, efficient recovery)
- **Lower Heat Pump**: Activates when lower sensor needs charging (low COP but maintains heating)

Modern control systems may use "superheat modulation" where:

- Heat pump adjusts compressor speed based on stratification degree
- Tighter superheat (more efficient) when stratification good
- Looser superheat (safer operation) when stratification poor

Monitoring Stratification from Python
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from nwp500.mqtt_client import NavienMQTTClient
    from nwp500.models import DeviceStatus
    
    async def monitor_stratification(mqtt_client: NavienMQTTClient, device_id: str):
        """Monitor tank stratification quality"""
        
        status = await mqtt_client.get_status(device_id)
        
        upper_temp = status.tank_upper_temperature  # float in °F
        lower_temp = status.tank_lower_temperature  # float in °F
        
        stratification_delta = upper_temp - lower_temp
        
        if stratification_delta < 5:
            print(f"WARNING: Poor stratification (Δ={stratification_delta}°F)")
            print("   → Full tank heating required")
            print("   → Efficiency reduced, recovery slower")
        elif stratification_delta > 25:
            print(f"GOOD: Excellent stratification (Δ={stratification_delta}°F)")
            print("   → Efficient targeted heating")
            print("   → Quick hot water availability")
        else:
            print(f"INFO: Normal stratification (Δ={stratification_delta}°F)")
            print("   → Balanced efficiency and recovery")
        
        return {
            'upper_temp': upper_temp,
            'lower_temp': lower_temp,
            'stratification_delta': stratification_delta,
            'quality': 'excellent' if stratification_delta > 25 else 'poor' if stratification_delta < 5 else 'normal'
        }

Factors Affecting Stratification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Positive Factors** (Preserve Stratification):

1. **Tank Insulation Quality**: Well-insulated tanks maintain temperature differences longer
2. **Slow Heating**: Gentle heating from bottom maintains distinct layers
3. **Low Draw Velocity**: Slow water draws don't turbulently mix layers
4. **Minimal Circulation**: Recirculation pumps can destroy stratification if running
5. **Vertical Tank Orientation**: Tall narrow tanks maintain stratification better than squat tanks

**Negative Factors** (Degrade Stratification):
    - Morning peak hour starting (6-7 AM)
    - Reservation calls for 140°F
    
    Device Decision:
    1. Weather-responsive: 25°F ambient → COP low, expect user needs
    2. Tank stratification: Delta only 5°F → full-tank heating needed
    3. Demand response: Reduce signal → lower compressor priority
    
    Action Taken:
    - Electric lower element activated (ignores DR, local override)
    - Heat pump compressor disabled (responds to DR reduce signal)
    - Target: Warm tank from bottom, allow sufficient top recovery
    - Result: 140°F achieved in 45 min (slower due to DR, but cold ambient expected)

Temperature Conversion Reference
================================

The NWP500 uses **half-degrees Celsius** encoding for temperature fields.

**Conversion Formulas**:

.. code-block:: text

    Half-degrees Celsius to Fahrenheit:
    fahrenheit = (raw_value / 2.0) * 9/5 + 32
    
    Examples:
    - Raw 70 → (70 / 2.0) * 9/5 + 32 = 95°F
    - Raw 98 → (98 / 2.0) * 9/5 + 32 ≈ 120°F
    - Raw 120 → (120 / 2.0) * 9/5 + 32 = 140°F
    - Raw 132 → (132 / 2.0) * 9/5 + 32 ≈ 150°F
    
    Inverse (Fahrenheit to raw):
    raw_value = (fahrenheit - 32) * 5/9 * 2

**Field Types**:

- **HalfCelsiusToF**: Most temperature fields (DHW, setpoints, freeze protection)
- **DeciCelsiusToF**: Sensor readings (tank sensors, refrigerant circuit)
  - Formula: ``fahrenheit = (raw_value / 10.0) * 9/5 + 32``

**Related Documentation**:

See :doc:`../protocol/data_conversions` for complete field conversion reference and formula applications.

Summary and Recommendations
============================

**Weather-Responsive Heating**:
- Automatically adapts heat pump efficiency based on ambient conditions
- Enables pre-charging for predictable demand peaks
- Monitors ambient via ``outsideTemperature`` field in device status
- Integrate ambient data into recovery time predictions

**Demand Response Integration**:
- Enables grid-aware operation and potential utility incentive payments
- Monitor ``drEventStatus`` and ``drOverrideStatus`` fields
- User can override DR events temporarily (up to 72 hours typical)
- Integrate DR status into user notifications and UI displays

**Tank Stratification Optimization**:
- Dual sensors enable smart two-stage heating
- Monitor stratification delta (upper - lower) for efficiency insights
- Target 20-30°F delta for optimal efficiency
- Alert users when stratification poor (indicates maintenance need)
- Use stratification data for predictive recovery time estimation

See Also
--------

* :doc:`../protocol/data_conversions` - Temperature field conversions (HalfCelsiusToF, DeciCelsiusToF)
* :doc:`../protocol/device_status` - Complete device status field reference
* :doc:`scheduling_features` - Reservation and TOU integration points
* :doc:`../python_api/models` - DeviceStatus model field definitions
