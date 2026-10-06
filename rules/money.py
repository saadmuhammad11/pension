"""Money handling for the determination engine. ``FMT-01``..``FMT-04`` (BRAIN §9.14).

Why Decimal and not float
-------------------------
``FMT-02`` forbids floating point outright, and the golden case shows why in one line:

    family pension = 134,421 x 75 / 100 = 100,815.75  ->  100,816

In binary floating point 100815.75 happens to be exact, so this particular case would
survive. The next one will not: ``0.1 + 0.2 != 0.3`` and Python's ``round`` uses
banker's rounding, so ``round(100815.5)`` is 100816 but ``round(100814.5)`` is 100814 --
half-up on one and half-down on the next, on a figure someone lives on for the rest of
their life. Decimal with an explicit ``ROUND_HALF_UP`` gives one answer, forever.

``FMT-03``: intermediate values are never pre-rounded. ``rupees()`` is called once, on the
figure that is actually presented. Pre-rounding the gross pension before taking 75% of it
would give 100,816 x 0.75 rather than 134,421 x 0.75 -- a different number reached by
rounding twice.

The engine imports nothing outside the standard library, deliberately. BRAIN §6.2 requires
that the same inputs and rule pack reproduce the same output "forever", and §12.3 requires
the rules tests to run without a GPU. An auditor recomputing a 2026 determination in 2031
should need this file and a Python interpreter, not a dependency resolver.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

#: What the engine accepts as a money-ish input. Explicitly NOT ``float``.
Numeric = Union[int, str, Decimal]


class MoneyError(ValueError):
    """A money value was malformed or a float was passed. Never swallowed."""


def money(value: Numeric) -> Decimal:
    """Coerce to Decimal, refusing float at the boundary.

    Refusing ``float`` here rather than silently converting is the whole point: a float
    that reaches this function has already lost precision somewhere upstream, and
    ``Decimal(0.1)`` is 0.1000000000000000055511151231257827021181583404541015625.
    Failing loudly at the boundary is how ``FMT-02`` is actually enforced rather than
    merely documented.
    """
    if isinstance(value, float):
        raise MoneyError(
            f"float {value!r} is not accepted as money (FMT-02). "
            "Pass an int, a str, or a Decimal."
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value.strip().replace(",", ""))
        except Exception as exc:  # pragma: no cover - defensive
            raise MoneyError(f"cannot read {value!r} as money") from exc
    raise MoneyError(f"unsupported money type {type(value).__name__}")


def rupees(value: Numeric) -> int:
    """Round to whole rupees, half up. ``FMT-01``.

    Call this once, on the presented figure. 100,815.75 -> 100,816.
    """
    return int(money(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(value: Numeric) -> str:
    """Format a figure for a determination step, e.g. ``Rs. 100,816``.

    Presentation only. Never feed the result of this back into a computation.
    """
    return f"Rs. {rupees(value):,}"


def exact(value: Decimal) -> str:
    """Render an unrounded intermediate for the ``computation_shown`` string.

    ``FMT-03`` requires the engine to state where rounding occurred, which means the
    pre-rounding value has to survive into the audit record. Trailing zeros are stripped
    so that 100815.75 reads as "100815.75" and 134421 reads as "134421" rather than
    "134421.00".
    """
    d = money(value).normalize()
    # normalize() renders large integers in exponent form (1E+2); expand those back.
    if d == d.to_integral_value():
        return str(d.quantize(Decimal("1")))
    return format(d, "f").rstrip("0").rstrip(".")
