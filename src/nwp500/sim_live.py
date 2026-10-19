"""Live sources for the simulator, and the composition of a scenario
from them.

A driver gets the simulator's inputs: the heater's state and its
schedules from the device, the air, the draws and the commands from its
caller. This module is that driver's part:

- the **source protocols** a driver composes. A source is anything with
  an ``async read()`` that returns one input: a ``HeaterReading``, the
  ``Schedules``, an ``Environment`` or the ``Loads``;
- ``Given``, a source of a value already in hand (a flag, a file);
- the live sources, ``LiveHeaterSource`` and ``LiveScheduleSource``,
  which read the device through the library's clients and build the
  inputs with ``nwp500.sim_adapters``;
- ``compose()``, which awaits the sources into a ``Scenario``.

An override is ``scenario.model_copy(update=...)`` on the result, so
scenario data can always stand in for the device's current state.

The device reports neither the weather nor the volume drawn: the air,
its humidity and the inlet come from another source
(``sim_home_assistant``, or ``Given``). Without one, or where it gives
no usable air, ``compose`` takes the heater's own reading of the air
at its intake (``sim_adapters.environment``).

A one-shot read cannot know the history the simulator asks for (when
the compressor last stopped, when the tank last heated): a composed
scenario leaves ``History`` unset, and the result names the defaults.

Example::

    from datetime import UTC, datetime, timedelta
    from nwp500 import sim, sim_live

    async def simulate_now(mqtt, api, device):
        composed = await sim_live.compose(
            start=datetime.now(UTC),
            horizon=timedelta(hours=24),
            tz="America/Los_Angeles",
            heater=sim_live.LiveHeaterSource(mqtt, device),
            schedules=sim_live.LiveScheduleSource(mqtt, api, device),
        )
        return sim.simulate(composed.scenario, composed.params)
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from nwp500 import sim_adapters as sa
from nwp500.exceptions import Nwp500Error
from nwp500.models import (
    DeviceFeature,
    DeviceStatus,
    ReservationSchedule,
    TOUInfo,
)
from nwp500.sim import (
    Commands,
    Environment,
    HeaterParams,
    HeaterState,
    Loads,
    Scenario,
    Schedules,
    Settings,
)

if TYPE_CHECKING:
    from nwp500.api_client import NavienAPIClient
    from nwp500.models import Device
    from nwp500.mqtt import NavienMqttClient

__author__ = "Emmanuel Levijarvi"
__copyright__ = "Emmanuel Levijarvi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)

#: How long a live source waits for the device's reply, seconds.
DEFAULT_TIMEOUT = 10.0


class LiveReadError(Nwp500Error):
    """A live source could not read what the scenario needs."""


class Source(Protocol[T_co]):
    """One input to a scenario, read when the driver composes it."""

    async def read(self) -> T_co:
        """The input, as of now."""
        ...


@dataclass(frozen=True)
class HeaterReading:
    """The heater, as one status and one feature read found it."""

    state: HeaterState
    settings: Settings
    #: The air at the heater's intake, as its status reported it.
    environment: Environment
    #: The default parameters for the heater's tank size; None when the
    #: device's feature info did not arrive.
    params: HeaterParams | None
    status: DeviceStatus
    feature: DeviceFeature | None


#: The sources ``compose`` takes.
HeaterSource = Source[HeaterReading]
ScheduleSource = Source[Schedules]
EnvironmentSource = Source[Environment]
LoadSource = Source[Loads]


@dataclass(frozen=True)
class Given(Source[T]):
    """A source of a value already in hand."""

    value: T

    async def read(self) -> T:
        """The value."""
        return self.value


@dataclass(frozen=True)
class Composed:
    """A scenario, and the parameters its heater reported (None when its
    feature info did not arrive)."""

    scenario: Scenario
    params: HeaterParams | None
    heater: HeaterReading


async def _reply[T](
    subscribe: Callable[[Any, Callable[[T], None]], Awaitable[Any]],
    unsubscribe: Callable[[Any, Callable[[T], None]], Awaitable[Any]],
    request: Callable[[Any], Awaitable[Any]],
    device: Device,
    timeout: float,
) -> T | None:
    """The first reply to ``request``, or None after ``timeout``. The
    ``request_*`` methods return a message id; the reply arrives through
    the subscription."""
    future: asyncio.Future[T] = asyncio.get_running_loop().create_future()

    def on_reply(reply: T) -> None:
        if not future.done():
            future.set_result(reply)

    await subscribe(device, on_reply)
    try:
        await request(device)
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        return None
    finally:
        await unsubscribe(device, on_reply)


async def read_status(
    mqtt: NavienMqttClient, device: Device, timeout: float = DEFAULT_TIMEOUT
) -> DeviceStatus:
    """The device's status. ``LiveReadError`` when none arrives."""
    status = await _reply(
        mqtt.subscribe_device_status,
        mqtt.unsubscribe_device_status,
        mqtt.request_device_status,
        device,
        timeout,
    )
    if status is None:
        raise LiveReadError(f"no device status within {timeout:g} s")
    return status


async def read_feature(
    mqtt: NavienMqttClient, device: Device, timeout: float = DEFAULT_TIMEOUT
) -> DeviceFeature | None:
    """The device's feature info, or None when none arrives."""
    return await _reply(
        mqtt.subscribe_device_feature,
        mqtt.unsubscribe_device_feature,
        mqtt.request_device_info,
        device,
        timeout,
    )


async def read_reservations(
    mqtt: NavienMqttClient, device: Device, timeout: float = DEFAULT_TIMEOUT
) -> ReservationSchedule:
    """The device's reservation schedule. ``LiveReadError`` when none
    arrives."""
    schedule = await _reply(
        mqtt.subscribe_reservation_response,
        mqtt.unsubscribe_reservation_response,
        mqtt.request_reservations,
        device,
        timeout,
    )
    if schedule is None:
        raise LiveReadError(f"no reservation schedule within {timeout:g} s")
    return schedule


class LiveHeaterSource:
    """The heater's state, settings and tank size, from one status and
    one feature read (``sim_adapters.heater_state``, ``settings`` and
    ``params``)."""

    def __init__(
        self,
        mqtt: NavienMqttClient,
        device: Device,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._mqtt = mqtt
        self._device = device
        self._timeout = timeout

    async def read(self) -> HeaterReading:
        """The heater now. ``LiveReadError`` when no status arrives; a
        missing feature info leaves ``params`` None."""
        status = await read_status(self._mqtt, self._device, self._timeout)
        feature = await read_feature(self._mqtt, self._device, self._timeout)
        if feature is None:
            _logger.warning(
                "No device feature info within %g s: the tank size is unknown",
                self._timeout,
            )
        return HeaterReading(
            state=sa.heater_state(status),
            settings=sa.settings(status),
            environment=sa.environment(status),
            params=None if feature is None else sa.params(feature),
            status=status,
            feature=feature,
        )


class LiveScheduleSource:
    """The heater's reservations (over MQTT), its TOU periods (REST,
    ``NavienAPIClient.get_tou_info``) and its TOU switch (its status).

    The device does not report the TOU period in force; the simulator
    derives it from the periods and the clock it is given.

    The TOU read needs the controller's serial number, from the feature
    info. When either does not arrive and TOU is on, the read fails
    (``LiveReadError``): a walk without the periods would ignore the
    heater's windows. With TOU off, the schedules have no periods, and
    a plan that turns TOU on needs them given.
    """

    def __init__(
        self,
        mqtt: NavienMqttClient,
        api: NavienAPIClient,
        device: Device,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._mqtt = mqtt
        self._api = api
        self._device = device
        self._timeout = timeout

    async def read(self) -> Schedules:
        """The schedules now."""
        status = await read_status(self._mqtt, self._device, self._timeout)
        reservations = await read_reservations(
            self._mqtt, self._device, self._timeout
        )
        tou_enabled = bool(status.tou_status)
        tou, why = await self._tou()
        if why is not None:
            if tou_enabled:
                raise LiveReadError(f"TOU is on, but {why}")
            _logger.warning("TOU periods not read (TOU is off): %s", why)
        return sa.schedules(
            reservations=reservations, tou=tou, tou_enabled=tou_enabled
        )

    async def _tou(self) -> tuple[TOUInfo | None, str | None]:
        """The TOU info, or why it could not be read."""
        feature = await read_feature(self._mqtt, self._device, self._timeout)
        if feature is None or not feature.controller_serial_number:
            return None, (
                "the controller serial number (feature info) did not "
                f"arrive within {self._timeout:g} s"
            )
        info = self._device.device_info
        try:
            tou = await self._api.get_tou_info(
                mac_address=info.mac_address,
                additional_value=info.additional_value,
                controller_id=feature.controller_serial_number,
            )
        # A REST error, a request that timed out, or a reply that is not
        # a TOU document (bad JSON, a model that does not validate).
        except (Nwp500Error, TimeoutError, ValueError) as e:
            return None, f"the TOU read failed: {e!r}"
        return tou, None


async def compose(
    *,
    start: datetime,
    horizon: timedelta,
    tz: str,
    heater: HeaterSource,
    schedules: ScheduleSource | None = None,
    environment: EnvironmentSource | None = None,
    loads: LoadSource | None = None,
    commands: Commands | None = None,
) -> Composed:
    """A scenario from ``start`` for ``horizon``, its local times in
    ``tz``, from the sources. Without ``schedules`` the heater has none;
    without ``environment`` the air is the heater's own reading, as it
    is when ``environment`` gives no usable air; without
    ``loads`` nothing is drawn; without ``commands`` nothing is
    written. The driver reads the clock for ``start``; nothing here
    does."""
    reading = await heater.read()
    env = reading.environment
    if environment is not None:
        env = await environment.read()
        if env.ambient_defaulted:
            env = env.model_copy(
                update={"ambient_f": reading.environment.ambient_f}
            )
    parts: dict[str, Any] = {
        "start": start,
        "horizon": horizon,
        "tz": tz,
        "state": reading.state,
        "settings": reading.settings,
        "environment": env,
    }
    if schedules is not None:
        parts["schedules"] = await schedules.read()
    if loads is not None:
        parts["loads"] = await loads.read()
    if commands is not None:
        parts["commands"] = commands
    return Composed(
        scenario=Scenario(**parts), params=reading.params, heater=reading
    )
