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


The joint rebuild: spans, the heat through the layers, the share fitted (2026-11-06)
====================================================================================

**Tried.** Built (``sim/joint-rebuild``, 8873dac, not merged), one
consolidated change in place of further one-term sweeps, after an
assessment of the simulator against its history found its heat map
fitted as the whole tank's rise but applied to the condenser's layers,
its draws taken at once and made up for by the inlet zone, the slower
draw's share and the fitted probe geometry, and its held-out span spent
by the selections made on it: every draw the detector times walked over
its span in the replay, the fit and the score ("Every draw over its
span", below); the heat pump's heat (its level and both slopes, the
cross term 0) fitted with the tank's terms through the layered walk on
the recoveries, with 5 or more, the whole-tank climb fit kept only under
that, the map's domain the recoveries' air and probe-mean range, the
power still fitted on the metered blocks at the new replay's condenser
water; the slower draw's share a fitted term where there are draws; the
lower probe's height free to the correction top (0.74), bound hits
named; the recoveries from the whole history (their air range), the
quiet windows and draws from the last seven weeks. The protocol was
written before any fit ran: fit A to 2026-09-18 from the parameters in
use, scored on the 29 held-out days after it against main's score of
those parameters; fit B to 2026-10-27 from the shipped example, scored
on the seven whole days after it, which no fit or choice had touched,
against the shipped example's; adopt only if neither span is worse
beyond the score's interval on the day's electricity, its end, the
recoveries or the probes after a draw, and a structural target
(recoveries with water in use, the lower probe after draws, false
starts) improves; no knob moved after a score.

**Found.** Both fits put the heat about 8 % over the whole-tank fit's,
with slopes 1.3 and 2 times as steep (A: 4417, +56.3, -16.9 BTU/h to
4801, +71.9, -36.7; B: 4445, +54.8, -16.7 to 4786, +66.3, -32.4), the
share at 0.20 and 0.16 against the 0.25 chosen, the lower probe's height
at 0.50 and 0.48 (not taking its freed bound), the condenser's width on
its 0.10 floor in A; the events' error on the fit period fell from 2.28
to 1.75 degF (A) and 2.22 to 1.72 (B). Held out on the 29 days (main's
score of the parameters in use, then the same parameters on the
branch's scorer, then fit A): the day's electricity 10.2, 11.6 and 15.1
% off (bias -2.1, -3.9, -11.0), its end 3.09, 3.87 and 4.74 degF, the
draw-free recoveries 3.9, 4.8 and 8.9 minutes off (fit A 7.8 short),
those with water in use 19.9, 23.6 and 26.0, a recovery's electricity
4.8, 5.0 and 7.0 %, the lower probe after a draw 1.74, 3.46 and 3.40
degF RMS, the starts placed 0.824, 0.793 and 0.747; the standby upper
probe 0.251, 0.272 and 0.204. On the seven frozen days (the shipped
example on main, on the branch, then fit B): the electricity 10.0, 10.1
and 12.8 % off (bias +10.0, +10.1, -1.0), the day's end 1.84, 1.84 and
3.65 degF, the five recoveries, all with water in use, 18.0, 18.8 and
16.9 minutes off (18, 19 and 6 long), the lower probe after a draw 4.84,
7.70 and 7.86, the day's lowest upper probe 2.42, 2.30 and 1.74 degF
off.

**Why dropped.** By the rule set before the scores: the held-out span is
worse beyond the interval on the electricity's bias, the draw-free
recoveries and a recovery's electricity, and worse within it on the
day's energy, its end and the recoveries overall; the frozen span is
mixed, its long recoveries with water in use closer by the same higher
heat that walks the draw-free ones short. The heat fitted through the
layers undoes the whole-tank frame's compensation rather than finding
the recoveries-with-draws error; the spans in the replay and the score
cost more on the held-out days than the refit returned. The parameters
in use and the code on main stay.

**Account.** The protocol, fits, scores and compare tables are kept with
the site's (``joint-rebuild-2026-11-06``: README.txt, RESULTS.txt,
fit-A.json, fit-B.json, V/ and F/; the params docs
``params-site-joint-A-8873dac.json`` and ``-B-``). The assessment that
led to it is not written up apart from this entry. What would make it
worth another try: a heat fit through the layers judged on held-out
draw-free recoveries as it is fitted, or the recoveries with water in
use diagnosed apart from the heat's level (:doc:`simulator`, the
recoveries with water in use).


Every draw over its span, with the tank refit (2026-11-06)
==========================================================

**Tried.** Built (``sim/draws-over-span``, 27bea31, not merged): every
draw the draw detector times walked over its span from the meter's
onset, at its even flow, in the replay that starts every event, the tank
fit and the score alike (before, the replay and the fit took every draw
at its onset and the score only those at ``DrawParams.undiluted_gpm`` or
faster over their spans), a draw under way at an event's start split
there by its pieces. Then every tank term and the condenser's span refit
together on the fit period (208 quiet windows, 208 draws, 90 recoveries
before 2026-09-18), with the slower draw's share at 0.25 and at 0, and
the 29 held-out days scored at 0.85. It was to replace the terms that
make up for draws taken at once: the share, the inlet zone, the lower
probe's height.

**Found.** On the fit period the events' error fell from 2.44 degF (the
draws at onset; refit so, 2.26) to 1.81 with the spans on the terms in
use and 1.67 with the share at 0 alone, then 1.55 refit at 0.25 and 1.43
at 0 (the lower probe's height then on its 0.5 bound). Held out, against
the model in use (refit at 0.25, then at 0): the starts placed 0.784 and
0.793 against 0.741, the false 0.28 and 0.21 a day against 0.28, the
missed 0.41 and 0.38 against 0.45; but the day's electricity 14.2 and
12.8 % off against 11.4 (a mean 0.8 and 6.6 % low against 0.7), the end
of day 4.17 and 4.45 degF off against 3.11, the probes after a draw 0.60
and 0.52 degF RMS against 0.33 (upper) and 3.44 and 3.55 against 1.71
(lower), the draw-free recoveries 6.7 and 7.0 minutes off against 3.5
and their electricity 5.8 and 5.7 % against 3.7, and the recoveries with
water in use 19.5 and 20.6 minutes off against 20.2, from 6.7 minutes
long to 9.6 and 13.2 short. The span's start against the meter's onset
was measured after (draws of 1 gal or more): a median 0.1 minutes after
it on the fit period and 0.2 held out, where 30 % start more than a
minute after it (95th percentile 5.2); the onset does not place them
late.

**Why dropped.** Worse held out on the day's electricity, its end, both
probes after a draw and the draw-free recoveries, for better starts; the
recoveries with water in use, which it was for, 0.7 minutes closer at
0.25 and further at 0, and short where they were long. The fit period's
gain did not carry over.

Re-judged the same day with both tanks fitted on the seven weeks before
2026-09-18 alone (calibration now fits the tank on its last seven weeks
with the history before as their lead-in, its errors within 0.12 of
that: ``calibrate-simulator``), against the draws at onset fitted so
(share 0.25, then 0, against onset): the day's electricity 18.6 and 15.3
% off against 10.2, its end 5.66 and 4.69 degF against 3.09, the probes
after a draw 0.67 and 0.56 against 0.31 (upper) and 3.29 and 3.32
against 1.74 (lower), the draw-free recoveries 11.5 and 9.4 minutes off
against 3.9 (11 and 9 short), those with water in use 22.3 and 21.4
against 19.9, the starts placed 0.815 and 0.738 against 0.824: worse
again (``recent-weeks-2026-11-06``).

**Account.** The scripts, params and scores are kept with the site's
(``draws-over-span-2026-11-06``, its README naming the two params docs).
The earlier timings: "Every timed draw walked over its span, the days"
and "A metered draw timed by the draw detector", below.


The slower draw's share lowered, for runs after a draw (2026-11-06)
===================================================================

**Tried.** Measured, not built: ``DrawParams.undiluted_share``, the
share of a slower draw's cold side the tank gives as well, at 0.1 and 0
rather than 0.25, every held-out recovery walked from its recorded start
as the score walks it, on the parameters in use (0.85).

**Found.** The four runs longest, each starting with a slower draw of 9
to 16 gal, came 1.5 to 5.4 minutes shorter, 09-22 17:14 UTC from 40 to
36 and 34 minutes long; 10-13 13:09 46 minutes shorter at 0 only because
its walk then stopped before a circulation run it had heated through.
The free recoveries' mean absolute error went from 4.3 to 4.2 minutes at
both, the runs with draws' from 23.1 to 22.0 and 18.3.

**Why dropped.** The share is not what the four lack: they run 24 to 40
minutes long (10-13 without its circulation run) and it moves them a
few. It was chosen on the held-out draws and days, these recoveries
among them (:doc:`simulator-methodology`, "A slower draw").

**Account.** :doc:`simulator`, "Accuracy", the runs with water drawn
around them. The scripts and tables are kept with the site's
(``placed-energy-2026-11-06``: ``share.py``, ``share.txt``,
``startdraws.txt``, ``power60.txt``).


More heat from cold water, for the runs after a large draw (2026-11-06)
=======================================================================

**Tried.** Measured, not built: the heat map's plane steeper below its
fitted water span, the heat plus K BTU/h for each degF the condenser's
water is under 114 degF, K at 16, 32 and 64, every held-out recovery
walked from its recorded start as the score walks it, on the parameters
in use (0.85).

**Found.** The four runs longest, each starting with 7 to 14 gal drawn
at its start, shorten: 10-13 13:09 UTC from 66 to 15, 7 and -5 minutes,
09-22 17:14 from 40 to 33, 27 and 18. The rest go shorter with them. The
14 free recoveries came a mean 0.2 minutes short as is and 2.3, 4.1 and
7.2 short (mean absolute error 4.3, 4.6, 5.3, 7.2); the 13 with draws
7.5 long as is, then 2.8, 9.6 and 20.6 short (23.1, 19.1, 20.7, 26.4),
the short ones among them shorter (10-01 03:42 from 5 to 20, 33 and 54
short).

**Why dropped.** It does not tell the runs after a large draw from the
rest: the free recoveries, from cold tanks too, are already right, and
the runs with draws that come short go shorter. Most of 10-13's
shortening is its circulation run after the record's stop, which the
walk no longer reaches.

**Account.** :doc:`simulator`, "Accuracy", the runs with water drawn
around them. The scripts and tables are kept with the site's
(``placed-energy-2026-11-06``: ``coldheat.py``, ``coldheat.txt``,
``rates.txt``, ``crawl.txt``, ``circ.txt``).


A cold-air slope in the compressor's power under a knee (2026-11-05)
====================================================================

**Tried.** Built (#390): ``CompressorParams.power_air_knee_f`` and
``power_w_per_air_below_f``, the power map's electricity its plane's
plus a slope for each degF the air is under a knee, the knee set at 60
degF and the slope fitted at +2.94 W a degF on the 10-minute metered
climb blocks at the condenser's water before 2026-09-18 with the plane
kept. A flat floor on the power's air, refitted with its plane, was
measured first.

**Found.** The 1,807 winter blocks under 60 degF read 4.1 W low (in the
fit) against 19.2 with the plane alone, the 50 held out 18.0 against
26.3, and the 29 held-out days' electricity 12.69 % off against 12.80.
Every fit of the knee erred less the higher the knee, to the top of the
range tried (68 degF for the floor, 64 for the slope), the winter's
blocks at 60 to 80 degF reading 4 to 9 W over the plane. The evaporator
fan's two speeds carry both (measured 2026-11-05): its high speed drew
23.7 W more, and a step for it at 60.5 degF read the winter's blocks
under 60 degF 0.4 W low and the held out 7.5, the 29 days' electricity
12.64 % off.

**Why dropped.** The slope stood for a step: the power does not rise
with the cold under the knee, it rises once, with the fan's speed. The
fan's step (``CompressorParams.fan_high_below_air_f``, ``fan_high_w``)
took its place before a release.

**Account.** :doc:`simulator`, "Accuracy", the cold-air power. The
scripts and scores are kept with the site's
(``compressor-power-2026-11-05``, ``winter-offset-2026-11-05``;
``params-site-fit-before-2026-09-18-share-0.25-power-knee60-*``).


A 7 gal inlet zone and tank refits, for the early starts (2026-11-05)
=====================================================================

**Tried.** Measured, not built: ``TankParams.inlet_mix_gal`` at 7 and 3
gal instead of the fitted 13.78, on the parameters in use
(``correction_top_height`` 0.75, the share at 0.25), against the walk's
early starts after draws and circulation runs (:doc:`simulator`,
"Accuracy", the false starts). Then two refits at 7 gal from those
parameters, on the 2026-04-16 to 09-18 record as metered: the condenser
span alone on its 90 recoveries, and every tank term but the inlet zone
with the span on its 208 quiet windows, 208 draws and 90 recoveries (as
``sim_calibrate`` fits the tank). The same full refit at 13.78 was the
check. Each scored over the 29 held-out days at
``DrawParams.meter_reads`` 0.85 and the clean draws of 8 gal or more
with the compressor off (28 held out at 0.85, 99 from 05-01 to the
meter's step as metered).

**Found.** Over the 29 days, as in use; the zone at 7 gal; with its
condenser refit; the full refit at 13.78; the full refit at 7: the false
starts 8, 4, 5, 5 and 4; the day's electricity 12.8, 13.6, 14.9, 12.9
and 13.4 % off (a mean 2.5, 6.1, 7.9, 5.2 and 5.8 % low); the day's end
state 3.11, 4.62, 4.98, 3.86 and 4.70 degF off; the recoveries 13.4,
17.4, 15.6, 16.5 and 17.1 min off. At 3 gal the starts came as at 7 and
the recoveries further off (18.8 min). Every one of them cleared the
night of 09-23's start and 10-11's, and all but the condenser refit,
which kept one at 21:52 UTC, 10-24's two, the full refit at 13.78 as
well as the zone; 09-18's and 10-21's stayed. The full refits' fit came
out with ``ua_bottom_btu_hr_f`` at 0 and ``upper_probe_height`` at 0.98
at 13.78 (both on their bounds), and at 7 with the bottom's loss at 1.57
and the upper probe at 0.956; the event RMSE went from 2.44 to 2.26 degF
at 13.78 and from 2.24 to 2.16 at 7. The walk's lower probe an hour
after a draw, less the record's: held out a mean -1.29, +0.66, -0.10,
+0.35 and +0.73 degF, 4.59, 4.14, 4.10, 4.01 and 3.77 RMS; before the
step -1.58, +0.30, -0.35, -0.05 and +0.23, 4.06, 3.45, 3.51, 3.39 and
3.34 RMS. The upper probe through draws read 0.33, 0.31, 0.30, 0.26 and
0.24 degF RMS.

**Why dropped.** The false starts came nearly as much from refitting the
tank on the code as it now stands, at the fitted zone (5 against 4), as
from the smaller zone; and every change left the day's electricity
further low, its end state further off and its recoveries longer, which
a schedule prices. The parameters in use stay.

**Account.** :doc:`simulator`, "Accuracy". The scripts, the walks, the
scores and the refits' parameters are kept with the site's scores
(``early-starts-2026-11-05``;
``params-site-fit-before-2026-09-18-share-0.25-inlet*``).


The start's stir at the compressor's stop too (2026-11-05)
==========================================================

**Tried.** The start's stir (``stratified.stir``: the water the
condenser wraps and the water below it pooled to their mean) also where
the compressor stops: in the replay that starts each walk, at the end of
the step ending at the record's stop, its heating credited; in a walk,
at the start of the stretch after a run, which carries no compressor
(the engine's runs set no stop instant). On the parameters in use
(``TankParams.correction_top_height`` 0.75, the share at 0.25), against
the walk's lower probe off by a few gallons of depth after a large draw
(:doc:`simulator`, "Accuracy", the lower probe after a large draw). Over
the 28 clean held-out draws of 8 gal or more with the compressor off at
``DrawParams.meter_reads`` 0.85 from the meter's step, the 99 clean from
2026-05-01 to the step as metered, and the 29 held-out days at 0.85; it
stirred 97, 222 and 460 times in the replays, and 73 times in the days'
walks (each walk, and each look-ahead the engine walks from a stop,
stirring that stop's state once).

**Found.** The compressor is off through each draw's hour, so the draws
took it only through the replay. The walk's lower probe at the hour,
less the record's: held out a mean -1.29 to -0.66 degF, RMS 4.59 to
4.71, 8 to 16 draws off by 3 degF or more; before the step -1.58 to
-1.42, RMS 4.06 to 4.53, 31 to 49. Of the 8 held-out draws off by 3 or
more, 3 came nearer (2026-10-21 13:05 UTC from -16.5 to -13.5, 09-18
18:57 from -6.1 to -4.9) and 5 went further (09-30 13:03 from -10.1 to
-11.0, 10-02 00:50 from +7.3 to +8.3); the largest moves were draws that
had been near (10-21 01:31 from -1.9 to +3.7). The upper probe through
them moved 0.15 degF RMS held out and 0.07 before the step. Over the 29
days the compressor's false starts went from 8 to 6 and the missed from
13 to 12, but the day's electricity came 13.8 % off against 12.8 (a mean
5.2 % low against 2.5), the day's end state 4.05 degF off against 3.11,
the lower probe through standby 0.64 degF RMS against 0.51 and through
draws 1.85 against 1.71, the draw-free recoveries 4.1 min off against
3.5.

**Why dropped.** It spreads the lower probe's error after a draw rather
than taking it away, and costs the day's electricity, its end state and
the standby the two fewer false starts do not pay for. Read statically
it would have cooled the water the probe stands for (deeper); walked,
the probe came less deep on the mean and the draws moved both ways.

**Account.** :doc:`simulator`, "Accuracy". The scripts and the walks are
kept with the site's scores (``stop-stir-2026-11-05``).


A smaller inlet zone, for the top's drop at a draw (2026-11-05)
===============================================================

**Tried.** Measured, not built: ``TankParams.inlet_mix_gal`` at 7 and
3 gal instead of the fitted 13.8, in the replay that starts each draw
and in the draw, over the 123 clean draws of 8 gal or more with the
compressor off from 05-01 (95 before the meter's step, 28 held out),
on the parameters in use at ``DrawParams.meter_reads`` 0.85 from the
step: against the walk's upper probe falling too far at a draw from a
stratified tank (:doc:`simulator`, "Accuracy", the upper probe after a
large draw).

**Found.** The walk's fall at the draw less the record's by 15 minutes
stayed +0.09 degF on the mean before the step and went from -0.43 to
-0.38 and -0.39 held out. 2026-09-24 01:22 UTC's fall went from 9.8 degF
to 8.0 and 8.2 (the record's 3.1), 09-21 02:32's from 6.7 to 6.2 and 6.0
(1.6). On the stratified draws (the probes 5 degF or more apart: 9
before the step, 5 held out) the mean excess fall went from 0.42 degF to
0.40 and 0.39 before the step and from 2.38 to 2.02 and 2.01 held out.

**Why dropped.** On 09-24 and 09-21 it did as well as leaning the
probes' correction only to 0.75 of the height
(``TankParams.correction_top_height``: 8.0 and 6.3), but before the step
it took the stratified draws' excess only to 0.40 and 0.39, where the
lean took it to 0.18 (held out, 1.93 against 2.02 and 2.01), and the
inlet zone is fitted. The lean was kept.

**Account.** :doc:`simulator`, "Accuracy". The scripts and the walks
are kept with the site's scores (``top-drop-2026-11-05``).


The start triggers reading a lagged upper probe (2026-11-05)
============================================================

**Tried.** The heat pump's start triggers (the lower trigger's wait on
the upper zone, the upper zone's start at a window's opening) reading
the walk's upper probe through a first-order lag, every other reading
the walk's own, so that a large draw's drop at the top reaches them
over minutes, as the record's probe shows it after the score's walk
takes the draw at once (:doc:`simulator`, "Accuracy", the upper probe
after a large draw). The time constant was fitted on the 95 clean
compressor-off draws of 8 gal or more from 05-01 to the meter's step,
by the RMS of the upper probe over the hour after each: 7.75 minutes,
0.32 degF against 0.35 unlagged. Scored in the day backtest of the 29
days held out from 2026-09-18 on the parameters in use, at
``DrawParams.meter_reads`` 0.85, at 7.75 and 15 minutes (measured
2026-11-05); unlagged, the patch scores as the code does.

**Found.** No half hour's heating changed, and the false starts (0.28 a
day) and the missed (0.45) stayed. Two days' walks differed, from 09-24
03:00 and 09-30 02:30 UTC, by up to 1.3 and 0.8 degF at the half hours
at 7.75 minutes (2.5 and 0.8 at 15). The electricity came 12.8 and 12.7
% off against 12.9, a mean 2.5 and 2.6 % low against 2.4; the day's end
state 3.05 and 3.01 degF off against 3.11.

**Why dropped.** No start was gained, lost or misplaced, and the
electricity and the end state changed little. Of the 13 starts within 30
minutes after a large draw, 10 are on the lower trigger (9 at the draw),
and every walk was unchanged through them. The held-out draws' walk
falls too far as well as too soon, which a lag of minutes does not take.

**Account.** :doc:`simulator`, "Accuracy" (the upper probe after a
large draw). The patch and the scores are kept with the site's scores
(``upper-lag-2026-11-05``).


Conduction raised after a draw or a run, and fading (2026-11-05)
================================================================

**Tried.** The tank's axial conductance
(``TankParams.conductance_btu_hr_f``, fitted 0.55 BTU/hr·°F) times 1 + K
exp(-h / tau), h the hours since the last draw or heating, so that a
tank a draw or a run has just disturbed mixes faster and a rested one is
left alone: against the record's upper probe falling faster after a draw
and heating than the walk's (:doc:`simulator`, "Accuracy"). Scored in
the day backtest of the 29 days held out from 2026-09-18 on the
parameters in use, at ``DrawParams.meter_reads`` 0.85 (measured
2026-11-05); at K 0 the patch scores as the code does. The patch is the
tank's step, so the replay that sets each day's and each event's start
was raised as well, after the record's draws and runs, and the draws and
runs before a day walk's start, the replay's, counted for it.

**Found.** The quiet half hours' drift after a draw and heating was
+0.094 degF an hour, after a draw alone +0.018.

- Raised on every step, K 4 and tau 1 or 2 h: after both +0.024 and
  -0.020, after a draw alone -0.071 and -0.112; the recoveries 33.6 and
  33.4 min off on average against 14.1, their electricity 12.8 and
  13.0 % against 3.9.
- Raised only on steps with nothing heating or flowing, K 2 or 4 with
  tau 1 h, and 4 with 2 h: after both +0.036, -0.017 and -0.069, after
  a draw alone -0.041, -0.094 and -0.139. At K 2, tau 1 h, the false
  starts went from 0.28 a day to 0.21 and the missed from 0.45 to 0.38
  (6 and 11 on the 29 days against 8 and 13), the electricity from 12.9
  % off to 10.6; the upper probe through draws from 0.37 degF RMS to
  0.43, the draw-free recoveries from 4.2 min off to 5.5, the day's end
  state from 3.1 degF off to 3.3, the day's lowest upper from 0.37 degF
  low to 0.68.
- Raised only after a run ends, on steps with nothing heating or
  flowing, K 2 and 4 with tau 1 h, and 2 with 3 h: after a draw alone
  unchanged (+0.014 to +0.019), after both +0.083, +0.060 and +0.046;
  the false starts 0.24, 0.21 and 0.21 a day; the electricity 13.2,
  14.0 and 15.4 % off, the day's end state 3.3, 3.9 and 4.4 degF off.

**Why dropped.** Started by every draw, it cools the top after a draw
alone, which the record does not; started only by a run's end, it
takes a part of the excess and costs the electricity and the day's end
state. The excess is after a draw on a day that has heated and lasts
hours; neither event's time alone marks it. A gain in the starts
of one or two over the 29 days does not outweigh the rest.

**Account.** :doc:`simulator`, "Accuracy" (the record's upper probe
after a draw and heating, after 10-18). The patch and the scores are
kept with the site's scores (``record-top-2026-11-05``).


A higher axial conductance, for the drift after a draw (2026-11-05)
===================================================================

**Tried.** The tank's axial conductance
(``TankParams.conductance_btu_hr_f``, fitted 0.55 BTU/hr·°F, 0.50 in
``default_params``) at 3, 10 and 30, so that the top of a tank a draw
has stratified cools faster as the record's does, where a rested tank,
nearer uniform, would be left alone. Scored in the day backtest of the
29 days held out from 2026-09-18 on the parameters in use otherwise, at
``DrawParams.meter_reads`` 0.85 (measured 2026-11-05).

**Found.** Rested coasts moved too: at 3 a quiet half hour before the
day's first draw drifts -0.21 degF an hour against 0.00, one after a
draw -0.16 against +0.08; the conductance moves both alike, by about
0.09 degF an hour for each BTU/hr·°F to 3. At 3 the false starts went
from 0.28 a day to 0.41 and the missed from 0.45 to 0.69, the
electricity 40.6 % off against 12.9, the standby's upper probe 1.14 degF
RMS against 0.21, the upper gap at 15:00 a median -1.38 degF against
+0.30. At 10 and 30 the false starts (0.59 and 0.79), the missed, the
standby's upper probe and the 15:00 gap were worse still; the
electricity was 29.6 and 43.2 % off.

**Why dropped.** It cannot take the drift after a draw without taking
the rested coasts with it, and the starts, the electricity, the standby
and the day's end state were worse at the least tried.

**Account.** :doc:`simulator`, "Accuracy" (the day's walk across the
held-out days, after 10-18).


The start triggers read through a lagged lower probe (2026-11-04)
=================================================================

**Tried.** The heat pump's start triggers reading the walk's lower probe
through a first-order lag, the tank's heat, the recovery's stop and the
elements' own rules reading the walk's own zones (with the heat pump out
of its range the elements' entry read the lagged one too, and in Energy
Saver a draw's drop could no longer start the heater; every held-out day
is in Heat Pump), so that a large draw's drop reaches the triggers over
minutes, as the record's probe shows it (:doc:`simulator`, "Accuracy",
the lower probe after a large draw). The time constant was fitted on the
95 clean compressor-off draws of 8 gal or more from 05-01 to the meter's
step, by the RMS of the lower probe over the hour after each, walked as
the score walks them: 18.75 minutes, 3.9 degF against 7.7 unlagged, and
on the 28 held out 4.8 against 8.4 at ``DrawParams.meter_reads`` 0.85
and 5.9 against 6.7 as metered (where 8 to 10 minutes gives the least,
5.0). Scored in the day backtest of the 29 days held out from 2026-09-18
on the parameters in use, on 384170e (a patch, not merged), at 18.75
minutes with ``meter_reads`` 0.85 and 1, and at 10 minutes (where, over
the 95, the record's lower probe comes to half its fall when the lagged
walk's does) with 0.85.

**Found.** At 0.85 and 18.75 minutes the false starts stayed 0.28 a day
and the missed went from 0.45 to 0.52; the electricity 13.9 % off
against 12.9, a mean 5.0 % low against 2.4; the end state 3.7 degF off
against 3.1. At 10 minutes the false starts stayed 0.28, the missed went
to 0.48, the electricity 14.1 % off, 4.5 % low, the end state 3.9 degF
off. As metered at 18.75 minutes the false starts went from 0.17 to 0.24
and the missed from 0.45 to 0.55, the electricity 16.4 % off against
14.3, 12.1 % low against 9.8. At 0.85 and 18.75 minutes 10-11's early
start came right and 10-24 had one false start fewer, but came out 41 %
low against 21 % high, and 09-28's three starts, placed at 0.85, were
all lost to the score: its start at the window's close went and the
other two came 30 and 58 minutes late. 09-18's stayed early, starting at
19:29, 32 minutes after the draw and 85 before the record's start:
walked over the hour after that draw from the record's state there (as
"Accuracy" measures it), the walk's lower probe settles at 103.6 to
104.6 degF, under the 104.9 trigger, where the record's settles at
109.6, and the day's walk falls further (101.0 degF at 19:00 unlagged),
so the lagged probe crosses too. 09-23's early start, the upper zone's
at the window's opening, whose trigger reads the upper probe, stayed
early: it moved from 03:03 to 03:11, 49 minutes before the record's.

**Why dropped.** No fewer false starts at 0.85, more missed at either
reading, and the day's electricity and end state worse. Of the early
starts after a large draw at 0.85, the lag put right one that was how
soon the walk's lower probe fell (10-11), and not one that was how far
(09-18).

**Account.** :doc:`simulator`, "Accuracy" (the lower probe after a large
draw); "Every timed draw walked over its span, the days", below.


Every timed draw walked over its span, the days (2026-11-04)
============================================================

**Tried.** In the day backtest of the 29 days held out from 2026-09-18,
on the parameters in use, every draw the draw detector times walked over
its span, instead of only those at ``DrawParams.undiluted_gpm`` or
faster (``sim_score._timed`` patched, on 7f2dbcb, not merged), at
``DrawParams.meter_reads`` 1 and 0.85.

**Found.** At 0.85 the false starts went from 0.28 to 0.24 a day and the
missed from 0.45 to 0.48; the electricity 15.3 % off against 12.9, a
mean 6.3 % low against 2.4; the end state 4.2 degF off against 3.1. As
metered the false starts stayed 0.17, the missed went to 0.48, the
electricity 15.8 % off against 14.3, a mean 11.4 % low against 9.8. At
0.85 the starts moved rather than came right: 09-23's at the window's
opening came 26 minutes before the record's instead of 57, inside the
score's 30; 10-24's extra one at the close went, but the day came out 41
% low against 21 % high; 09-28's and 10-20's at the close, which 0.85
had placed, were lost, 10-20 coming out 42 % low again; 09-18's and
10-11's early starts stayed early, 10-11's by 28 minutes more.

**Why dropped.** Worse on the day's electricity, its end state and the
missed starts at either reading, and it moves starts rather than fixing
them.

**Account.** :doc:`simulator`, "Accuracy" (the lower probe after a large
draw); "A metered draw timed by the draw detector", below, the same
timing judged on the recoveries.


The tank refitted with the earlier draws on today's meter (2026-11-03)
======================================================================

**Tried.** The site's tank refitted on the record before 2026-09-18 on
the code of 2026-11-03 (21fffe0), every draw before the house meter's
step (2026-09-12 19:51 UTC) taken as 0.90 of its metered gallons, so
that the draws the fit reads are in today's meter's gallons ("The draws
before the meter's step scaled down", below), beside the same refit on
the draws as metered; both started from the code's own parameters (the
tank fitted on the whole record to 10-26), as "The tank refitted with
the slower draw's share fixed" (below) was. At 0.90 the refit was also
started from the parameters in use (fitted before 2026-09-18, f7e7f48).
Held out from 2026-09-18 and scored against the parameters in use on the
same code.

**Found.** On the draws as metered the refit left the code's tank for
about the place the share's refit had found (the inlet zone 10.7 gal
against its 10.7, the lower probe's spread 3.09 gal against 3.10, the
bottom's loss 0.34 BTU/h per degF against 0.37): the recoveries 20.0 min
off (14.5-25.3) against 12.8 (8.7-17.7) for the parameters in use, the
draw-free 9.5 against 4.8, those with water in use 27.3 against 18.3,
the lower probe after the 46 draws 1.99 degF RMS against 1.74; the quiet
windows' lower probe 0.42 against 0.48 and the day's electricity 13.7 %
off against 14.3. At 0.90 the tank's fit took no step from the code's
tank, its terms and losses coming back as they went in, and refitted the
heat pump's maps (its heat 0.5 % less, its power's slope by the air 8.4
% more): the recoveries 12.2 (8.3-16.7), the draw-free 4.8, with water
in use 17.3, the lower probe 1.71, the quiet windows' upper probe 0.193
against 0.205, the day's electricity 14.1 %, all inside the intervals of
the parameters in use, but not held out for its tank, which was fitted
on the record to 10-26. Started from the parameters in use, at 0.90 it
moved no term by more than 0.2 % and scored as they do.

**Why dropped.** At 0.90 the tank's fit found no step that lowered its
cost from the code's tank, and moved no term over 0.2 % from the
parameters in use, so it adds no tank of its own; whether the scale or
the cost's roughness under its finite differences held it there, the run
does not show. Nor does it show the meter's step moving the refit off:
the code's tank was fitted on the draws as metered too, over the record
to 10-26, so the refit's move may come of its shorter record as much as
of the gallons. The scale itself is not measured ("The draws before the
meter's step scaled down"); the parameters in use are kept.

**Account.** :doc:`simulator`, "Accuracy". The scores, drivers and
parameters are kept with the site's scores
(``onemeter-refit-2026-11-03``).


A refit on today's meter alone (2026-11-03)
===========================================

**Tried.** The parameters refitted on the record from 2026-09-12 20:00
UTC, after the house meter's step, to 10-11 local, so that the draws the
fit reads and those a scheduler reads today are in one meter's gallons,
and scored on 10-11 to 10-26 against the parameters in use (fitted
before 2026-09-18), score-only on the same record (:doc:`simulator`,
"Accuracy", the lower probe's error after a large draw; "The draws
before the meter's step scaled down" below).

**Found.** The four weeks hold too few draw-free climbs to fit the heat
map, which the fit left as it was; it refitted the power, the losses and
the tank (``ua_bottom`` 0.60 to 1.78 BTU/h per degF, ``inlet_mix_gal``
13.8 to 16.6, the probes' spreads narrower). Over the 12 held-out days,
the parameters in use against the refit: the recoveries 13.2 min off
(11) against 19.4, the draw-free 4.3 (5) against 8.0, those with water
in use 20.7 (6) against 28.9; the lower probe after the 16 draws 2.01
degF RMS against 2.11; the upper probe in standby 0.210 degF RMS against
0.256 (25 windows, its interval 0.22 to 0.30 clear of 0.210); the day's
electricity 24.7 % off against 23.8, a starts placed share of 0.65
against 0.55.

**Why dropped.** Worse or no better on every score but the day's
electricity, inside its interval, on held-out days too few to set it
apart. A refit in one meter's gallons over a longer record, or with the
earlier draws on a measured scale, would be the next try.

**Account.** :doc:`simulator`, "Accuracy". The scores, the driver and
the parameters are kept with the site's scores
(``poststep-refit-2026-11-03``,
``params-site-fit-poststep-4ee2fd2.json``).


The draws before the meter's step scaled down (2026-11-03)
==========================================================

**Tried.** Every draw before 2026-09-12 19:51 UTC, when the house meter
(a Droplet) whose gallons size the draws began reading the circulation
pump's runs lower, taken as a fraction of its metered gallons, in the
replay and the walk, on the parameters in use, no refit: against the
lower probe's error after a large draw changing near then and the
recoveries with water in use running long before 2026-09-18
(:doc:`simulator`, "Accuracy"). The fractions: 0.90, 0.87 and 0.81 (the
house's draw detector's ratio of meter to pump after the step).

**The meter.** Over the pump's runs with no draw within 5 minutes, the
meter's volume over the pump's reads lower the shorter the run (before
the step 0.86 at under 5 of the pump's gallons, 45 runs; 0.91 at 5 to 8,
113; 0.94 at 8 to 12, 60) and falls through the record at like length:
at 5 to 8 gallons 0.98 in April (2 runs), 0.93 in July (46), 0.88 over
08-01 to 08-14 (61), 0.86 from 08-15 to the step (4), 0.84 from the step
to 09-30 (17) and 0.76 in October (24); at 8 to 12, 0.94 from 08-15 to
the step (25) and 0.87 from it to 09-30 (4). So few runs on one side of
the step do not fix its size. Only the medians of April and of the week
of 07-06 come within 3 % of the pump here. The showers (draws of 5 min
or more at 0.6 gal/min or more) read a median 1.12 gal/min before the
step (288) and 0.96 after (86), the months pooled.

**Found.** The lower probe's fall to its lowest in the hour after the
same 117 draws of 8 gal or more from 05-01 local to the step, the
compressor off, went from a mean 1.67 degF too far to 0.92, 1.66 and
3.09 too short at 0.90, 0.87 and 0.81 (a standard error of about 0.3);
the 4 after the step before 2026-09-18 stayed at 3.03 (the held-out
draws, which it does not scale, were not rerun; measured, 2.2 short, a
standard error of 0.8). April's 16 went from 1.6 short to 4.9, 5.9 and
7.7. At 0.87 and 0.81, the 76 recoveries with water in use before the
step went from 25.8 min long (28.4 off) to 20.3 (23.5) and 18.8 (22.7),
and the 10 draw-free, through the state the replay gives them, from 11.1
off (0.3 short) to 11.6 (0.2 long) and 11.8 (0.4 long).

**Why dropped.** The step's size the record does not fix, and at 5 to 8
gallons the meter drifted besides. Over 0.90 to 0.81 the draws from
05-01 to the step go from 0.9 to 3.1 degF short, against 2.2 for those
held out; April's go further from them; at 0.87 about four fifths of the
recoveries' long run stays. Which of the meter's readings is right the
record does not say, and the pump's figure is its own estimate, not a
measure. The draws are kept as metered. A volume measured at a tap later
put the meter at 0.85 on 2026-11-03 (:doc:`simulator`, "Accuracy"), but
the meter's reading of the pump's runs went on falling after the step,
so that one fill does not give its scale on earlier days; rescaling the
record's draws, and a refit on them, would want more such measurements.

**Account.** :doc:`simulator`, "Accuracy". The scores and scripts are
kept with the site's scores (``meter-step-2026-11-03``).


The condenser's heat rising as a plume (2026-11-03)
===================================================

**Tried.** The condenser's heat put, each step, into the highest layer
from the condenser's top up that is no warmer than its water plus 10 or
20 degF, as a plume rising past colder water would leave it (the
condenser's top layer itself where that is warmer), instead of into the
layers it wraps, in the walk and in the replay that starts it, on the
parameters in use, no refit, over the 116 scored recoveries from
2026-04-17: against the walk's slow climb before its probes come
together (:doc:`simulator`, "Accuracy").

**Found.** Per recovery, minutes off (mean bias), at 10 and 20 degF: the
11 held-out draw-free went from 4.8 (2.2 long) to 42.9 and 43.0, all
short, their electricity from 4.0 % to 42.3 % and 42.5 % off; the 16
held out with water in use from 18.3 (1.7 short) to 86.5 and 87.0, all
short; before 2026-09-18 the 10 draw-free from 11.1 to 42.0 and 42.2 and
the 79 with water in use from 27.7 (25.2 long) to 56.3 and 56.5, a mean
51.2 and 51.4 short. The recovery of 2026-08-12 03:32 UTC went from 38.3
min short to 112.7 and 114.5.

**Why dropped.** Far short in every group. By construction none of the
condenser's heat goes in below its top layer, under both probes (only
the layers' conduction carries any down), and the lower probe stops the
walk; the walks' layers were not kept. The excess barely mattered.

**Account.** :doc:`simulator`, "Accuracy". The scores and the patch are
kept with the site's scores (``mixed-cold-recovery-2026-11-02``).


The condenser's span higher, or the heat scaled down (2026-11-02)
=================================================================

**Tried.** On the parameters in use, no refit, over the 116 scored
recoveries from 2026-04-17, against the two errors of :doc:`simulator`'s
"Accuracy" (the walk slow before its probes come together, about a tenth
fast once they have): the condenser's span to 0.40 at its top instead of
the fitted 0.272, so its heat reaches the lower probe sooner; the heat
map scaled by 0.91 (its heat and its slopes), so a mixed climb comes at
the record's pace; and both.

**Found.** Per recovery, minutes off (mean bias), for the span, the
scale and both: the 11 held-out draw-free from 4.8 (2.2 long) to 4.0
(0.6 long), 19.5 (18.9 long) and 17.5 (16.9 long), their electricity
from 4.0 % to 3.8 %, 10.9 % and 12.0 % off; the 16 held out with water
in use from 18.3 (1.7 short) to 19.6 (8.9 short), 42.4 and 32.9; before
2026-09-18 the 10 draw-free from 11.1 to 18.1, 14.6 and 19.6, their
electricity from 20.1 % to 39.0 %, 28.1 % and 46.1 % off, and the 79
with water in use from 27.7 (25.2 long) to 20.7 (17.0 long), 57.2 and
47.5. The recovery of 2026-08-12 03:32 UTC went from 38.3 min short to
47.6, 1.0 and 11.1 short.

**Why dropped.** The span helps most of the recoveries with water in use
before 2026-09-18 (66 of 79), not those held out (8 of 16), and makes
most that start with the probes together worse (11 of 15), the mixed
cold start further short; the scale lengthens nearly every recovery;
both together are worse than either where it helped. None was refitted
with the tank's other terms, which were fitted together with the span
and the map as they are.

**Account.** :doc:`simulator`, "Accuracy". The scores are kept with the
site's scores (``mixed-cold-recovery-2026-11-02``).


The condenser's span reaching the bottom (2026-11-02)
=====================================================

**Tried.** The condenser's span from 0.08 or 0 instead of the fitted
0.159 (``TankParams.condenser_span``, to 0.272 as fitted), the other
parameters as in use, no refit, over the 116 scored recoveries from
2026-04-17: the bottom taking the condenser's heat itself, rather than
by the stir of the entry below.

**Found.** Per recovery, minutes off (mean bias), at 0.08 and at 0: the
11 held-out draw-free went from 4.8 (2.2 long) to 26.0 (22.9 long) and
44.6 (38.3 long), their electricity from 4.0 % to 15.7 % and 27.6 % off;
the 16 held out with water in use from 18.3 (1.7 short) to 45.6 and
64.7; before 2026-09-18 the 10 draw-free from 11.1 to 14.0 and 22.7, the
79 with water in use from 27.7 to 57.9 and 80.0. At 0 the three that ran
furthest short came right as with the stir: 2026-08-12 03:32 UTC 3.1 min
long, 09-30 02:51 4.8 short, 10-23 22:48 4.1 short.

**Why dropped.** As the stir: a bottom that takes heat lengthens nearly
every recovery, so, on the parameters fitted with the span at 0.159, the
walk's balance on the others rests on a bottom that stays cold, and the
record's probes do not show which recoveries' bottoms take heat.

**Account.** :doc:`simulator`, "Accuracy". The scores are kept with the
site's scores (``mixed-cold-recovery-2026-11-02``).


The water below the condenser stirred through a run (2026-11-02)
================================================================

**Tried.** The start's stir (``stratified.stir``: the water the
condenser wraps and the water below it pooled to their mean) on every
step while the compressor heats, not only at its start, in the walk and
in the replay that starts it, on the parameters in use (fitted before
2026-09-18, the share at 0.25), over the 116 scored recoveries from
2026-04-17. A recovery from a mixed cold tank had climbed 1.11-1.15
times as fast as the map's heat warms the whole tank, its bottom left
cold (:doc:`simulator`, "Accuracy").

**Found.** Per recovery, minutes off (mean bias): the 11 held-out
draw-free went from 4.8 (2.2 long) to 44.4 (38.2 long), their
electricity from 4.0 % to 27.4 % off; the 16 held out with water in use
from 18.3 (1.7 short) to 64.5 (63.3 long); before 2026-09-18 the 10
draw-free from 11.1 to 22.5 and the 79 with water in use from 27.7 to
79.8. It lengthened 106 of the 116, by a median 53.9 min. Three of the
11 that started with the upper probe under 125 degF came right, the
three that had run furthest short: 2026-08-12 03:32 UTC, from a mixed
tank, from 38.3 min short to 2.7 long, 09-30 02:51 from 46.1 to 5.2
short, 10-23 22:48 from 61.4 to 4.4 short; the other 8 ended 34.4-87.7
min long.

**Why dropped.** Far worse everywhere else. The lengthening was about as
large whatever the start, so the three came right only because they had
started about as far short; the trial does not single out what a mixed
start lacks.

**Account.** :doc:`simulator`, "Accuracy". The scores, the band table
and the patch are kept with the site's scores
(``mixed-cold-recovery-2026-11-02``).


A fast draw walked over its time in the replay (2026-11-02)
===========================================================

**Tried.** The record's replay, which starts every event and which the
tank is fitted on, walking a draw the detector times at
``DrawParams.undiluted_gpm`` or faster over its span, a piece a minute
and each the tank's water whole, as the score's own walks of an event
already do ("A metered draw timed by the draw detector", below): the
replay had taken it all at its onset, through the valve. The part of the
record replayed to a start held the draws still running at its start,
and a draw under way at an event's start was replayed timed to it. On
the installation's fitted parameters, the site's installation, the
record to 2026-10-26.

**Found.** The record's 24 element runs, each replayed from the layers
at its start through it and 30 minutes on: the upper probe 3.9 degF RMS
against 4.4 (the mean of the runs' own), held out (5 runs) 2.8 against
5.2, all of it on 2026-10-03 02:51 UTC, the run before the 53.8 gal draw
at 2.69 gal/min. Held out, the recoveries with water in use came out
18.8 min off against 18.3, more than all of it the one starting
2026-10-01 03:42 (three others came 1.3 min closer between them), 8 min
into a 31.1 gal draw at 2.10 gal/min: 18.4 min short against 9.0, its
start's bottom 5 degF warmer, which the probes' correction left in
place. Before 2026-09-18 every score moved under 0.05; the 29 held-out
days' energy came 14.33 % off against 14.31, only 10-03 moving.

**Why dropped.** The replay's element runs better, no score a decision
reads: the recoveries with water in use held out a little worse, the
rest unmoved. The replay keeps a fast draw at its onset.

**Account.** :doc:`simulator`, "Accuracy";
``reference/sim-score/replay-fast-draws-2026-11-02/`` in the checkout
(the patch and its scores; not in the repository).


An element's heat by the volume above it (2026-11-02)
=====================================================

**Tried.** The upper element's heat put into each layer by its share of
the volume above the element's height, 17.7 gal at 0.72, instead of all
into the layer at it, which turns over into the three above, 21.1 gal.
Two layers at the height sharing it heat the same 21.1 gal once they
turn over ("The upper element higher", below); this does not, so the
height no longer acts in whole layers. From a mixed 120 degF tank, on
the installation's fitted parameters, the upper probe climbs 1.89
degF/min against 1.64 (1.59 on the defaults, the figure the entries
below give), where the record's clean runs climbed 2.01.

**Found.** The record's 24 element runs from 2026-04-16, each replayed
from the layers at its start through it and 30 minutes on, the lower
element's minutes in its own layer, on the installation's fitted
parameters: the upper probe 6.0 degF RMS against 4.4 (the mean of the
runs' own), the fit period (19 runs) 6.1 against 4.2, held out (5) 5.6
against 5.2. The Energy Saver runs read closer (05-05 3.9 against 7.7,
04-30 3.1 against 5.5); the long Electric runs overshoot (05-03 13.2
against 2.7).

**Why dropped.** Worse on the runs as they happen, the fit period and
held out alike.

**Account.** :doc:`/reference/simulator-inputs`, the elements' heights;
``reference/sim-score/replay-lower-element-2026-11-02/`` in the checkout
(not in the repository).


A member's flows spread as the record's (2026-11-02)
====================================================

**Tried.** Measured, not adopted: each ``draw_ensemble`` member's long
draws run at a flow drawn from the installation's own long draws before
2026-09-18, each the slot's flow times a factor (the record draw's flow
over the 335 draws' median, 1.12 gal/min), its gallons kept; and, apart,
the draws of 20 gal or more at the factors of the record's 19 such.
Members run at the slot's mean flow, and none of their 2969 draws of 4
gal or more over the 29 held-out days reached the 2 gal/min at which a
draw takes the tank's water whole, where both of the days the tank ran
out did.

**Found.** On the 29 days, 50 members each, no day's ``cold_share``
moved either way: 0.08 and 0.02 on the two that ran out, a mean 0.04 on
the rest. The record had 4 long draws of 335 at 2 gal/min or more before
2026-09-18, 1 of its 19 of 20 gal or more (2.28 gal/min, 05-04).

**Why dropped.** It changes nothing on the record it is drawn from: this
household's fast draws are too rare before the split. Spread over all
long draws it put no fast draw in a member on either evening that ran
out; spread over the large ones, one on 09-29, 25.5 gal at 2.30 gal/min
in a member that already ran cold, and none on 10-02.

**Account.** :doc:`/how-to/simulate-heater` (``cold_share``);
``reference/sim-score/ensemble-cold-share-2026-11-02/`` in the checkout
(not in the repository).


The share at 0.1 on the score that splits a slower draw (2026-11-02)
====================================================================

**Tried.** Measured, not adopted, on the parameters fitted before
2026-09-18 (the site's installation): ``DrawParams.undiluted_share`` at
0.1 instead of 0.25, scored once ``sim_score`` split a slower draw under
way at a recovery's start, which made the recoveries with water in use
before 2026-09-18 a mean 25.2 min long. At 0.1 the fit period's draws
had favoured it (below, "The slower draw's share at 0.1").

**Found.** Before 2026-09-18 the 79 recoveries with water in use came
out 26.2 min off against 27.7, a mean 23.6 long against 25.2, and the
lower probe after the 207 draws 1.57 degF RMS against 1.78. Held out,
the 16 came out 21.0 min off against 18.3 and the lower probe after the
46 draws 1.89 against 1.74; the draw-free 5.1 against 4.8.

**Why dropped.** Held out it is worse on the recoveries and the draws,
and it leaves most of the fit period's long recoveries, where the walk
cools the tank too far at a draw with the compressor running
(:doc:`simulator`, *Accuracy*).

**Account.** ``reference/sim-score/slow-draw-under-way-2026-11-02/`` in
the checkout (``*-share-0.1.json``, ``perdraw.*``, ``rate.*``; not in
the repository).


A slower draw's rest at a start walked over its time (2026-11-02)
=================================================================

**Tried.** Measured, not adopted, on the parameters fitted before
2026-09-18 (the share at 0.25, the site's installation): with every draw
the detector timed split at an event's start (``sim_score``, now kept),
a slower draw's rest walked over the rest of its time, at its own flow,
where the score walks it all at the start, as it walks a slower draw at
its onset.

**Found.** Held out, the 16 recoveries with water in use came out 18.4
min off against 18.3, a mean 1.7 short either way. Over the 44
recoveries from 2026-04-17 to 10-26 that started inside a slower draw, a
mean 25.4 min long against 25.3, 27.0 min off against 26.9.

**Why dropped.** It scored the same and walks a slower draw two ways:
timing every draw scored worse (below, "A metered draw timed by the draw
detector").

**Account.** :doc:`simulator`, *Accuracy* (the recoveries);
``reference/sim-score/slow-draw-under-way-2026-11-02/`` in the checkout
(not in the repository).


The circulation priced at the runs' own flow (2026-11-02)
=========================================================

**Tried.** Measured, not adopted, on the parameters in use (fitted
before 2026-09-18, the share at 0.25): ``CirculationParams.flow_gpm`` at
half the 1.40 in use, against the record's recoveries with circulation
inside them, and at 1.05 gal/min, about the own flow of the runs
overlapping 07-28 16:45 UTC's recovery (1.0 to 1.2), on that recovery
alone. The six recoveries from 2026-07-08 to 08-04, each with 22 to 28
minutes of circulation, had come out 38 to 217 min long, and walked
without the runs 22 to 91 min short.

**Found.** At half the flow the 16 recoveries with circulation before
2026-09-14 came out a mean 25 min long (43 absolute) against 45 (58),
the six still 14 to 165 min long (07-28 16:45 UTC 105 against 152), and
the five from 09-14 7 min short (18 absolute) against 3 long (11). At
1.05 gal/min, walked without its setpoint write, 07-28's compressor
stopped at 354 min against 364 at 1.40, where the record's stopped at
255. At 1.40 the summer's runs' heat was already priced about as the
return line measured it, at 1.01 to 1.16 times the walk's price at 1.40
over July and August, the compressor running or off; 07-28's seven runs
overlapping the recovery, counted whole, at 0.80 (10,177 BTU against
12,744).

**Why dropped.** The price was not what ran long: the walk takes the
runs' heat where its lower probe sees it, about twice the record's fall
over a summer run, and the heat pump stops on that probe. Half the flow
undercharges the summer's runs' heat (measured 1.51 to 1.63 times its
price over July and August) and prices 07-28's about as measured (1.04),
yet leaves 07-28 at 105 min long, against 152 at 1.40. Walked at 1.05
without its setpoint write, 07-28 stopped 99 min after the record's,
against 109 at 1.40. No change.

**Account.** :doc:`simulator`, "Accuracy". The recoveries, the runs and
the scripts are kept with the site's scores
(``summer-circulation-2026-11-02``).


Long draws counted by the day (2026-11-02)
==========================================

**Tried.** Built as a scratch prototype, not merged: each member's long
draws counted once a local day, from a binomial with the day's expected
count (its slots' long rates summed) and a variance of a fitted share of
it, and placed over the day's slots in proportion to their rates, each
at a uniform instant in its slot; the short draws as before. On one
installation's 49 metered days, 2026-09-12 to 11-01, the members spread
wider than the days over the whole day and the days' counts of draws of
4 gal or more missed the members' mean by a mean square 0.49 of their
variance. The share was fitted as that ratio on one half and scored on
the other: 0.55 on the 25 days to 10-07, 0.36 on the 24 from 10-09 (300
members); scored with 500 members and two seeds against the prototype
with independent counts.

**Found.** Scored on the second half with 0.55, the day's continuous
ranked probability score came out worse in both seeds, 5.46 gal against
5.17 and 6.04 against 5.90, the evening's 4.93 against 4.80 and 4.91
against 4.83, though the whole day's squared miss rose from 0.26 and
0.30 to 0.41 and 0.45 of the members' variance, toward 1. Scored on the
first half with 0.36, the day's came out worse in both, 9.40 against
9.12 and 9.67 against 9.34, and the spread turned from too wide to too
narrow (the squared miss 1.44 and 1.41 times the variance against 0.78
and 0.70); the evening's was mixed, 8.64 against 8.78 and 8.69 against
8.54.

**Why dropped.** The halves asked for different spreads, and one fitted
on either made the other's days score worse. Worth another try over a
longer record whose daily count holds steady, or with a forecast that
publishes its counts' spread.

**Account.** :doc:`/how-to/simulate-heater`, "Weigh candidates over many
households". The days, the scripts and the scores are kept with the
site's scores (``draw-ensemble-2026-11-02``).


The mains colder, for the lower probe's error after a draw (2026-11-02)
=======================================================================

**Tried.** Measured, not adopted: the mains (``DrawParams.climate_f``'s
annual mean, moving ``cold_supply.mains_f`` with it) 5 degF colder and 5
degF warmer, in the walk and in the replay that starts it, over the 32
draws of 8 gal or more from 2026-09-18 with the compressor off for the
hour after, on the parameters in use (fitted before 2026-09-18, the
share at 0.25). The walk's lower probe fell too short over the hour
after those draws, a mean 2.2 degF, where from 05-01 to 09-17 it fell
too far; the mains are the input the walk is given that moves most with
the season.

**Found.** The mains 4.9 degF colder moved the mean error from +2.21 to
+1.50 degF and 4.8 warmer to +2.92: 0.15 degF a degF. Taking the error
out would need the mains some 15 degF colder than the model from
2026-09-18 (19 for October's draws), where an inlet probe at the heater
read them a mean 1.5 degF warmer than the model over 25 days of
2026-09-20..10-28.

**Why dropped.** The mains move the error too little, and the probe puts
the model's error on the other side. No change.

**Account.** :doc:`simulator`, "Accuracy". The draws, the quiet hours
and the scripts are kept with the site's scores
(``lower-probe-bias-2026-11-02``).


The slower draw's share at 0.1 (2026-11-02)
===========================================

**Tried.** Measured, not adopted: ``DrawParams.undiluted_share`` at 0.1
on the parameters in use (fitted before 2026-09-18), against the 0.25
``site_example_params`` sets. The share was first measured with each
draw of 8 gal or more walked alone over the hour after it, while the
record's probes over that hour held the draws after it as well: 27 of
the 137 before 2026-09-18 and 4 of the 32 after had others adding to a
gallon or more. Walked with the record's draws over the hour, the 137
put the share near 0.1, not 0.25. The numbers in
:doc:`simulator-methodology`, "A slower draw", and in the three entries
below on the share are now those walks'.

**Found.** On the 137 the walk's lower probe fell 13.6 degF against the
record's 13.7 at 0.1, within 3.90 degF RMS, against 14.9 and 4.16 at
0.25; on the 32 held out 11.7 against 14.9, 5.46 RMS, against 12.6 and
4.86. Scored held out, 0.1 came out behind 0.25: the day's electricity
15.9 % off (10.2-22.4) against 14.3, the recoveries 16.5 min (11.8-21.6)
against 14.5, the lower probe after the 46 draws 1.89 degF RMS against
1.74, and 10-21's start at 21:00 lost again (45.6 % low against 4.5);
the deliveries 1.28 gal under-promised against 1.35.

**Why dropped.** The record before the split favours 0.1 and the draws
after it 0.25 or more; held out, the days, the recoveries and the draws
came out behind. 0.25 is kept.

**Account.** :doc:`simulator-methodology`, "A slower draw".


The tank refitted with the large draws weighed more (2026-11-02)
================================================================

**Tried.** Built as a scratch patch, not merged: the site's tank
refitted as in the entry below, the share held at 0.25, on the code of
2026-11-02 (3adaad0), with each draw of 8 gal or more weighed 3.35
times, the 62 of them together as much as the 208 quiet windows; the 146
smaller draws and the 90 recoveries weighed as before. The fit weighs
each event alike, and its events before 2026-09-18 are as many draws as
quiet windows, 208 of each: the draws weighed as much as the quiet
windows, which the two entries below name, is what they measured.

**Found.** The fit raised the bottom's loss to 2.61 BTU/h·degF, from
0.60 in use and 0.37 in the refit below, and shrank the inlet zone to
8.9 gal. Held out, against the parameters in use: the 32 draws of 8 gal
or more cooled the lower probe 11.0 degF in the walk against 14.9 in the
record, 12.6 in use and 11.7 in the refit below, at 6.08 degF RMS
against 4.86 and 5.18 (each walked with the record's draws over the hour
after it, 2026-11-02); the lower probe after the 46 draws 2.03 degF RMS
against 1.74, the quiet windows' upper probe 0.299 against 0.205 and
their lower 0.443 against 0.484. The day's electricity 13.9 % off
(8.3-20.3) against 14.3, 14 % of it in another hour than the meter's
against 19, 0.10 false starts a day against 0.17, and 10-24's start
called (7.6 % low against 41.8); the starts on 10-18 and 10-20 stayed
missed and 10-21's was lost (41.4 % low against 4.5). The recoveries
18.7 min off (13.9-23.6) against 14.5, the draw-free 9.1 min (4.8-14.2)
against 4.8.

**Why dropped.** Weighed more, the large draws' fall came out further
from the record's, not nearer, and the quiet windows' upper probe, the
draws and the recoveries worse; better on the day's electricity and its
hours, the false starts, 10-24's start and the quiet windows' lower
probe. The parameters in use are kept. What would make it worth another
try: a change to how a draw cools the tank, which no fit of these terms
has found.

**Account.** :doc:`simulator-methodology`, "A slower draw".


The tank refitted with the slower draw's share fixed (2026-11-02)
=================================================================

**Tried.** Measured, not adopted: the site's tank refitted on the
record before 2026-09-18 on the code of 2026-11-02 (bd86a7c), its
terms as before and ``DrawParams.undiluted_share`` held at 0.25. The
parameters in use were fitted on the code before the share (f7e7f48).

**Found.** The refit moved the tank's terms more than the share's own
fit did: the lower probe's height 0.485 to 0.472 and its spread 2.31 to
3.10 gal, the inlet zone 13.8 to 10.7 gal, the bottom's loss 0.60 to
0.37 BTU/h·degF; the heat pump's heat and power within 0.6 %, their
slopes by air and water within 3.6 %. Held out, against the parameters
in use with the share at 0.25: the day's electricity 13.7 % off
(8.3-20.0) against 14.3, 15 % of it in another hour than the meter's
against 19, 0.10 false starts a day against 0.17, and 10-24's start
called (10.1 % low against 41.8); 10-21's start at 21:00 was lost again
(40.8 % low against 4.5). The recoveries 18.4 min off (13.4-23.1)
against 14.5, the draw-free 9.3 min (5.1-14.0) against 4.8 and their
electricity 6.7 % (4.6-9.1) against 4.0; the lower probe after the 46
draws 1.99 degF RMS against 1.74, the quiet windows' lower probe 0.423
against 0.484 and their upper 0.235 against 0.205.

**Why dropped.** The refit takes back most of what the share gave the
draws, the lower probe's fall after them as far off as before it, and
the draw-free recoveries came out twice as far off, outside the interval
of the parameters in use. The parameters in use are kept. The fit
already weighs the draws as much as the quiet windows, 208 of each; the
large draws weighed more were tried after (above).

**Account.** :doc:`simulator-methodology`, "A slower draw".


The slower draw's share fitted with the tank (2026-11-01)
=========================================================

**Tried.** Built as a scratch patch, not merged:
``DrawParams.undiluted_share`` added to the tank fit's terms
(``tank_fit.TERMS``, 0 to 1, from 0.25) and the site's tank refitted
with the others on the record before 2026-09-18, the code of 2026-11-01
(9e8dfc8).

**Found.** The fit put the share at 0.08 and moved the other terms
little (the lower probe's height 0.485 to 0.490 and its spread 2.31 to
2.64 gal, the inlet zone 13.8 to 13.1 gal). The fit weighs each event
alike, the quiet windows with the draws. Held out, against the merged
code (the earlier parameters, the share at 0.25): the day's electricity
15.9 % off (10.3-22.2) against 14.3, the recoveries 17.3 min (12.6-22.4)
against 14.5, the draw-free 6.3 against 4.8, the lower probe after the
46 draws 2.00 degF RMS against 1.74, the quiet windows' upper probe
0.221 against 0.205; their lower probe 0.456 against 0.484, the
deliveries 1.25 gal under-promised against 1.35, and 0.14 false starts a
day against 0.17. The starts missed on 10-18, 10-20 and 10-24 stayed
missed, and the one at 21:00 on 10-21 the merged code calls was missed
again: that day 41.2 % low against 4.5.

**Why dropped.** Worse on the days, the recoveries, the draws and the
quiet windows' upper probe, all inside their intervals, and 10-21's
start lost; better on the quiet windows' lower probe, the deliveries and
the false starts. Measured apart on the draws' own fall, the record
before 2026-09-18 puts the share near 0.1 and the held-out draws 0.25 or
more; held out, 0.25 scored ahead of 0.1 (above). The fit weighed the
draws as much as the quiet windows already, 208 of each; the large draws
weighed more were tried after (above).

**Account.** :doc:`simulator-methodology`, "A slower draw".


Every draw taking the tank's water whole (2026-11-01)
=====================================================

**Tried.** Measured, not built: whether the meter counts the tank's
inflow rather than the tap's, so that every draw takes as much of the
tank's water as it delivers, as a fast draw does
(:doc:`simulator-methodology`, "A fast draw"). The 32 held-out draws of
8 gal or more with the compressor off for the hour after, each walked
from the record's state at its onset with the record's draws over the
hour (2026-11-02), on the parameters fitted before 2026-09-18, the
tank's water whole (the share at 1).

**Found.** The walk's lower probe fell a mean 17.5 degF against the
record's 14.9, within 5.36 degF RMS against the valve's 5.92, and less
than the record's on 7 of the 32 against the valve's 29: it overshot as
far as the valve fell short. On the 137 before 2026-09-18 it overshot
further: 21.5 against 13.7, 9.91 RMS against the valve's 4.07.

**Why dropped.** The record sits between the two. A quarter of the cold
side's share from the tank as well came within 4.86 degF RMS of the 32
held out after 2026-09-18, and is what was kept.

**Account.** :doc:`simulator-methodology`, "A slower draw".


A larger inlet zone for a fast draw (2026-10-31)
================================================

**Tried.** Measured, not built: whether the record's fast draws (2.1-2.7
gal/min, :doc:`simulator-methodology`, "A fast draw") mix more of the
tank, rather than take more of it. Each of the 24 draws of 20 gal or
more replayed for 40 min from the record's state 2 min before it, the
heat off, on the parameters fitted before 2026-09-18, with
``inlet_mix_gal`` at 13.8 (fitted), 25, 40 and 63.2 gal (the tank).

**Found.** No zone reproduced them. On 09-29 19:42 (30.8 gal at 2.35
gal/min) the record's upper probe reached 80.8 degF. The walk's
reached 97.2 at the fitted zone, 87.5 at 40 gal, and 104.9 with the
whole tank mixed: mixing keeps the tank's heat, and the record's tank
lost more. The same on 09-30 20:33 (81.5 against 101.1 at best) and 10-02
20:01 (97.3 against 96.8 at 40 gal but 103.1 at the whole tank). The
slower draws, at 13.8 gal, came within a few degF, and at 40 gal or
more their upper probe 6-23 degF under the record's (04-28's, already
35 under at the fitted zone, further).

**Why dropped.** Mixing cannot remove heat. The tank water each fast
draw took, about 1.3 times the valve's share, is what moved it, and is
what was kept.

**Account.** :doc:`simulator-methodology`, "A fast draw".


A metered draw timed by the draw detector (2026-10-31)
======================================================

**Tried.** Each metered draw run from its onset for as long as the
draw detector held, instead of all at the onset, in the replay that
starts every event, the recoveries' walks and the draw events: for
the length of the last detector span starting no more than 10 min
after the onset, if it ends no more than 2 min before it, the
detector's dropouts under 3 min joined, cut short at the next draw's
onset. A span over an hour times none. Of the 1791 draws 1753 were
timed, a median 4.7 min; 17 were left at their onset by the hour, 21
had no span. Fitted before 2026-09-18 and scored on the 27 recoveries after,
on the site's installation (code 4693d3c, not merged).

**Found.** The inlet zone set by hand from 1 to 45 gal, or the
condenser's span moved to 0.25-0.37 or 0-0.11, left the walk's lower
probe within 2 degF at 10 min of where it was at the start of the
recoveries of 2026-09-22 17:14 and 2026-10-13 13:09 UTC, where the
record's fell 13-15 degF. Those two showers ran on into the recovery.
The meter put 16.0 gal at 4.8 min before the first start; the heater's
own flag came on 3.7 min before it and the detector held from 0.9 to
13.2 min after. The record's lower probe fell from 117.5 degF 4 min
before the start to 104.7 at it and 90.3 10 min after. The walk, taking
the draw at the meter's onset, had fallen to 103.1 at the start and
moved under 1 degF over the next 10 min. On 10-13 the meter put 10.2
gal at 3.3 min before; the detector held from 0.8 min before to 8.3
after; the record fell 22.5 degF in all. Timed, on the base's terms,
the 16 recoveries with water in use came out 34.3 min off against
42.5, a mean 19.4 short against 34.1, and the 11 without 6.2 against
5.7. Refitted, the 16
came out 37.9 min off, a mean 31.5 short; the 11 without 6.9 against
5.7, a mean 3.2 short against 3.1 long; the lower probe after a draw
1.65 degF RMSE against 2.01, the upper 0.24 against 0.30; the day's
energy 17.5 % off against 16.5. Every score but the draw-free
recoveries' mean stayed inside the base's interval; that went from
3.1 min long to 3.2 short, outside it. The refit shortened each of the
16, by 5.5-18.7 min against the timed walk on the base's terms, about
12 in the middle. The recovery of 2026-10-23 22:48, with its 15.4 gal
draw 48 min in, came out 66.5 min short timed against 65.6, and 79.0
refitted; the one of 2026-09-30 02:51 stayed over 260 min short.

**Why dropped.** Mixed: the draws and the recoveries with water in use
better, the draw-free recoveries and the day's energy worse, the
draw-free recoveries' mean outside its interval. The refit kept 4.5 of
the 8.2 min the timing took off the recoveries' error, and 2.6 of the
14.7 off their mean shortfall.

Kept since for a draw at ``DrawParams.undiluted_gpm`` or faster only:
the score walks it over its detector span, and a 54 gal draw at 2.7
gal/min taken at its onset started the element 19 min early on
2026-10-02 (:doc:`simulator-methodology`, "A fast draw").

**Account.** :doc:`simulator`, "Accuracy"; :doc:`simulator-methodology`,
"How a draw moves the tank".


The lower probe allowed higher (2026-10-31)
===========================================

**Tried.** The tank refitted with the lower probe's height free to
0.75 of the column instead of 0.5, after the held-out recoveries with
water in use (drawn, or the circulation running) inside them or in the
30 minutes before came out short, a mean 34.1 min; the five 38 min or
more short (38-284) each start within 30 minutes of 10-31 gal drawn,
or have a 15 gal draw inside. Fitted before 2026-09-18 and scored on
the 27 recoveries after, on the site's installation.

**Found.** The fit had not been held by the bound: the height came out
0.481 against the base's 0.485, which was already 0.015 under the old
bound, and every held-out score stayed inside its interval (the 16
recoveries with water in use 41.6 min off against 42.5, a mean 32.8
short against 34.1; the 11 without 5.6 against 5.7). The shortfall
follows the water drawn in the 30 minutes before the start (correlation
-0.63 over 15 of the 16, the one of 2026-09-30 02:51 UTC, 284 min short,
left out) more than the water drawn inside it (-0.43), and neither the
start's correction to the probes (at most 1.6 degF, mostly cooling) nor
the circulation (none on 13 of the 16) nor the mains (a mean 1.5 degF
under an inlet probe, 0.1-3.9 over 25 days of 2026-09-20..10-28,
``cold_supply.mains_f``) accounts for it. After the three traced draws
of 10-16 gal just before a recovery's start or inside it, the record's
lower probe fell 13-15 degF over the next 10-35 minutes, with the
compressor running, where the walk's moved under 3 degF; over the 34
held-out draws of 8 gal or more with it off, the record's fell a median
of 12.2 degF over the hour and the walk's 10.0, less on 31 of the 34,
each walked alone (re-measured on 2026-11-02 with the record's draws
over each hour, on that day's code and the share at 0: 12.0 against 10.6
over 32, less on 29). The walk's lower probe reaches its target sooner
than the record's, and the heat pump stops on that probe. The later
trial, "A metered draw timed by the draw detector", found that two of
the three traced draws ran on into the recovery, the walk having taken
all of each at the meter's onset before the start.

**Why dropped.** No change: the probe's range was not what held the
fit. A correction to a recovery's duration alone would
leave the walk's layers as they are: the lower probe read from them,
which sets the starts, and the deliverable gallons, which are read
from them directly.

**Account.** :doc:`simulator`, "Accuracy"; :doc:`simulator-methodology`,
"How a draw moves the tank".


The inlet's mixing by the draw's flow (2026-10-31)
=================================================

**Tried.** Measured, not built: whether a faster draw mixes more of the
bottom, so the inlet zone should grow with the flow. On the 45 held-out
metered draws (after 2026-09-18), each walked from the record's replay
on the defaults from the site's installation, the lower probe's error
against the draw's flow, its gallons over the minutes the draw
detector held.

**Found.** The draws ran 0.15-1.45 gal/min, but the 20 of 4 gal or
more all 0.69-1.31. With the gallons held, each gal/min added 1.1
degF (standard error 1.0) to the lower probe's error over the hour and
3.0 (1.6) over the first 20 minutes, where the draw scored at an
instant may stand in too. The error follows the gallons (its RMS
correlates 0.88 with them, 0.56 with the flow), both ways on the large
draws.

**Why dropped.** The record cannot fit a flow term. Draws of the same
volume at very different flows from a rested tank, such as 10 gal at
0.5 and at 2.5 gal/min, would.

**Account.** :doc:`simulator-methodology`, "How a draw moves the
tank".


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


The circulation's return as one volume, or a plug at the bottom (2026-10-29)
==========================================================================

**Tried.** Two forms of the loop's return before the measured pipe: an
effective loop of 19.36 gal, its return at the tank's own temperature
after it, and the measured run's return all entering at the bottom's
inlet zone, pushing the column up as a draw does.

**Found.** On the measured run of 2026-10-29 the effective loop took
9,137 BTU from the tank against 4,589 measured, from a volume three
times the pipe's 6.86 gal; it prices the record's runs better (300 BTU
a run in cross-validation against 399), but the measured pipe scores
the held-out recoveries closer (27.2 min against 30.9). The return as
a plug at the bottom took 4,442 BTU but read the lower probe 7.35 degF
RMS and the upper 2.73 over the run. The record's summer runs at the
pump's speed sweeps read the return 6-29 degF under the tank, up to
29,000 BTU/hr, more than the loop can lose; they were not taken as the
pipe's loss.

**Why dropped.** The measured pipe, with warmer return rising past the
inlet zone to where the tank is as warm, is kept.

**Account.** :doc:`standby-loss`, "The return's rest and cooling";
:doc:`simulator-methodology`, "Circulation".


The upper element higher (2026-10-29)
=====================================

**Tried.** The upper element at 0.79 of the column instead of 0.72, so
it heats 15.8 gal and the upper probe climbs 2.00 degF/min, near the
2.01 of the record's 29 clean element runs, against 21.1 gal and 1.59.

**Found.** Replaying the record's 24 element runs from 2026-04-16, most
with water drawn or the compressor running, the upper probe read 10.2
degF RMS at 0.79 against 7.9 at 0.72. Splitting the element's heat
between two layers did not smooth the step between heights.

Measured again 2026-11-02, the replay heating the lower element's
minutes in its own layer (it had put every element minute in the
upper's), on the installation's fitted parameters: 4.7 at 0.79 against
4.4 at 0.72, held out (5 runs) 5.3 against 5.2.

**Why dropped.** Worse on the runs as they happen. The height acts in
whole layers; see the 24-layer entry above for the layer count.

**Account.** :doc:`/reference/simulator-inputs`, the elements'
heights.


The heat map fitted on the model's probes (2026-10-29)
======================================================

**Tried.** The heat map refitted on the walk's own probe error over
draw-free recoveries, so it balances in the model's frame, instead of
on the record's mixed climbs.

**Found.** The map on mixed climbs already balances in the model's
frame within 0.6 % (1.006 times). The refits made the 11 held-out
draw-free recoveries worse, 6.9 min from the measured duration to 7.6
to 8.3, on the site's installation.

**Why dropped.** Worse held out. The heat stays fitted on mixed climbs;
only the power was moved, to the condenser's water on the replay.

**Account.** :doc:`simulator-methodology`, "The map";
:doc:`simulator`, "Two errors in a heat-pump recovery partly cancel".


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
partly cancel". Taken off a run under way at a scenario's start only, it
is kept (``CompressorParams.running_probes_warm_f``, 2026-11-06).


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


The condenser's span fitted on recoveries alone (2026-10-27)
============================================================

**Tried.** The condenser's span fitted on the record's recoveries
alone, apart from the tank's terms.

**Found.** It came out 0.154-0.419, and through the replayed profile it
read the quiet windows' lower probe 0.86 degF RMS against 0.52.

**Why dropped.** The span is fitted with the tank's terms, jointly on
quiet windows, draws and recoveries (``tank_fit.TERMS`` and
``CONDENSER_TERMS``).

**Account.** :doc:`simulator-methodology`, "Fitting and checking the
parameters".


Events started from the two probes (2026-10-27)
===============================================

**Tried.** Each scored event, and a scenario's start, from the profile
the two probes stand for, with no history.

**Found.** Through the simulator, the held-out draw-free recoveries
came out 15 min from the measured duration against 7.9 started from
the replay. The replay needs the record's circulation: without it the
draws' lower probe read 3.3 degF RMS against 2.1.

**Why dropped.** Each event starts from the layers 24 hours of the
record's replay leave (``HeaterState.layers_f``,
``sim_score.score(record=)``). :doc:`simulator`'s accuracy gives the
same events started from the probes for comparison.

**Account.** :doc:`simulator-methodology`, "The replay".
