"""The exceptions of the library. Everything it raises on purpose is an :class:`EInvoiceError`."""

from __future__ import annotations


class EInvoiceError(ValueError):
    """Base class: an invoice cannot be built or read."""


class InvalidInvoiceError(EInvoiceError):
    """:func:`~einvoice_xml.build_cii` was given an invoice with problems; they are in ``problems``."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("the invoice cannot become an e-invoice: " + "; ".join(problems))
        self.problems = tuple(problems)


class ReadError(EInvoiceError):
    """The input is not an e-invoice this library can read."""


class LimitExceededError(ReadError):
    """The input is larger than the limits of the reader allow."""
