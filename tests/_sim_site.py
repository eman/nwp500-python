"""One installation's book terms, for the tests ported from it.

Those tests were written where the book's default was that site's
mixing valve. The library's default is no valve, so these stand in for
``nwp500.sim.book``'s names with the site's book terms (``EP``) as the
default, and the test bodies stay as they were.
"""

from dataclasses import fields, replace
from typing import Any

from nwp500.sim import book as _book
from nwp500.sim.defaults import SITE_VALVE
from nwp500.sim.params import BookParams

#: The site's book terms: the library's defaults with its mixing valve.
EP = replace(
    BookParams(),
    delivery_intercept_f=SITE_VALVE[0],
    delivery_slope=SITE_VALVE[1],
)

DEPLETION_THRESHOLD_F = _book.DEPLETION_THRESHOLD_F
compressor_btu = _book.compressor_btu
element_btu = _book.element_btu
standby_btu = _book.standby_btu
loss_ceiling_btu = _book.loss_ceiling_btu


class Booked(_book.Booked):
    """``book.Booked``, its terms the site's unless given."""

    def drawable_btu(self, p: BookParams | None = None) -> float:
        return super().drawable_btu(p or EP)

    def drawn(
        self, gal: float, upper_f: float, p: BookParams | None = None
    ) -> _book.Booked:
        return super().drawn(gal, upper_f, p or EP)

    def deliverable_gal(
        self, upper_f: float, p: BookParams | None = None
    ) -> float:
        return super().deliverable_gal(upper_f, p or EP)

    def aged(self, p: BookParams | None = None) -> bool:
        return super().aged(p or EP)

    def error_band_btu(self, p: BookParams | None = None) -> float:
        return super().error_band_btu(p or EP)


def site(b: _book.Booked) -> Booked:
    """``b`` as a site ``Booked``."""
    return Booked(**{f.name: getattr(b, f.name) for f in fields(b)})


def full_tank(u: float, lo: float, inlet: float, p: Any = None) -> Booked:
    return site(_book.full_tank(u, lo, inlet, p or EP))


def delivery_f(upper_f: float, p: Any = None) -> float:
    return _book.delivery_f(upper_f, p or EP)


def deliverable_from_heat(
    heat: float,
    upper_f: float,
    inlet_f: float,
    p: BookParams | None = None,
    **kw: Any,
) -> float:
    return _book.deliverable_from_heat(heat, upper_f, inlet_f, p or EP, **kw)


def tank_max_btu(
    upper_f: float, lower_f: float, ep: BookParams | None = None
) -> float:
    return _book.tank_max_btu(upper_f, lower_f, ep or EP)


def walk_booked(
    start: _book.Booked,
    points: Any,
    heating: Any,
    draws: Any,
    ambient_at: Any,
    p: BookParams | None = None,
    **kw: Any,
) -> _book.BookedPath:
    return _book.walk_booked(
        start, points, heating, draws, ambient_at, p or EP, **kw
    )
