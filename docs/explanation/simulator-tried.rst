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


The circulation priced at the runs' own flow (2026-11-02)
=========================================================

**Tried.** Measured, not adopted: ``CirculationParams.flow_gpm`` at half
the 1.40 in use, against the record's recoveries with circulation inside
them, and at 1.05 gal/min, about the own flow of the runs overlapping
07-28 16:45 UTC's recovery (1.0 to 1.2), on that recovery alone, on the
parameters in use (fitted before 2026-09-18, the share at 0.25). The six
recoveries from 2026-07-08 to 08-04, each with 22 to 28 minutes of
circulation, had come out 38 to 217 min long, and walked without the
runs 22 to 91 min short.

**Found.** At half the flow the 16 recoveries with circulation before
2026-09-14 came out a mean 25 min long (43 absolute) against 45 (58),
the six still 14 to 165 min long (07-28 16:45 UTC 105 against 152), and
the five from 09-14 7 min short (18 absolute) against 3 long (11). At
1.05 gal/min, walked without its setpoint write, 07-28's compressor
stopped at 354 min against 364 at 1.40, where the record's stopped at
255. At 1.40 the summer's runs' heat was already priced about as the
return line measured it, at 1.01 to 1.16 times the walk's price at 1.40
over July and August, the compressor running or off; 07-28's seven runs
overlapping the recovery, whole, at 0.80 (10,177 BTU against 12,744).

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
