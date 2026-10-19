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

Install the extra
-----------------

.. code-block:: bash

   pip install 'nwp500-python[ble]'

Put the heater in pairing mode
------------------------------

Hold the **Back** and **Power** buttons on the front panel for five seconds.
The heater then advertises over Bluetooth with a name containing ``HPWH1``
until it is connected or pairing mode ends. Your computer needs to be within
Bluetooth range of the heater.

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

What an NWP500 answers
----------------------

Checked against a unit on 2026-10-16, the heat pump answers these classes:
``SSD`` (17), ``EHD`` (32), ``TSD``/``TCD``/``TDD``/``TAD`` (38-41),
``TOU_PLAN`` (170, the stored plan as 192 bytes), ``SFHD`` (210), ``DID``
(240), ``MSCD`` (243) and ``MSWD`` (244). It does **not** answer the
parameter classes 51-54 that the service app uses on boilers, with any
expected length or sub-address, so its installer parameters live behind
a class the heat-pump-specific service app knows and this library does
not yet. :data:`nwp500.ble.NWP500_RESPONDING_CLASSES` lists the
responding set. Every one of them is read-only: writing a block's own bytes
back is answered as a read (:data:`nwp500.ble.NWP500_WRITABLE_CLASSES` is
empty). The boiler parameter classes 51-54 are not implemented on this
controller at all.

Min Operation Temp is readable but not writable here: it is DID byte 17
(:meth:`~nwp500.ble.DeviceInfo.min_operation_temperature`), confirmed equal
to the device's ``heatMinOpTemperature`` over MQTT. The writable parameter
class is selected from a per-model table the service app downloads from
Navien's server, so it is not reachable from this interface alone.

The address byte is ignored by every answering class except ``TOU_PLAN``,
where it is a record index: the stored plan is twelve 16-byte records and a
read at address *N* returns the plan from record *N* on.

From Python:

.. code-block:: python

   from nwp500.ble import ClassCode, NavienBleClient, scan

   found = await scan(10)
   address = found[0][0]
   async with NavienBleClient(address) as ble:
       info = await ble.read_device_info()
       serials = await ble.read_controller_serials()
       status = await ble.read(ClassCode.SSD)
       print(status.crc_ok, status.data.hex())

``read()`` returns each reply as received, with ``crc_ok`` set. The
readers that decode a block (``read_device_info()``,
``read_controller_serials()``, ``read_parameter_blocks()``) raise
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
* Packet: ``F7 20 01 03`` + command (3 read / 16 write; replies 131 / 144)
  + length (payload + 2) + class + address + payload + CRC-16/MODBUS
  (low byte first).
* A read's payload is one byte, the expected reply length (58 for ``DID``,
  40 for ``MSCD``, 8 for ``SPID``, 59 for the other parameter blocks).
