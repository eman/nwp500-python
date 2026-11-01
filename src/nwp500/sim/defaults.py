"""Default parameters, by tank size.

Every value comes from one NWP500-65 on 240 V: its parameters as fitted
on 2026-10-11 from its own record, with the constants measured by
targeted device runs and the engineering constants the fit assumes
(each field's ``Provenance`` says which: ``provenance_of``). The 50 and
80 gal models get the 65's tank resized to their own (``sized``): the
50 is narrower than the 65 and as tall, the 80 as wide and taller, and
the terms that go with the tank's walls and cross-section scale with
them. Their compressor, elements and controller are the 65's, and none
of their terms is measured.

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

import math
from dataclasses import replace

from nwp500.sim.params import (
    INSTALLATION_TERMS,
    MAP_REF_WATER_F,
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
from nwp500.sim.physics.water import btu_per_gal_f
from nwp500.sim.units import WATER_BTU_PER_GAL_F

#: The device's ``volume_code``: NWP500-50, -65 and -80.
VOLUME_50 = 1
VOLUME_65 = 2
VOLUME_80 = 3

#: Rated storage volume by model, gallons: the manual's specification
#: table (45.2, 63.2 and 76.1 for the 50, 65 and 80 gal models).
RATED_GAL = ((VOLUME_50, 45.2), (VOLUME_65, 63.2), (VOLUME_80, 76.1))

#: Each model's outside, inches: its diameter and height, from the same
#: table (Ø21.7 × 63, Ø25 × 63 and Ø25 × 71.6).
OUTSIDE_IN = (
    (VOLUME_50, 21.7, 63.0),
    (VOLUME_65, 25.0, 63.0),
    (VOLUME_80, 25.0, 71.6),
)

_IN3_PER_GAL = 231.0

#: One installation's thermostatic mixing valve: delivered water at
#: 53.56 + 0.485 × the upper zone, °F, never above the tank. Measured
#: from five plateaus at a gauge on its outlet, 2026-09-16/17.
SITE_VALVE = (53.56, 0.485)
#: No mixing valve: the tap gets the tank's own water.
NO_VALVE = (0.0, 1.0)
#: The flow from which that installation's draws took the tank's water
#: whole, gal/min (``DrawParams.undiluted_gpm``): its draws of 20 gal or
#: more ran at 0.8-1.7 gal/min through the valve's share and at
#: 2.1-2.7 without it, 2026-04-16..10-26.
SITE_UNDILUTED_GPM = 2.0

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
#: 14 days before a retrain). Its pipe is measured on one run on
#: 2026-10-29 (``calibration.measure_pipe``), 35.7 min at constant
#: pressure after a 4 h rest with nothing else acting on the tank: the
#: return rose half way to its steady value at 6.86 gal of the run's
#: own flow reading, and held 1.6 °F under the upper probe at 1.08
#: gal/min, a loss of 14.4 BTU/h·°F. With it the return's rest and
#: cooling are fitted (``calibration.fit_return``) on 122 runs with the
#: compressor off, 2026-04-04 to 2026-10-24: the return rests 3.74 °F
#: above the heater's air, and the pipe a run warmed cools back to rest
#: on 0.72 h. The gallons are the run's own reading's: the house's
#: meter has read about 0.3 gal/min under it since 2026-09-14.
SITE_CIRCULATION = CirculationParams(
    displaced_gal=6.86,
    flow_gpm=1.397,
    pipe_ua_btu_hr_f=14.4,
    return_rest_offset_f=3.74,
    return_cool_tau_h=0.72,
    # Its household meter read a run at 0.81 of the run's own flow
    # (median of 47 runs), but the flow a history's replay takes is the
    # household's draws alone (``sim_home_assistant`` reads them from
    # the draw detector), which no run passes.
    meter_share=0.0,
)


#: The tank in the quiet windows the jacket's loss and the column's
#: conductance were fitted on, °F: their typical mean (``_restated``).
_QUIET_TANK_F = 125.0


def _restated(params: HeaterParams) -> HeaterParams:
    """``params``' terms fitted in BTU against a constant
    ``WATER_BTU_PER_GAL_F``, restated against water's heat at its
    temperature (``physics.water``): the same climbs and coasts, so the
    same answers where they were fitted. Each scales by the water's
    heat per gallon there over the constant: the heat pump's map at its
    120 °F reference water (0.988), its slope with the water taking the
    heat's own fall with it (-15.9 to -16.7 BTU/h per °F); the jacket's
    loss and the column's conductance at ``_QUIET_TANK_F`` (0.987).
    Refitted on the record under the water's heat, 2026-04-16 to 10-26,
    the map lands within 0.1 % of the fit restated so at 120 °F, and on
    the record from 2026-09-18 the restated fit scores within 0.05 min
    a recovery and 0.03 % of its energy of the fit under the constant."""
    c, loss, tank = params.compressor, params.loss, params.tank
    at_map = btu_per_gal_f(MAP_REF_WATER_F) / WATER_BTU_PER_GAL_F
    falls = (
        btu_per_gal_f(MAP_REF_WATER_F + 0.5)
        - btu_per_gal_f(MAP_REF_WATER_F - 0.5)
    ) / WATER_BTU_PER_GAL_F
    quiet = btu_per_gal_f(_QUIET_TANK_F) / WATER_BTU_PER_GAL_F
    return replace(
        params,
        compressor=replace(
            c,
            heat_btu_h=c.heat_btu_h * at_map,
            heat_btu_h_per_air_f=c.heat_btu_h_per_air_f * at_map,
            heat_btu_h_per_water_f=c.heat_btu_h_per_water_f * at_map
            + c.heat_btu_h * falls,
            heat_btu_h_per_air_water_f=c.heat_btu_h_per_air_water_f * at_map,
        ),
        loss=replace(
            loss,
            ua_side_btu_hr_f=loss.ua_side_btu_hr_f * quiet,
            ua_bottom_btu_hr_f=loss.ua_bottom_btu_hr_f * quiet,
            ua_top_btu_hr_f=loss.ua_top_btu_hr_f * quiet,
        ),
        tank=replace(
            tank, conductance_btu_hr_f=tank.conductance_btu_hr_f * quiet
        ),
    )


def _nwp500_65() -> HeaterParams:
    """The NWP500-65's parameters, as fitted (``_restated``)."""
    return _restated(_fitted_65())


def _fitted_65() -> HeaterParams:
    """The NWP500-65's parameters as fitted, against a constant
    ``WATER_BTU_PER_GAL_F``."""
    return HeaterParams(
        # The layered tank fitted on its record, 2026-04-16 to
        # 2026-10-26 (``sim_calibrate.calibrate_changes``): 266 quiet
        # windows, 254 metered draws and 118 recoveries, each started
        # from the day's replay before it, the compressor's start
        # stirring the layers (``physics.stratified.stir``), no hold
        # imposed and the heat pump's maps read along their planes.
        tank=TankParams(
            volume_gal=63.2,
            layers=12,
            upper_probe_height=0.9023796550762445,
            lower_probe_height=0.4762953177315908,
            upper_probe_spread_gal=5.223993410085456,
            lower_probe_spread_gal=2.2109548939857624,
            lower_probe_offset_f=1.1277012541585785,
            condenser_span=(0.15449269225072243, 0.28915445602405737),
            inlet_mix_gal=14.217652959831804,
            conductance_btu_hr_f=0.5106531501532018,
        ),
        loss=LossParams(
            ua_side_btu_hr_f=3.062819008375388,
            ua_bottom_btu_hr_f=0.5590393828960091,
            ua_top_btu_hr_f=0.5568139861843887,
        ),
        # The heat's map and the run-on fitted on its record,
        # 2025-12-28 to 2026-10-26 (``heat_pump_fit.fit_heat_pump``),
        # the heat against the two-zone tank's loss: refitted against
        # the loss above, from 2026-04-16, it moves 0.5 % at 65 °F air
        # and 120 °F water and under 0.9 % across its span (4,478
        # BTU/h, +55.9 per °F of air, -16.4 per °F of water). The
        # power's map fitted on 3,562 metered climb blocks of 211 runs,
        # 2026-04-16 to 10-26, at the condenser's water on the record's
        # replay through the tank above
        # (``heat_pump_fit.in_condenser_water``), where the walk reads
        # it: 4.7 °F under the lower probe on average.
        compressor=CompressorParams(
            heat_btu_h=4499.436604500702,
            heat_btu_h_per_air_f=55.49795247502065,
            heat_btu_h_per_water_f=-15.948333659761246,
            heat_btu_h_per_air_water_f=0.0,
            power_w=408.82790749208425,
            power_w_per_air_f=1.023669362351011,
            power_w_per_water_f=2.7232689098605563,
            power_w_per_air_water_f=0.0,
            heat_domain_air_f=(61.0, 89.0),
            heat_domain_water_f=(114.0, 144.0),
            power_domain_air_f=(53.0, 90.0),
            power_domain_water_f=(65.0, 144.0),
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


def tank_column_in(volume_code: int) -> tuple[float, float]:
    """The water column of model ``volume_code``, inches: its inner
    diameter and its height. The 65 and the 80 are as wide outside, so
    the 80's 12.9 gal more over its 8.6 in more height is the water's
    cross-section: 21.0 in across inside 25, under 2.0 in of wall and
    foam. Taking the same wall on the 50, each model's rated storage
    over its cross-section is its column: 17.7 × 42.4 in, 21.0 × 42.1
    and 21.0 × 50.7. The 50 and the 65 come out as tall within 0.3 in
    under their equal 63 in, as they should."""
    outside = {code: (d, h) for code, d, h in OUTSIDE_IN}
    rated = dict(RATED_GAL)
    if volume_code not in rated:
        raise ValueError(f"unknown volume_code {volume_code!r}")
    (d65, h65), (_, h80) = outside[VOLUME_65], outside[VOLUME_80]
    added = (rated[VOLUME_80] - rated[VOLUME_65]) * _IN3_PER_GAL
    inner65 = math.sqrt(4.0 * added / (math.pi * (h80 - h65)))
    wall = (d65 - inner65) / 2.0
    inner = outside[volume_code][0] - 2.0 * wall
    height = rated[volume_code] * _IN3_PER_GAL / (math.pi * inner**2 / 4.0)
    return inner, height


def sized(params: HeaterParams, volume_code: int) -> HeaterParams:
    """``params``, a 65's, for model ``volume_code`` (``tank_column_in``):
    its volume the model's rated storage, and the terms that go with the
    tank's shape scaled by it, each by what it is.

    - The sides' loss by the shell's conductance, ``h / ln(r_o / r_i)``
      at the same wall: 0.86 of the 65's on the 50, 1.20 on the 80.
    - The bottom's by the cross-section: 0.71 on the 50.
    - The column's axial conductance by the cross-section over the
      height: 0.71 on the 50, 0.83 on the 80.
    - The probes' spreads and the inlet zone, gallons along the column,
      by the cross-section: a length of the column holds 0.71 of the
      water on the 50, and the same on the 80.

    The top's loss (the head, its fittings and pipes) is the 65's, and
    so are the heights, each a share of the volume from the bottom:
    the 50's column is the 65's height, so its probes, elements and
    coil sit as high; where the 80's sit in its taller column is not
    known. The heat pump's maps, the elements and the controller are
    the 65's."""
    inner, height = tank_column_in(volume_code)
    inner65, height65 = tank_column_in(VOLUME_65)
    outside = {code: d for code, d, _ in OUTSIDE_IN}
    area = (inner / inner65) ** 2
    tall = height / height65
    side = (height / math.log(outside[volume_code] / inner)) / (
        height65 / math.log(outside[VOLUME_65] / inner65)
    )
    tank, loss = params.tank, params.loss
    return replace(
        params,
        tank=replace(
            tank,
            volume_gal=dict(RATED_GAL)[volume_code],
            upper_probe_spread_gal=tank.upper_probe_spread_gal * area,
            lower_probe_spread_gal=tank.lower_probe_spread_gal * area,
            inlet_mix_gal=tank.inlet_mix_gal * area,
            conductance_btu_hr_f=tank.conductance_btu_hr_f * area / tall,
        ),
        loss=replace(
            loss,
            ua_side_btu_hr_f=loss.ua_side_btu_hr_f * side,
            ua_bottom_btu_hr_f=loss.ua_bottom_btu_hr_f * area,
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
    (``SITE_VALVE``, ``SITE_UNDILUTED_GPM``) and circulation
    (``SITE_CIRCULATION``) included: a
    snapshot of its fit of 2026-10-11, the heat pump's performance map
    fitted on 2026-10-26 and the layered tank's terms on 2026-10-27.
    Several of its values move with every refit there (the
    circulation's displaced volume and flow, the heat pump's map, the
    tank's losses), so read it as an example, not as that
    installation's current state. The 50 and 80 gal models resize its
    tank to theirs (``sized``)."""
    if volume_code not in dict(RATED_GAL):
        raise ValueError(f"unknown volume_code {volume_code!r}")
    site = _nwp500_65()
    valved = with_valve(site, SITE_VALVE)
    base = replace(
        valved,
        draw=replace(valved.draw, undiluted_gpm=SITE_UNDILUTED_GPM),
        circulation=SITE_CIRCULATION,
    )
    if volume_code == VOLUME_65:
        return base
    return sized(base, volume_code)
