"""Default parameters, by tank size.

Every value comes from one NWP500-65 on 240 V: its parameters as fitted
on 2026-10-11 from its own record, with the constants measured by
targeted device runs and the engineering constants the fit assumes
(each field's ``Provenance`` says which: ``provenance_of``). The 50 and
80 gal models get the same parameters with the tank's volume scaled by
rated storage, and nothing else: their compressor, elements, jacket
loss and controller are the 65's until one of them is measured.

The fit is one unit's, in one place, and part of it describes that
place rather than the heater (``params.Scope``): the draw terms were
fitted through its mixing valve, on its mains and its household's
draws. ``site_example_params`` is that installation whole;
``default_params`` is the same heater with **no mixing valve**, the one
draw setting with no fitted numbers in it, which errs the safe way for
a valve owner who leaves it unset (every gallon charged as tank water,
depletion called early), and the rating test's mains (``RATING_INLET_F``)
in place of that installation's. A caller with its own calibration, a
valve or its own climate (``DrawParams.climate_f``) passes its own
``HeaterParams``.
"""

from dataclasses import replace

from nwp500.sim.params import (
    INSTALLATION_TERMS,
    CirculationParams,
    CompressorParams,
    ControllerParams,
    DrawParams,
    ElementParams,
    HeaterParams,
    LossParams,
    TankParams,
)
from nwp500.sim.physics.draw import DEFAULT_INLET_TEMP_F

#: The device's ``volume_code``: NWP500-50, -65 and -80.
VOLUME_50 = 1
VOLUME_65 = 2
VOLUME_80 = 3

#: Rated storage volume by model, gallons: the manual's specification
#: table (45.2, 63.2 and 76.1 for the 50, 65 and 80 gal models).
RATED_GAL = ((VOLUME_50, 45.2), (VOLUME_65, 63.2), (VOLUME_80, 76.1))

#: One installation's thermostatic mixing valve: delivered water at
#: 53.56 + 0.485 × the upper zone, °F, never above the tank. Measured
#: from five plateaus at a gauge on its outlet, 2026-09-16/17.
SITE_VALVE = (53.56, 0.485)
#: No mixing valve: the tap gets the tank's own water.
NO_VALVE = (0.0, 1.0)

#: The mains of the federal rating test for water heaters (10 CFR 430,
#: Subpart B, Appendix E), °F: colder than most of the year's mains
#: south of the northern tier, so the draws it prices err the safe way.
RATING_INLET_F = 58.0
#: The installation's climate (``DrawParams.climate_f``): its weather
#: station's monthly means over 2025-11 to 2026-10
#: (``cold_supply.climate_of``), a year's mean air of 61.3 °F and a
#: swing of 19.9 °F between its warmest and coldest month. Its mains
#: by the day read 1.5 °F under the plateaus of its inlet probe on 25
#: days of 2026-09-20 to 10-28.
SITE_CLIMATE = (61.3, 19.9)

#: The installation's circulation: 1.397 gal/min (the median over the
#: 14 days before a retrain). The run model's three terms are fitted together
#: (``calibration.fit_return``) on 123 runs with the compressor off,
#: 2026-04-04 to 2026-10-24: the return rests 7.84 °F above the heater's
#: air, and the pipe a run warmed cools back to rest on 0.464 h. The
#: 19.36 gal is an effective volume, just under the longest measured
#: run (19.8 gal), which sets it: the record's long runs never brought
#: hot water back (the return still 17 to 38 °F under the tank after 16
#: to 20 gal), so a run takes heat as long as it runs, and the typical
#: 4 min run (5.9 gal) is under it.
SITE_CIRCULATION = CirculationParams(
    displaced_gal=19.36,
    flow_gpm=1.397,
    return_rest_offset_f=7.84,
    return_cool_tau_h=0.464,
    # Its household meter read a run at 0.81 of the run's own flow
    # (median of 47 runs), but the flow a history's replay takes is the
    # household's draws alone (``sim_home_assistant`` reads them from
    # the draw detector), which no run passes.
    meter_share=0.0,
)


def _nwp500_65() -> HeaterParams:
    """The NWP500-65's parameters."""
    return HeaterParams(
        # The layered tank fitted on its record, 2026-04-16 to
        # 2026-10-26 (``sim_calibrate.calibrate_changes``): 266 quiet
        # windows, 254 metered draws and 118 recoveries, each started
        # from the day's replay before it, the compressor's start
        # stirring the layers (``physics.stratified.stir``) and no hold
        # imposed.
        tank=TankParams(
            volume_gal=63.2,
            layers=12,
            upper_probe_height=0.901813885380396,
            lower_probe_height=0.46296408131161204,
            upper_probe_spread_gal=5.971337972581407,
            lower_probe_spread_gal=2.0635540925212172,
            lower_probe_offset_f=1.008459895282938,
            condenser_span=(0.14307729589423623, 0.3508032644394711),
            inlet_mix_gal=14.330242694663644,
            conductance_btu_hr_f=0.49547263784845164,
        ),
        loss=LossParams(
            ua_side_btu_hr_f=3.139115014260317,
            ua_bottom_btu_hr_f=0.1675409344227829,
            ua_top_btu_hr_f=0.553916158090328,
        ),
        # The performance map and run-on fitted on its record,
        # 2025-12-28 to 2026-10-26 (``heat_pump_fit.fit_heat_pump``),
        # the heat against the two-zone tank's loss: refitted against
        # the loss above, from 2026-04-16, it moves 0.05 % at 65 °F air
        # and 120 °F water and under 0.2 % across its span (4,497
        # BTU/h, +55.5 per °F of air, -16.1 per °F of water).
        compressor=CompressorParams(
            heat_btu_h=4499.436604500702,
            heat_btu_h_per_air_f=55.49795247502065,
            heat_btu_h_per_water_f=-15.948333659761246,
            heat_btu_h_per_air_water_f=0.0,
            power_w=401.7270566837221,
            power_w_per_air_f=0.21405638109110056,
            power_w_per_water_f=2.8460496649489793,
            power_w_per_air_water_f=0.0,
            heat_domain_air_f=(61.0, 89.0),
            heat_domain_water_f=(114.0, 144.0),
            power_domain_air_f=(45.0, 90.0),
            power_domain_water_f=(73.0, 148.0),
            start_hold_after_min=(15.0, 60.0, 180.0, 720.0),
            start_hold_min=(0.0, 0.0, 0.0, 0.0, 0.0),
        ),
        element=ElementParams(
            element_w=5148.0,
            upper_starts_below_setpoint_f=0.54,
            high_demand_starts_below_setpoint_f=0.72,
            start_bracket_lower_f=0.0,
            high_demand_bracket_lower_f=0.36,
            upper_reengages_below_setpoint_f=4.1,
            energy_saver_reengages_at_f=104.9,
            energy_saver_entry_deficit_f=1.8,
            energy_saver_bracket_lower_f=1.44,
            energy_saver_upper_off_below_setpoint_f=1.62,
            upper_dead_time_min=1.21,
        ),
        draw=DrawParams(
            delivery_intercept_f=53.56,
            delivery_slope=0.485,
            inlet_temp_f=DEFAULT_INLET_TEMP_F,
            inlet_from_probe=True,
            climate_f=SITE_CLIMATE,
        ),
        controller=ControllerParams(
            write_start_lag_s=30.0,
            restart_lockout_s=330.0,
            window_write_starts_f=4.0,
            mode_write_starts_f=2.0,
            mode_write_lower_starts_f=3.6,
            energy_saver_write_seen_f=1.44,
            tou_cap_f=3.6,
            hp_stop_overshoot_f=0.9,
        ),
    )


def with_valve(
    params: HeaterParams, valve: tuple[float, float]
) -> HeaterParams:
    """``params`` with the mixing valve ``(intercept_f, slope)``:
    delivered water at ``intercept_f + slope × upper``, never above the
    tank; ``NO_VALVE`` for none: the draw terms' line."""
    intercept, slope = valve
    return replace(
        params,
        draw=replace(
            params.draw, delivery_intercept_f=intercept, delivery_slope=slope
        ),
    )


def default_params(volume_code: int = VOLUME_65) -> HeaterParams:
    """The default parameters for a tank of ``volume_code`` (the
    device's: 1 for 50 gal, 2 for 65, 3 for 80): ``site_example_params``
    with no mixing valve (``NO_VALVE``), no circulation and the rating
    test's mains all year (``RATING_INLET_F``, no climate). Every other
    installation term is still that site's, labelled so
    (``params.scope_of``) and named in ``unfitted``
    (``INSTALLATION_TERMS``), so every answer they reach says
    ``draw_uncalibrated`` until your own meter fits them."""
    site = with_valve(site_example_params(volume_code), NO_VALVE)
    return replace(
        site,
        draw=replace(
            site.draw,
            inlet_temp_f=RATING_INLET_F,
            inlet_from_probe=False,
            climate_f=None,
        ),
        circulation=None,
        unfitted=INSTALLATION_TERMS,
    )


def site_example_params(volume_code: int = VOLUME_65) -> HeaterParams:
    """One NWP500-65 installation's parameters, its mixing valve
    (``SITE_VALVE``) and circulation (``SITE_CIRCULATION``) included: a
    snapshot of its fit of 2026-10-11, the heat pump's performance map
    fitted on 2026-10-26 and the layered tank's terms on 2026-10-27.
    Several of its values move with every refit there (the
    circulation's displaced volume and flow, the heat pump's map, the
    tank's losses), so read it as an example, not as that
    installation's current state. The 50 and 80 gal models scale its
    tank volume by rated storage (``RATED_GAL``), and nothing else."""
    rated = dict(RATED_GAL)
    if volume_code not in rated:
        raise ValueError(f"unknown volume_code {volume_code!r}")
    site = _nwp500_65()
    base = replace(with_valve(site, SITE_VALVE), circulation=SITE_CIRCULATION)
    if volume_code == VOLUME_65:
        return base
    scale = rated[volume_code] / rated[VOLUME_65]
    return replace(
        base,
        tank=replace(base.tank, volume_gal=base.tank.volume_gal * scale),
    )
