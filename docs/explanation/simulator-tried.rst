===================================
Simulator Changes Tried and Dropped
===================================

Changes to the simulator that were built or measured against the
record and not kept, newest first. Each says what was tried, what the
record said, and where the full account is. Before trying one of these
again, read that account: what would make it worth another try is
named there. When a change is tried and dropped, add it here.

.. contents::
   :local:
   :depth: 1


24 layers, refitted (2026-10-30)
================================

**Tried.** The tank at 24 layers instead of 12, its terms refitted on
the whole record, for answers that do not swing with the layer count
and an upper element nearer its measured climb.

**Found.** Fitted before 2026-09-18 and scored after, no answer moved
outside the scores' intervals: recoveries 38.2 min off against 37.7,
their energy 12.9 % against 12.4. Both were fitted and scored from the
defaults' installation, without ``site_example_params``'s mixing
valve, circulation and mains (with no circulation terms the replay
that starts each event leaves out the record's pump runs), so these
are not the basis of :doc:`simulator`'s accuracy; compare a new score only with one made
the same way. The upper probe climbs under the
upper element 1.70 degF/min against 1.58 at 12 and the record's 2.01,
as the refit widens the probe's spread. A walk takes 1.55 times as
long, and the refit lands on another point of the ridge the bottom's
loss and the inlet zone trade along.

**Why dropped.** No better on the record, slower. The element's
shortfall is that it heats a whole layer; a change that heats the
volume over its height at any count is what would close it.

**Account.** :doc:`simulator-methodology`, "The layer count is part of
the fitted model".


A room the heat pump cools (2026-10-30)
=======================================

**Tried.** Measured, not built: the air beside the heater over 230
runs against the same hours on nearby days with nothing running.

**Found.** Over a run the air rose 0.49 degF less than at the same
hours with nothing running (0.04-0.95), 27 BTU/hr of the heat at the
map's air slope, about a ninth of the heat map's own error. A
replay's air carries it; a forecast's carries it as its anchor does.

**Why dropped.** Too small to model, and a room of its own needs its
capacity and its loss to outdoors, which no heater's record measures.

**Account.** :doc:`simulator-methodology`, "The air";
:doc:`recovery-speed`, "The heat pump cools its room a little".


The heat map fitted on the winter's climbs (2026-10-30)
=======================================================

**Tried.** Bringing the 48,000 compressor minutes at 45-60 degF of air
(December to April) into the heat map, to fit it below 61 degF and to
see a frost derate if there is one.

**Found.** The draw detector began on 2026-04-16, so the winter's
minutes may all have had a draw. Each way of admitting them was tried
where the detector is known. Judged a stretch at a time they read the
heat 3.5-4 % high, and judged by the heater's own flag 14 % high, its
rise with the air a third flat. No frost shows: in air of 50-55 degF
the runs lasted a median 369 minutes, and 2 % were followed by an off
under 15 minutes, against 5-9 % above 60 degF.

**Why dropped.** The winter can only be judged by the flag, whose bias
would set the cold end. A rough count on the flag had put the cold
air's heat 19-22 % over the map; that was the flag.

**Account.** :doc:`recovery-speed`, "Below 61 degF the heat is not
measured".


The probes reading warm while the compressor runs (2026-10-28)
==============================================================

**Tried.** An offset on both probes that builds over a run's first
minutes (measured on 74 quiet stops: 0.54 degF upper, 0.89 lower), in
the probes, the stops and the replay, with the power read at the lower
probe's reading.

**Found.** On the 11 held-out draw-free recoveries the mean went from
6.6 min long to 2.5, but the mean absolute error rose from 11.9 to 12.7
min and the electricity's from 5.7 % to 9.9 %. Over the 21 from
2026-04-16, the 8 under 90 minutes went from 1.9 min short to 8.2.

**Why dropped.** Worse where it counts. At the time two errors partly
cancelled: the power, read at the condenser's water below the probe it
was fitted on, priced the long runs low. The power has since been
refitted where it is read, so that offset is gone, and the trial,
against that older model, does not say how the offset would do now.

**Account.** :doc:`simulator`, "Two errors in a heat-pump recovery
partly cancel".


A hold imposed at the compressor's start (2026-10-28)
=====================================================

**Tried.** The minutes the lower probe holds after a start, fitted by
how long the compressor was off and imposed on the walk
(``CompressorParams.start_hold_min``, still a parameter, by default
five holds of 0 minutes).

**Found.** The tank's fit had to bend to it: the bottom's loss came out
0.887 BTU/hr per degF with the hold imposed against 0.168 without, and
the condenser's span ran over the lower probe (0.147-0.576).

**Why dropped.** Replaced by the start's stir: the condenser pools the
cold water under it, and the probe's hold follows from the layers.

**Account.** :doc:`simulator-methodology`, "The start's stir";
:doc:`/reference/simulator-inputs`, the tank's fitted terms.
