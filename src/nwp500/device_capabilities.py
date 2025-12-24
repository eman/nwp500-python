"""Device capability checking for MQTT commands.

This module provides a generalized framework for checking device capabilities
before executing MQTT commands. It uses a mapping-based approach to validate
that a device supports specific controllable features without requiring
individual checker functions.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from .exceptions import DeviceCapabilityError

if TYPE_CHECKING:
    from .models import DeviceFeature

__author__ = "Emmanuel Levijarvi"


# Type for capability check functions
CapabilityCheckFn = Callable[["DeviceFeature"], bool]


class MqttDeviceCapabilityChecker:
    """Generalized MQTT device capability checker using a capability map.

    This class uses a mapping of controllable feature names to their check
    functions, allowing capabilities to be validated in a centralized,
    extensible way without requiring individual methods for each control.
    """

    # Map of controllable features to their check functions
    # Capability names MUST match DeviceFeature attribute names exactly
    # for traceability: capability name -> DeviceFeature.{name}
    _CAPABILITY_MAP: dict[str, CapabilityCheckFn] = {
        "power_use": lambda f: bool(f.power_use),
        "dhw_use": lambda f: bool(f.dhw_use),
        "dhw_temperature_setting_use": lambda f: _check_dhw_temperature_control(
            f
        ),
        "holiday_use": lambda f: bool(f.holiday_use),
        "program_reservation_use": lambda f: bool(f.program_reservation_use),
        "recirculation_use": lambda f: bool(f.recirculation_use),
        "recirc_reservation_use": lambda f: bool(f.recirc_reservation_use),
        "anti_legionella_setting_use": lambda f: bool(
            f.anti_legionella_setting_use
        ),
    }

    @classmethod
    def supports(cls, feature: str, device_features: "DeviceFeature") -> bool:
        """Check if device supports control of a specific feature.

        Args:
            feature: Name of the controllable feature to check
            device_features: Device feature information

        Returns:
            True if feature control is supported, False otherwise

        Raises:
            ValueError: If feature is not recognized
        """
        if feature not in cls._CAPABILITY_MAP:
            valid_features = ", ".join(sorted(cls._CAPABILITY_MAP.keys()))
            raise ValueError(
                f"Unknown controllable feature: {feature}. "
                f"Valid features: {valid_features}"
            )
        return cls._CAPABILITY_MAP[feature](device_features)

    @classmethod
    def assert_supported(
        cls, feature: str, device_features: "DeviceFeature"
    ) -> None:
        """Assert that device supports control of a feature.

        Args:
            feature: Name of the controllable feature to check
            device_features: Device feature information

        Raises:
            DeviceCapabilityError: If feature control is not supported
            ValueError: If feature is not recognized
        """
        if not cls.supports(feature, device_features):
            raise DeviceCapabilityError(feature)

    @classmethod
    def register_capability(
        cls, name: str, check_fn: CapabilityCheckFn
    ) -> None:
        """Register a custom controllable feature check.

        This allows extensions or applications to define custom capability
        checks without modifying the core library.

        Args:
            name: Feature name
            check_fn: Function that takes DeviceFeature and returns bool
        """
        cls._CAPABILITY_MAP[name] = check_fn

    @classmethod
    def get_available_controls(
        cls, device_features: "DeviceFeature"
    ) -> dict[str, bool]:
        """Get all controllable features available on a device.

        Args:
            device_features: Device feature information

        Returns:
            Dictionary mapping feature names to whether they can be controlled
        """
        return {
            feature: cls.supports(feature, device_features)
            for feature in cls._CAPABILITY_MAP
        }


def _check_dhw_temperature_control(features: "DeviceFeature") -> bool:
    """Check if device supports DHW temperature control.

    Returns True if temperature control is enabled (not UNKNOWN or DISABLE).
    """
    from .enums import DHWControlTypeFlag

    return features.dhw_temperature_setting_use not in (
        DHWControlTypeFlag.UNKNOWN,
        DHWControlTypeFlag.DISABLE,
    )
