"""Predict the full run from small rehearsals.

Each metric m (runtime, output rows, bytes) is measured at sample fractions f and fitted
to a power law  m(f) = a * f^k  in log-log space. The prediction for the full run is m(1) = a.

The exponent k is the useful part:
  k ~ 1   grows with the data (a scan, a filter, a key join against a full table)
  k ~ 0   flat (an aggregate to a fixed number of groups)
  k > 1.3 grows faster than the data: a join that multiplies rows, a sort, or a join where
          both sides were sampled (each side at f gives f^2 matches) -> treat with care
Runtime gets a fixed per-query overhead removed first (measured with a trivial query), so
small rungs do not make big runs look cheap.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

BANDS = {"high": (0.7, 1.5), "medium": (0.5, 2.0), "low": (0.25, 4.0)}
LINEAR = (0.7, 1.3)


@dataclass
class Fit:
    metric: str
    value: float | None
    low: float | None
    high: float | None
    exponent: float | None
    confidence: str            # high | medium | low | none
    points: int
    r2: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = asdict(self)
        for key in ("value", "low", "high"):
            if out[key] is not None:
                out[key] = _round(out[key])
        if out["exponent"] is not None:
            out["exponent"] = round(out["exponent"], 2)
        if out["r2"] is not None:
            out["r2"] = round(out["r2"], 3)
        if not out["notes"]:
            del out["notes"]
        return out


def _round(x: float) -> float:
    if x == 0 or not math.isfinite(x):
        return x
    digits = max(0, 3 - int(math.floor(math.log10(abs(x)))))
    return round(x, min(digits, 6))


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float, float | None]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    slope = sxy / sxx
    intercept = my - slope * mx
    if n < 3:
        return intercept, slope, None
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys, strict=False))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return intercept, slope, r2


def fit_power_law(metric: str, fractions: list[float], values: list[float | None],
                  target: float = 1.0, offset: float = 0.0) -> Fit:
    """Fit m(f) = offset + a * f^k on the points where m > offset and predict m(target)."""
    pts = [(f, v - offset) for f, v in zip(fractions, values, strict=False)
           if v is not None and f > 0 and (v - offset) > 0]
    notes: list[str] = []
    if not pts:
        if any(v is not None for v in values):
            nonnull = [v for v in values if v is not None]
            if nonnull and max(nonnull) <= offset:
                # Everything was at or below the overhead: nothing measurable grows.
                return Fit(metric, offset, offset, offset * 2 if offset else None, 0.0, "low", 0,
                           notes=["All rungs were too small to measure; the full run may still be slow."])
        return Fit(metric, None, None, None, None, "none", 0, notes=["No usable measurements."])

    if len(pts) == 1:
        f, v = pts[0]
        value = offset + v * (target / f)
        lo, hi = BANDS["low"]
        return Fit(metric, value, offset + v * (target / f) * lo, offset + v * (target / f) * hi, 1.0, "low", 1,
                   notes=["Only one usable rung; assumed linear growth."])

    xs = [math.log(f) for f, _ in pts]
    ys = [math.log(v) for _, v in pts]
    intercept, k, r2 = _linfit(xs, ys)
    predicted = math.exp(intercept + k * math.log(target))

    # Sub-linear growth (aggregations) extrapolates safely; super-linear growth does not.
    if len(pts) >= 3 and r2 is not None and r2 >= 0.9:
        confidence = "high" if k <= LINEAR[1] else "medium"
    elif len(pts) >= 2 and (r2 is None or r2 >= 0.6):
        confidence = "medium" if k <= LINEAR[1] else "low"
    else:
        confidence = "low"
        notes.append("The rungs do not line up well (noisy measurements).")

    if k > 1.3:
        notes.append(f"Grows faster than the data (exponent {k:.2f}). Likely a join that multiplies rows, a big "
                     "sort, or a join where both sides were sampled. The full run can be much bigger.")
    elif k < 0.3 and metric == "output_rows":
        notes.append("Output barely grows with the data (typical for aggregations).")

    lo, hi = BANDS[confidence]
    return Fit(metric, offset + predicted, offset + predicted * lo, offset + predicted * hi, k, confidence,
               len(pts), r2, notes)


def overall_confidence(fits: list[Fit]) -> str:
    order = ["none", "low", "medium", "high"]
    used = [f.confidence for f in fits if f.confidence != "none"]
    if not used:
        return "none"
    return min(used, key=order.index)
