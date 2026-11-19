==================
Heater description
==================

``nwp500.heater`` describes the heater to a scheduler: the modes a plan
may carry, the setpoint range and step, and the device commands with
each key's type and range. Import it from ``nwp500.heater``; the
simulator's profile, ``nwp500.sim.profile.heater_profile``, is the
same description with the tank volume and the depletion threshold
added (:doc:`/how-to/simulate-heater`).

Build a device's profile
========================

Pass the device's features to take its own setpoint range. Without
them the range is the NWP500's, 104.9 to 149.9 degF.

.. code-block:: python

   from nwp500.heater import device_profile

   # feature: the DeviceFeature subscribe_device_feature delivered
   profile = device_profile(feature)

   profile.setpoint_min_f, profile.setpoint_max_f  # 104.9, 149.9
   profile.setpoint_step_unit, profile.setpoint_step  # "C", 0.5
   profile.revision  # a digest of every fact

The range is in degF whatever unit the library displays, read from the
feature's ``dhw_temperature_min_raw`` and ``dhw_temperature_max_raw``.
Any object with those two attributes, in half degrees Celsius, works in
place of a ``DeviceFeature``.

Modes
=====

``profile.modes`` lists every mode a plan may carry, in this order:

.. list-table::
   :header-rows: 1

   * - Name
     - Code
     - Sources
     - Modelled
   * - ``heat_pump``
     - 1
     - compressor
     - yes
   * - ``energy_saver``
     - 3
     - compressor, element
     - yes
   * - ``high_demand``
     - 4
     - compressor, element
     - yes
   * - ``electric``
     - 2
     - element
     - yes
   * - ``vacation``
     - 5
     - none
     - no
   * - ``power_off``
     - 6
     - none
     - no

The code is the ``DhwOperationSetting`` value the device takes and a
record holds. ``modelled`` is false for a mode the simulation does not
run: a write into it is dropped from a simulation with the reason
``write_mode_not_modelled``. ``profile.modelled_names`` gives the
modelled ones, ``profile.names`` all of them.

``profile.name_of(reported)`` names a mode the heater reported, given
as its device name (``"HIGH_DEMAND"``), a ``DhwOperationSetting`` or its
code (``4``, ``4.0``); it is None for Standby, which the device
reports but is never set. ``profile.effective(name, sources)`` says
whether the reported heat source shows a mode in effect, and is None
for a mode with no sources.

Commands
========

``COMMAND_KEYS`` maps each command a plan may carry to its keys and
their types. ``COMMAND_RANGES`` gives the inclusive range of each
whole-number key, and ``COMMAND_KEYS_ONLY_WITH`` the keys given only
with another key's value:

.. list-table::
   :header-rows: 1

   * - Command
     - Keys
   * - ``vacation``
     - ``days``: whole number, 1 to 99
   * - ``power``
     - ``on``: true or false
   * - ``anti_legionella``
     - ``enabled``: true or false; ``period_days``: whole number, 1 to
       30, given only with ``enabled: true``
   * - ``tou``
     - ``enabled``: true or false
   * - ``demand_response``
     - ``enabled``: true or false

The MQTT client's ``set_vacation_days`` and ``enable_anti_legionella``
check the same ranges.

The profile as a document
=========================

``profile.document()`` is the profile as a JSON-compatible document:
``profile.facts()`` and ``revision``.

.. code-block:: python

   doc = profile.document()
   doc["modes"][4]  # {"name": "vacation", "code": 5, "sources": [], "modelled": False}
   doc["command_keys"]["vacation"]  # {"days": {"type": "integer", "min": 1, "max": 99}}
   doc["setpoint_f"]  # {"min": 104.9, "max": 149.9}
   doc["revision"]

Each key in ``command_keys`` has a ``type``, ``integer`` or
``boolean``; a whole number has ``min`` and ``max``, and a key given
only with others has ``only_with``. ``tank_gal`` and
``depletion_threshold_f`` are null in a device's profile and set in the
simulator's. ``check(profile)`` raises ``ValueError`` for a profile
whose facts contradict each other.

API
===

.. automodule:: nwp500.heater
   :members: HeaterProfile, ProfileMode, device_profile, check,
      setpoint_range_f, command_key_facts, SetpointLimits, MODES,
      DEVICE_MODE_CODES, SOURCES, DEFAULT_MODE, ASSISTED_MODE,
      COMMAND_KEYS, COMMAND_RANGES, COMMAND_KEYS_ONLY_WITH, COMMANDS,
      VACATION_DAYS, ANTI_LEGIONELLA_PERIOD_DAYS, SETPOINT_MIN_F,
      SETPOINT_MAX_F, SETPOINT_STEP, SETPOINT_STEP_UNIT
