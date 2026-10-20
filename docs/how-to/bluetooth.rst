Read the Controller over Bluetooth
==================================

The NWP500 has a Bluetooth LE service that carries the controller's native
data protocol. The NaviLink app uses it to read device info and write
time-of-use plans, and Navien's service app uses it to read and change the
installer parameters (Installer Menu > Parameter Settings). The
:mod:`nwp500.ble` package speaks that protocol.

.. warning::

   This is installer-side access. Reads are harmless. Writes change
   controller settings directly and the parameter block layouts for the
   NWP500 are not mapped yet; :meth:`~nwp500.ble.NavienBleClient.write_block`
   is experimental and should only replay bytes you read from the same
   block with a deliberate change.
   :meth:`~nwp500.ble.NavienBleClient.write_tou_records` replaces the
   stored time-of-use plan and checks it by reading it back.

Install the extra
-----------------

.. code-block:: bash

   pip install 'nwp500-python[ble]'

Put the heater in pairing mode
------------------------------

With the heater off, hold the **Back** and **Power** buttons on the front
panel for five seconds. The heater then advertises over Bluetooth with a
name starting ``HPWH1``. Your computer needs to be within Bluetooth range
of the heater.

The heater's Wi-Fi setup mode (with the heater off, hold **M** and **OK**,
then hold **OK** on the Wi-Fi ready screen) also advertises, as
``HPWH4610``, under the same address and GATT service. It accepts a
connection but answers nothing, not even the device-info read. ``scan``
lists it, marked as the Wi-Fi setup mode, and ``read`` and ``nwp-cli``
pick an ``HPWH1`` heater over it.

Scan and read
-------------

.. code-block:: bash

   python -m nwp500.ble scan
   python -m nwp500.ble read --out blocks.json

``read`` connects to the strongest heater it hears and dumps every class
an NWP500 answers (:data:`nwp500.ble.NWP500_RESPONDING_CLASSES`, listed
below) as hex, with the CRC check result for each reply. Pass
``CLASS[:LENGTH]`` arguments to read particular classes instead, for
example ``SSD:59`` or ``TOU_PLAN``, or the boiler parameter blocks
(``SPID``, ``SPLD``, ``SPHD``, ``SPD``), which an NWP500 does not answer.
``read`` exits with status 1, and writes no ``--out`` file, when no class
answered.

From nwp-cli
------------

``nwp-cli`` reaches the heater through Navien's cloud (MQTT and REST)
unless told otherwise. ``--backend ble`` runs a command over Bluetooth
instead, with no sign-in. It needs the ``cli`` and ``ble`` extras:

.. code-block:: bash

   nwp-cli --backend ble serial
   nwp-cli --backend ble info
   nwp-cli --backend ble status
   nwp-cli --backend ble --ble-address AA:BB:CC:DD:EE:FF info --raw

Without ``--ble-address`` (or ``NAVIEN_BLE_ADDRESS``), it scans for ten
seconds and uses the strongest heater in pairing mode. ``serial``,
``info`` and ``status`` are the commands the heater can answer over
Bluetooth. ``info`` shows only what the ``DID`` and ``MSCD`` blocks hold:
serial numbers, model type, country code and the setpoint range, whose
lower end is Min Operation Temp. ``status`` shows only the decoded ``RTMD``
fields (see `Read live status`_). Every other command is refused before
connecting, since the heater accepts no settings changes over Bluetooth.

The commands run their usual handlers against
:class:`~nwp500.ble.BleMqttAdapter`, which offers the
:class:`~nwp500.NavienMqttClient` methods the heater can serve over
Bluetooth and raises :class:`~nwp500.ble.BleUnsupportedError` for the rest.
Where the MQTT client delivers a ``DeviceStatus``, the adapter delivers a
:class:`~nwp500.ble.RealTimeStatus`, and where it delivers a
``DeviceFeature``, a :class:`~nwp500.ble.BleDeviceFeature`. It has only the fields the blocks
carry, each checked against the heater's MQTT report: the controller
serial, the setpoint range, the model type, the country code and the
controller software code. Any other field raises :class:`AttributeError`
rather than reading as a default.

The block decoders use the cloud models' field names where a field was
matched against them. :class:`~nwp500.ble.DeviceInfoBlock` (``DID``) has
``dhw_temperature_min_raw``, ``dhw_temperature_max_raw``,
``model_type_code`` and ``country_code``; it is unrelated to
:class:`nwp500.models.DeviceInfo`, the cloud's device record.
:class:`~nwp500.ble.ControllerSerials` (``MSCD``) has
``controller_serial_number``, and :class:`~nwp500.ble.SoftwareInfoBlock`
(``MSWD``) has ``controller_sw_code``.

Temperatures convert as the cloud models do: ``BleDeviceFeature`` and
:meth:`~nwp500.ble.DeviceInfoBlock.min_operation_temperature` go through the
same half-degree conversion and follow ``--unit-system``
(:func:`nwp500.set_unit_system`). The blocks do not carry the heater's own
display unit, which the cloud path detects from the device, so without a
preference they are Fahrenheit. This was checked by switching the heater's
display between °F and °C: the cloud's ``temperatureType`` followed, and no
byte of any block the heater answers over Bluetooth changed.

What an NWP500 answers
----------------------

Checked against a unit on 2026-10-16, the heat pump answers reads of
these classes:
``SSD`` (17), ``EHD`` (32), ``TSD``/``TCD``/``TDD``/``TAD`` (38-41),
``TOU_PLAN`` (170, the stored time-of-use plan), ``SFHD`` (210), ``DID``
(240), ``MSCD`` (243) and ``MSWD`` (244). It does **not** answer the
parameter classes 51-54 that the service app uses on boilers, with any
expected length or sub-address, so its installer parameters live behind
a class the heat-pump-specific service app knows and this library does
not yet. :data:`nwp500.ble.NWP500_RESPONDING_CLASSES` lists the
responding set. Writing a block's own bytes back is answered as a read by
every one of them, but ``TOU_PLAN`` takes a write in its own format (see
`Write the time-of-use plan`_), so it is the one writable class
(:data:`nwp500.ble.NWP500_WRITABLE_CLASSES`). The boiler parameter classes
51-54 are not implemented on this controller at all.

Min Operation Temp is readable but not writable here: it is DID byte 17
(:meth:`~nwp500.ble.DeviceInfoBlock.min_operation_temperature`), confirmed equal
to the device's ``heatMinOpTemperature`` over MQTT. The writable parameter
class is selected from a per-model table the service app downloads from
Navien's server, so it is not reachable from this interface alone.

The address byte is ignored by every answering class except ``TOU_PLAN``,
where it is a slot index (see below).

Read the time-of-use plan
-------------------------

``TOU_PLAN`` holds the time-of-use plan the controller runs, as 16-byte
records with the fields of a cloud TOU interval: season and weekday
bitfields, start and end times, and prices scaled by ``10 **
decimal_point``. :meth:`~nwp500.ble.NavienBleClient.read_tou_records`
decodes them into :class:`~nwp500.models.TOUPeriod`, the model the MQTT
client and REST API use, so a plan read here compares directly with the
cloud's (for example with ``TOUPeriod.canonical()``). Checked on a unit,
the decoded intervals equal the cloud's copy of its plan.

The controller keeps the plan in a table of 40 slots, and a read names a
span of it. The address byte is the first slot, and the payload byte, which
the other classes treat as the expected length, is the last.
The reply holds ``16 * (last - first + 1)`` bytes, a count the controller
keeps in one byte, so it wraps past 255. A plain read of the class (payload
59) therefore returns slots 0-11 from address 0, and from address 12
nothing. Spans of more than 14 slots are never answered, since 240 bytes do
not fit in one notification. ``read_tou_records()`` reads the table in
three spans (:func:`~nwp500.ble.build_tou_read`) and returns every
interval. Checked on a unit, all twenty intervals of its plan equal the
cloud's copy. ``python -m nwp500.ble read`` prints the decoded plan under
the ``TOU_PLAN`` line.

Write the time-of-use plan
--------------------------

:meth:`~nwp500.ble.NavienBleClient.write_tou_records` stores a plan of up
to twelve intervals:

.. code-block:: python

   plan = await ble.read_tou_records()
   await ble.write_tou_records(plan[:4])

The write is the NaviLink app's: an 8-byte clock header (year, month, day,
weekday, time) and then the records, in the layout the controller returns
on a read (:func:`~nwp500.ble.build_tou_write`). The heater answers ``01``
when it stores them. On the unit checked it behaved as follows:

* The write goes into slots 0 onward and leaves later slots as they were.
  A second write at address 0 overwrites the first rather than
  continuing it. A write at any other address is answered with ``04`` and
  clears the whole table.
* A write of more than twelve records goes unanswered and changes
  nothing.
* A record of zeros, which is how the table marks an empty slot, makes the
  heater drop the whole write, so no Bluetooth write empties a slot.

So a plan cannot be shortened over Bluetooth: writing four intervals over
a stored plan of six would leave the last two running. The method
therefore reads the table first and raises
:class:`~nwp500.ble.TouWriteError` when the stored plan is longer than the
new one, so the example above only succeeds on a plan of four intervals
or fewer. After the write it reads the table back and raises the same
error if the heater refused or stored something else.

A plan of more than twelve intervals, or a shorter one replacing it, needs
the cloud: :meth:`~nwp500.NavienMqttClient.configure_tou_schedule`
replaces the whole plan. The heater does not report a Bluetooth write to
the cloud, so :meth:`~nwp500.NavienAPIClient.get_tou_info` keeps returning
the cloud's earlier copy. On the unit checked, a write into an empty table
also turned TOU scheduling on, and clearing the table turned it off; check
``tou_status`` afterwards. NaviLink's own Bluetooth path sends a longer
plan as several pages at address 0, which on this heater leaves only the
last page stored.

Read live status
----------------

The heater does not answer a read of the real-time monitoring class
(``RTMD``, 48). It pushes that block instead, once it receives the
class-50 session command 200 that Navien's service apps send on
connecting: a 156-byte block about every 300 ms. A read ends the stream:
the heater answers it and pushes no more blocks until the next command.
The service app's monitoring graph sends 202 for its Stop button, which on
the heater runs the stream at about one block a second instead, and 201
stops it.

:meth:`~nwp500.ble.NavienBleClient.read_status` starts the stream and
returns the newest block as a :class:`~nwp500.ble.RealTimeStatus`, and
starts the stream again when a read has ended it. It drops the first block
after each start, which on the unit checked held values from earlier. The decoded fields have the
:class:`~nwp500.models.DeviceStatus` names, raw encodings and conversions,
and each was checked against the same heater's MQTT status report
(2026-10-19):

==================================  ======  =================================
Field                               Offset  Encoding
==================================  ======  =================================
``operation_mode``                  0       ``CurrentOperationMode``
``current_statenum``                1       byte
``dhw_temperature_raw``             16-17   0.1 °C, rounded to half-degrees
``current_super_heat_raw``          18-19   0.1 °C + 500
``dhw_temperature_setting_raw``     35      half-degrees Celsius
``tank_upper_temperature_raw``      42-43   0.1 °C + 500
``tank_lower_temperature_raw``      44-45   0.1 °C + 500
``discharge_temperature_raw``       46-47   0.1 °C + 500
``suction_temperature_raw``         48-49   0.1 °C + 500
``evaporator_temperature_raw``      50-51   0.1 °C + 500
``ambient_temperature_raw``         52-53   0.1 °C + 500
``eev_step``                        80-81   steps
==================================  ======  =================================

Multi-byte fields are little-endian, and ``_raw`` fields hold the cloud's
encoding (0.1 °C for the thermistors). Checked in standby and while the heat pump ran. The rest of the block,
including the component flags and the energy figures, is not yet decoded
and is kept in ``raw``. ``read_status()`` waits up to 15 seconds for a
block (``timeout``), since the first one can take more than five.

.. code-block:: python

   async with NavienBleClient(address) as ble:
       info = await ble.read_device_info()  # before the stream starts
       status = await ble.read_status()
       print(status.tank_upper_temperature, status.ambient_temperature)

Read the DIP-switch block
-------------------------

``SSD`` (17) is not live status.
:meth:`~nwp500.ble.NavienBleClient.read_sub_status` decodes ``SSD`` into
:class:`~nwp500.ble.SubStatus`, with two 16-bit DIP-switch words, using
the layout the UK service toolkit reads on boilers. That layout is
unconfirmed on the heat pump. The toolkit expects a 60-byte block and an
NWP500 sends 59, and what each bit means is not known. The unit checked
read ``0x0004`` and ``0x0000``. ``python -m nwp500.ble read`` prints both
words under the ``SSD`` line.

From Python:

.. code-block:: python

   from nwp500.ble import ClassCode, NavienBleClient, scan

   found = await scan(10)
   address = found[0][0]
   async with NavienBleClient(address) as ble:
       info = await ble.read_device_info()
       serials = await ble.read_controller_serials()
       for record in await ble.read_tou_records():
           print(record.start_hour, record.end_hour, record.decoded_price_min)
       dip = await ble.read_sub_status()
       print(hex(dip.dip_switch_1), hex(dip.dip_switch_2))
       errors = await ble.read(ClassCode.EHD)
       print(errors.crc_ok, errors.data.hex())

``read()`` returns each reply as received, with ``crc_ok`` set. The
readers that decode a block (``read_device_info()``,
``read_controller_serials()``, ``read_sub_status()``, ``read_tou_records()``,
``read_parameter_blocks()``) raise
:class:`~nwp500.ble.CrcMismatchError` rather than decode a reply that
failed its checksum.

Locating a parameter
--------------------

The device reports the current installer values over MQTT
(``heatMinOpTemperature``, ``freezeProtectionTemperature``,
``antiLegionellaPeriod``, ``airFilterAlarmPeriod``). Once the class that
carries them is known, compare those values, in half-degrees Celsius for
temperatures, against the block bytes to find each parameter's offset.
A change is then a read of the block, one byte edited, and a
:meth:`~nwp500.ble.NavienBleClient.write_block` of that class, which is
how the service app applies parameter changes on boilers.

Protocol summary
----------------

* Service ``237339a3-b40d-4283-a629-f89bb838d85a``; write characteristic
  ``…d85c``; notifications on ``…d85b``; MTU 247.
* Advertised name: ``HPWH1…`` in pairing mode, or ``HPWH4610`` in Wi-Fi
  setup mode (answers nothing).
* Packet: ``F7 20 01 03`` + command (3 read / 16 write; replies 131 / 144)
  + length (payload + 2) + class + address + payload + CRC-16/MODBUS
  (low byte first).
* A read's payload is one byte, the expected reply length (58 for ``DID``,
  40 for ``MSCD``, 8 for ``SPID``, 59 for the other parameter blocks).
* A session command is a class-50 write of 30 bytes: the code, then
  zeros. Code 200 starts the ``RTMD`` stream, whose blocks arrive as
  command-16 packets.
