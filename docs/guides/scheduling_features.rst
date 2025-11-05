Advanced Scheduling and Feature Enhancement Guide
=================================================

This guide documents advanced scheduling capabilities of the NWP500 and proposes enhancements for additional features. It also clarifies the interaction between different scheduling systems.

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
        "param": 120            # Temperature offset (raw value, add 20 to display)
                                # 120 raw = 140°F display
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

The ``param`` field stores temperature with an offset of 20°F:

.. code-block:: text

    Display Temperature → Raw Parameter Value
    95°F → 75 (95-20)
    120°F → 100 (120-20)
    140°F → 120 (140-20)
    150°F → 130 (150-20)

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

Proposed Feature Enhancements
-----------------------------

The following features would enhance the NWP500 capability but are not currently implemented:

1. Smart Energy Optimization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Machine learning-based heating optimization

**How it would work**:
- Device learns household hot water usage patterns (peak times, volumes)
- Automatically generates optimal reservation schedule
- Adapts schedule based on actual behavior month-to-month
- Reduces energy use by 5-15% without user intervention

**Implementation Difficulty**: High (requires ML model, device storage)

**Benefit**: Energy savings with zero user complexity

2. Weather-Responsive Heating
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Automatic performance adjustment based on ambient temperature

**How it would work**:
- Device adjusts compressor target superheat based on current ambient
- Pre-charges tank on cold mornings for better recovery
- Reduces heat pump operation in winter when COP is low (delegates to electric)
- Increases heat pump usage in summer when COP is high

**Current Capability**: Device receives ``outsideTemperature`` from API
**Missing**: Algorithm to respond proactively

**Benefit**: Improved efficiency across seasons (+10-20% winter efficiency improvement possible)

3. Demand Response Integration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Full integration with grid demand response programs

**Current State**: CTA-2045 signals supported but limited end-user documentation

**Enhancement**:
- Automatic pre-charging before predicted peak events
- Automated tank "cool-down" during peak periods
- User notifications of DR events with estimated cost/benefit
- Historical tracking of DR participation and savings

**Benefit**: Reduced electricity costs during peak, reduced grid strain, potential DR incentive payments

4. Hot Water Flow Prediction
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Predict when tank will be depleted and heating time needed

**How it would work**:
- Monitor current flow rate and tank charge %
- Estimate depletion time: ``time_to_depletion = tank_charge / current_flow_rate``
- Predict heating time needed: ``heat_time = available_energy / heating_power``
- Alert user if scheduled hot water demand exceeds capacity

**Benefit**: Prevent cold showers, enable proactive user actions

5. Recirculation System Optimization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Smart recirculation scheduling and flow control

**Current State**: Basic recirculation support; pump runs on timer

**Enhancement**:
- Adaptive flow rate based on time-of-day (high during morning peak, reduced during off-peak)
- Temperature-based recirculation (only recirculate if pipes cooling faster than target)
- Integration with TOU (disable recirculation during peak price periods)
- Cost tracking for recirculation energy usage

**Benefit**: Reduce recirculation energy waste, maintain comfort at lower cost

6. Predictive Maintenance Alerts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Anticipate failures before they occur

**How it would work**:
- Track compressor discharge temperature trends
- Monitor EEV step counts for refrigerant charge health
- Calculate COP (Coefficient of Performance) vs. baseline
- Alert when COP degradation suggests refrigerant leak or blockage

**Example Alert**: "Heat pump COP has degraded 20% - refrigerant leak suspected. Service recommended."

**Benefit**: Prevent catastrophic failures, reduce repair costs

7. Seasonal Mode Automation
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Automatically adjust strategies based on season

**How it would work**:
- Winter mode: Aggressive electric element use (COP low), precharge for peak demand
- Spring/Fall: Balanced hybrid operation
- Summer: Heat pump only, defer heating to off-peak TOU periods

**Implementation**: Settings profiles + seasonal triggers

**Benefit**: Optimized efficiency year-round without user adjustment

8. Historical Energy Analytics
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Track and analyze energy consumption patterns

**Metrics**:
- Daily/weekly/monthly consumption by mode (heat pump vs. electric)
- COP measurement for heat pump efficiency
- Cost per gallon estimates
- Comparison to baseline usage

**Display**: Charts, trends, anomaly detection

**Benefit**: Identify efficiency issues, validate savings claims

9. Tank Stratification Optimization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Use tank sensor stratification data for smarter heating

**Current State**: Device measures both upper and lower temps but rarely exposed to user

**Enhancement**:
- Preferentially heat lower tank during off-peak (more energy capacity)
- Reserve upper tank heating for peak demand (faster recovery)
- Detect and alert on failed stratification (sensors too close together)

**Benefit**: Reduce heating time during peak periods

10. User Comfort Profiles
^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Pre-configured operating profiles for common scenarios

**Profiles**:
- "Budget Conscious": Minimal heating, aggressive TOU optimization
- "Family": Higher capacity, faster recovery, predictable peak times
- "Eco": Aggressive heat pump, minimal electric heating, vacation-friendly
- "Luxury": Always-hot, immediate response, highest comfort
- "Hybrid Work": Mid-week heat pump, weekday evening prep, weekend high capacity

**Benefit**: One-tap optimization without learning technical details

11. Multi-Unit Coordination
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Coordinate operation of multiple water heaters (e.g., dual-tap or master/slave)

**How it would work**:
- Coordinate tank charge levels across units
- Distribute load to balance wear
- Prioritize active-use unit during peak demand
- Cascade heating when first unit insufficient

**Benefit**: Better efficiency with multiple units, extended lifespan

12. Export/Import Schedules
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Feature**: Share and import reservation/TOU schedules

**Use Cases**:
- Share optimized schedules between users
- Import manufacturer-recommended profiles
- Community-contributed schedules for specific tariffs
- A/B testing different schedules

**Benefit**: Faster optimization, community knowledge sharing

Implementation Roadmap
----------------------

Priority-based implementation suggestions:

**Phase 1 (High-Priority, Quick Win)**
1. Improve existing TOU/Reservation documentation (DONE in this guide)
2. Weather-responsive parameter suggestions to user
3. Historical energy analytics (basic tracking)

**Phase 2 (High-Impact, Medium Effort)**
1. Demand Response full documentation + notification system
2. Predictive maintenance alerts (discharge temp trend analysis)
3. Seasonal mode automation profiles

**Phase 3 (Advanced, High-Value)**
1. ML-based energy optimization
2. Hot water depletion prediction
3. Multi-unit coordination framework

**Phase 4 (Long-term, Ecosystem Features)**
1. Schedule import/export marketplace
2. User community profiles and sharing
3. Integration with home automation platforms

See Also
--------

* :doc:`reservations` - Quick start for reservation setup
* :doc:`time_of_use` - TOU pricing details and OpenEI integration
* :doc:`../protocol/data_conversions` - Understanding temperature and power fields
* :doc:`auto_recovery` - Handling temporary connectivity issues
