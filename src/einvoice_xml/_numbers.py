"""Decimal arithmetic independent of the caller's decimal context."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, DivisionByZero, InvalidOperation, Overflow

_CENT = Decimal("0.01")


def context() -> Context:
    """A fresh context, wide enough to stay exact for every amount the library accepts."""
    return Context(
        prec=200, rounding=ROUND_HALF_UP, Emin=-999999, Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow]
    )


def round_money(value: Decimal) -> Decimal:
    """Commercial rounding (half up) to cents. Call inside ``localcontext(context())``."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)
