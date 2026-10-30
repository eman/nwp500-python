"""Physical constants the simulator core uses."""

# A gallon of water's heat per °F at the mains, 58 °F: 8.34 lb at
# 1 BTU/lb·°F. It falls as the water warms (``physics.water``); the
# tank's heat is kept in degrees of it (``physics.water.heat_f``).
WATER_BTU_PER_GAL_F = 8.34

# BTU is the core's internal unit (the tank, the water and the UA law
# are all expressed in it), but it is not what the wire speaks.  The
# appliance reports energy in Wh (`available_energy_wh`),
# electricity is priced in kWh, and the scheduler's whole job is
# comparing energy a draw removed against energy still needed to reach
# setpoint.  Those are the same quantity with opposite signs, so they
# belong in the same unit; the conversion happens once, at the API
# boundary.
BTU_PER_WH = 3.412141633

# Fallback ambient temperature (°F), the air at the heater, when no
# reading and no forecast is available: the ambient a standby coast
# assumes for an instant its series does not cover.  The annual mean
# of the air at the heater for the installation it was measured at.
DEFAULT_AMBIENT_F = 65.0
