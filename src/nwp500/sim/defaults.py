"""Default parameters, by tank size.

Every value comes from one NWP500-65 on 240 V: its parameters as fitted
on 2026-10-11 from its own record, with the constants measured by
targeted device runs and the engineering constants the fit assumes
(each field's ``Provenance`` says which: ``provenance_of``). The 50 and
80 gal models get the same parameters with the tank's volume scaled by
nominal size, and nothing else: their compressor, elements, jacket loss
and controller are the 65's until one of them is measured.

The fit is one unit's, in one place, and part of it describes that
place rather than the heater (``params.Scope``): the draw terms were
fitted through its mixing valve, on its mains and its household's
draws. ``site_example_params`` is that installation whole;
``default_params`` is the same heater with **no mixing valve**, the one
draw setting with no fitted numbers in it, which errs the safe way for
a valve owner who leaves it unset (every gallon charged as tank water,
depletion called early). A caller with its own calibration, or a
valve, passes its own ``HeaterParams``.
"""

from dataclasses import replace

from nwp500.sim.delivery import with_example_evidence
from nwp500.sim.params import (
    INSTALLATION_TERMS,
    CirculationParams,
    CompressorParams,
    ControllerParams,
    DrawParams,
    ElementParams,
    HeaterParams,
    LossParams,
    PowerParams,
    TankParams,
)

#: The device's ``volume_code``: NWP500-50, -65 and -80.
VOLUME_50 = 1
VOLUME_65 = 2
VOLUME_80 = 3

#: Nominal gallons by ``volume_code``.
NOMINAL_GAL = ((VOLUME_50, 50.0), (VOLUME_65, 65.0), (VOLUME_80, 80.0))

#: One installation's thermostatic mixing valve: delivered water at
#: 53.56 + 0.485 × the upper zone, °F, never above the tank. Measured
#: from five plateaus at a gauge on its outlet, 2026-09-16/17.
SITE_VALVE = (53.56, 0.485)
#: No mixing valve: the tap gets the tank's own water.
NO_VALVE = (0.0, 1.0)

#: The installation's circulation: 6.2746 gal displaced per run (fitted
#: per retrain), 1.397 gal/min (the median over the 14 days before it),
#: and the book's 159 BTU per gallon circulated.
SITE_CIRCULATION = CirculationParams(
    displaced_gal=6.2746,
    flow_gpm=1.397,
    loss_btu_per_gal=159.0,
    # Fitted on the book's re-anchors with runs merged within 10 min:
    # an effective volume, apart from ``displaced_gal``.
    book_circuit_gal=1.47,
    # Its household meter read a run at 0.81 of the run's own flow
    # (median of 47 runs), but the flow the book takes is the
    # household's draws alone (``sim_home_assistant`` reads them from
    # the draw detector), which no run passes.
    meter_share=0.0,
)


def _nwp500_65() -> HeaterParams:
    """The NWP500-65's parameters."""
    return HeaterParams(
        tank=TankParams(
            volume_gal=63.2,
            lower_zone_share=0.5,
            stratification_gap_tau_h=60.063706561480814,
        ),
        loss=LossParams(
            ua_btu_hr_f=4.60509822193756,
            ua_exponent=0.18641936047758134,
            ua_ref_delta_t_f=50.0,
            ua_baseline_btu_hr_f=5.0,
        ),
        compressor=CompressorParams(
            compressor_constant=0.05140793710947029,
            evap_approach_f=18.553854238987046,
            two_zone=True,
            cond_approach_f=10.0,
            clearance_ratio=0.05,
            polytropic_exp=1.17,
            fan_airflow_cfm=229.0,
        ),
        power=PowerParams(
            power_scale=0.5299928954425356,
            cop_scale=2.1838863347798503,
            startup_wh=160.29537801006768,
            cop_lift_coeff=0.005,
            cop_lift_ref_f=62.0,
        ),
        element=ElementParams(
            element_w=5148.0,
            upper_f_per_min=2.01,
            lower_f_per_min=1.38,
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
            observability=0.633,
            reach_gate_f=30.0,
            reach_offset_f=1.5,
            reach_gal=9.0,
            upper_f_per_gal=0.05,
            delivery_intercept_f=53.56,
            delivery_slope=0.485,
            inlet_temp_f=72.4,
            inlet_from_probe=True,
            lower_gate_f=5.0,
            pool_f_per_hour=0.015,
            ungated_observability=0.398008155230017,
        ),
        controller=ControllerParams(
            write_start_lag_s=30.0,
            restart_lockout_s=330.0,
            window_write_starts_f=4.0,
            mode_write_starts_f=2.0,
            mode_write_lower_starts_f=3.6,
            energy_saver_write_seen_f=1.44,
            tou_cap_f=3.6,
        ),
    )


def with_valve(
    params: HeaterParams, valve: tuple[float, float]
) -> HeaterParams:
    """``params`` with the mixing valve ``(intercept_f, slope)``:
    delivered water at ``intercept_f + slope × upper``, never above the
    tank; ``NO_VALVE`` for none. The draw terms' line, which the book
    takes too (``HeaterParams.book_terms``)."""
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
    with no mixing valve (``NO_VALVE``), no circulation and no readiness
    evidence (the site's was metered through its valve, and over-promises
    without one: the probes answer alone until your own is measured).
    Every other installation term is still that site's, labelled so
    (``params.scope_of``) and named in ``unfitted``
    (``INSTALLATION_TERMS``), so every answer they reach says
    ``book_uncalibrated``, ``readiness_uncalibrated`` or
    ``draw_uncalibrated`` until your own meter fits them."""
    site = site_example_params(volume_code)
    return replace(
        with_valve(site, NO_VALVE),
        circulation=None,
        readiness=replace(site.readiness, evidence=()),
        unfitted=INSTALLATION_TERMS,
    )


def site_example_params(volume_code: int = VOLUME_65) -> HeaterParams:
    """One NWP500-65 installation's parameters, its mixing valve
    (``SITE_VALVE``) and circulation (``SITE_CIRCULATION``) included: a
    snapshot of its fit of 2026-10-11. Several of its values move with
    every refit there (the circulation's displaced volume and flow, the
    compressor and power fits), so read it as an example, not as that
    installation's current state. The 50 and 80 gal models scale
    by nominal size its tank volume (the tank's, and the heat book's
    count of it) and the book's empty point (``BookParams.empty_btu``,
    about 256 BTU per gallon of it), and nothing else. Its readiness
    evidence is the site's 19-draw frontier
    (``delivery.EXAMPLE_EVIDENCE``), measured on the 65 gal tank, which
    the model served for every heater."""
    nominal = dict(NOMINAL_GAL)
    if volume_code not in nominal:
        raise ValueError(f"unknown volume_code {volume_code!r}")
    site = _nwp500_65()
    base = replace(
        with_valve(site, SITE_VALVE),
        circulation=SITE_CIRCULATION,
        readiness=with_example_evidence(site.readiness),
    )
    if volume_code == VOLUME_65:
        return base
    scale = nominal[volume_code] / nominal[VOLUME_65]
    return replace(
        base,
        tank=replace(base.tank, volume_gal=base.tank.volume_gal * scale),
        book=replace(
            base.book,
            tank_gal=base.book.tank_gal * scale,
            empty_btu=base.book.empty_btu * scale,
        ),
    )
