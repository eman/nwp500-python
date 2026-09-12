"""Installer diagnostics counters (``st/td/rd`` query).

The NaviLink app's installer screen requests these with command 16777228
on ``st/td/rd``. The device answers on ``res/td`` with packed hex strings;
the NaviLink cloud decodes them into JSON objects and republishes on
``res/td/rd`` **only when the response topic has the app's five-segment
form** ``cmd/{deviceType}/{homeSeq}/{userSeq}/{clientId}/res/td/rd``. The
library requests that form, so consumers receive the decoded objects.

Field names mirror the wire keys (including the vendor's misspellings,
which are kept as aliases). Units are not documented by the vendor; the
values that could be cross-checked against other device data are noted on
the fields. Everything is a raw integer counter.
"""

from typing import Any, Self, cast

from pydantic import Field

from .._base import NavienBaseModel

__all__ = [
    "DeviceDiagnostics",
    "DiagnosticsComponentCounters",
    "DiagnosticsDhwUsage",
    "DiagnosticsEventCounters",
]


class DiagnosticsEventCounters(NavienBaseModel):
    """Lifetime energy, age and fault counters (wire object ``tsData``)."""

    #: Lifetime heat pump energy in Wh. Matches the monthly energy query's
    #: ``total.hpUsage`` on the unit it was verified against.
    cumulated_pwr_hp: int = 0
    #: Lifetime heating element energy in Wh. Matches ``total.heUsage``.
    cumulated_pwr_he: int = 0
    days_since_installation: int = 0
    cumulated_occ_num_eco: int = 0
    cumulated_occ_num_dry_fire: int = 0
    #: Freeze-protection heating events. The wire key is misspelled.
    num_of_frost_protect_burn: int = Field(
        default=0, alias="numOffRostProtectBurn"
    )
    #: Condensate overflow events.
    cumulated_occ_num_con_ovr_flow: int = 0
    #: Water leak (overflow sensor) events.
    cumulated_occ_num_wtr_ovr_flow: int = 0
    cumulated_op_time_dr_shed: int = 0
    cumulated_op_time_dr_load_up: int = 0
    cumulated_op_time_dr_adv_load_up: int = 0
    cumulated_op_time_dr_cpp: int = 0
    cumulated_op_time_dr_grid_emg: int = 0
    #: Abnormal discharge temperature events.
    cumulated_occ_num_ab_dis_tmp: int = 0
    #: Heat pump operation errors.
    cumulated_occ_num_hpo: int = 0
    #: Abnormal suction temperature events.
    cumulated_occ_num_ab_suc_tmp: int = 0
    #: Abnormal discharge and suction temperature events.
    cumulated_occ_num_ab_dis_suc_tmp: int = 0


class DiagnosticsDhwUsage(NavienBaseModel):
    """Hot water draw statistics (wire object ``tdData``).

    All zero on the unit this was verified against, so the units of the
    flow and time fields are unknown.
    """

    #: The wire key is ``numOfdhwUse`` (lowercase ``dhw``).
    num_of_dhw_use: int = Field(default=0, alias="numOfdhwUse")
    dhw_use_total_flow: int = 0
    dhw_use_total_time: int = 0
    num_of_long_dhw_use: int = 0
    long_dhw_use_total_flow: int = 0
    long_dhw_use_total_time: int = 0
    num_of_short_dhw_use: int = 0
    #: The wire key is misspelled ``avrageRecoveryTime``.
    average_recovery_time: int = Field(default=0, alias="avrageRecoveryTime")


class DiagnosticsComponentCounters(NavienBaseModel):
    """Component run time and cycle counters (wire object ``taData``).

    ``cumulated_op_time_*`` values are hours: the compressor and upper
    element times match the monthly energy query's lifetime ``hpTime`` and
    ``heTime`` on the unit this was verified against. ``cumulated_op_num_*``
    values are start counts.
    """

    cumulated_op_time_comp: int = 0
    cumulated_op_num_comp: int = 0
    cumulated_op_time_eva_fan: int = 0
    cumulated_op_num_eva_fan: int = 0
    #: Electronic expansion valve steps.
    cumulated_op_step_eev: int = 0
    #: Upper heating element.
    cumulated_op_time_uhe: int = 0
    cumulated_op_num_uhe: int = 0
    #: Lower heating element.
    cumulated_op_time_lhe: int = 0
    cumulated_op_num_lhe: int = 0
    cumulated_op_num_shut_off_vv: int = 0
    mixing_valve_op_total_step: int = 0
    #: The wire key is misspelled ``mixingValveOpAvgMixinGrate``.
    mixing_valve_op_avg_mixing_rate: int = Field(
        default=0, alias="mixingValveOpAvgMixinGrate"
    )
    cumulated_op_num_recirc_pump: int = 0
    cumulated_op_time_recirc_pump: int = 0
    cumulated_op_time_inv_comp1: int = 0
    cumulated_op_time_inv_comp2: int = 0
    cumulated_op_time_inv_comp3: int = 0
    cumulated_op_time_inv_comp4: int = 0


class DeviceDiagnostics(NavienBaseModel):
    """Decoded ``res/td/rd`` response.

    The three counter blocks live under a ``data`` key on the wire; the
    validator lifts them to the top level. ``tcData`` is always an empty
    object on the NWP500 and is ignored.
    """

    device_type: int = 0
    mac_address: str = ""
    additional_value: str = ""
    type_of_td: int = Field(default=0, alias="typeOfTD")
    ts_data: DiagnosticsEventCounters = Field(
        default_factory=DiagnosticsEventCounters
    )
    td_data: DiagnosticsDhwUsage = Field(default_factory=DiagnosticsDhwUsage)
    ta_data: DiagnosticsComponentCounters = Field(
        default_factory=DiagnosticsComponentCounters
    )

    @classmethod
    def from_response(cls, response: dict[str, Any]) -> Self:
        """Build from the ``response`` object of a ``res/td/rd`` message."""
        data = response.get("data")
        merged: dict[str, Any] = {
            k: v for k, v in response.items() if k != "data"
        }
        if isinstance(data, dict):
            merged.update(cast(dict[str, Any], data))
        return cls.model_validate(merged)
