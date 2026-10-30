"""The neutral model of an invoice to write: frozen dataclasses, ``Decimal`` amounts, ``date`` dates.

The model states what the invoice says; nothing is looked up or assumed. How a business
system arrives at a category or a unit code is its own affair.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class InvoiceKind(StrEnum):
    """BT-3, UNTDID 1001."""

    INVOICE = "380"
    CREDIT_NOTE = "381"


class VatCategory(StrEnum):
    """BT-118 / BT-151, UNTDID 5305."""

    #: Standard rate; a rate above 0.
    STANDARD = "S"
    #: Reverse charge; 0 %, the VAT ids of both parties, a reason.
    REVERSE_CHARGE = "AE"
    #: Not subject to VAT; no rate, no VAT id of either party, a reason.
    NOT_SUBJECT = "O"
    #: Zero rated; 0 %, no reason.
    ZERO_RATED = "Z"
    #: Exempt; 0 %, a reason.
    EXEMPT = "E"
    #: Intra-community supply; 0 %, the VAT ids of both parties, a reason, delivery date or
    #: period and the country delivered to.
    INTRA_COMMUNITY = "K"
    #: Export outside the EU; 0 %, the seller's VAT id, a reason.
    EXPORT = "G"


@dataclass(frozen=True, slots=True)
class Party:
    """Seller (BG-4) or buyer (BG-7)."""

    name: str
    #: ISO 3166-1 alpha-2 (BT-40, BT-55).
    country: str
    street: str | None = None
    #: Second address line.
    supplement: str | None = None
    postal_code: str | None = None
    city: str | None = None
    vat_id: str | None = None
    #: The tax number at the tax office (BT-32, seller only).
    tax_number: str | None = None
    #: Identifier (BT-29, BT-46), e.g. the customer number at the seller.
    identifier: str | None = None
    #: Legal registration, e.g. the commercial register entry (BT-30, BT-47).
    legal_registration: str | None = None
    #: Electronic address (BT-34, BT-49) and its scheme (EAS code, e.g. ``EM``).
    electronic_address: str | None = None
    electronic_address_scheme: str | None = None


@dataclass(frozen=True, slots=True)
class Line:
    """An invoice line (BG-25)."""

    #: Line identifier (BT-126), unique within the invoice.
    id: str
    name: str
    quantity: Decimal
    #: UN/ECE Recommendation 20 code (BT-130), e.g. ``HUR``, ``C62``.
    unit_code: str
    #: Price per unit before the line discount. A negative price is written as a positive
    #: price with a negative quantity (EN 16931 knows no negative price, BR-27).
    unit_price: Decimal
    #: The net amount of the line (BT-131), in whole cents (BR-DEC-23).
    net_amount: Decimal
    category: VatCategory
    #: The VAT rate in percent; ``None`` for category ``O``, which has none.
    rate: Decimal | None
    description: str | None = None
    discount_percent: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class TaxBreakdown:
    """One entry of the VAT breakdown (BG-23); see :func:`einvoice_xml.tax_breakdown`."""

    category: VatCategory
    #: ``None`` for category ``O``.
    rate: Decimal | None
    basis_amount: Decimal
    tax_amount: Decimal
    #: BT-120, the reason in words.
    exemption_reason: str | None = None
    #: BT-121, the CEF VATEX code.
    exemption_reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentMeans:
    """Payment instructions (BG-16)."""

    #: BT-81, UNTDID 4461; ``58`` is a SEPA credit transfer.
    code: str = "58"
    #: BT-84.
    iban: str | None = None
    #: BT-85.
    account_name: str | None = None
    #: BT-86.
    bic: str | None = None


@dataclass(frozen=True, slots=True)
class Note:
    """An invoice note (BG-1)."""

    content: str
    #: BT-21, UNTDID 4451, e.g. ``REG`` for the legal details of the issuer.
    subject_code: str | None = None


@dataclass(frozen=True, slots=True)
class PrecedingInvoice:
    """The invoice a credit note refers to (BG-3)."""

    number: str
    issue_date: date | None = None


@dataclass(frozen=True, slots=True)
class Invoice:
    """An invoice or credit note. Totals are derived from ``tax_breakdown``."""

    kind: InvoiceKind
    number: str
    issue_date: date
    #: ISO 4217 (BT-5).
    currency: str
    seller: Party
    buyer: Party
    lines: tuple[Line, ...]
    tax_breakdown: tuple[TaxBreakdown, ...]
    #: BT-72.
    delivery_date: date | None = None
    #: BT-73, BT-74.
    period_start: date | None = None
    period_end: date | None = None
    #: BT-80: the country delivered to; needed for category ``K``.
    deliver_to_country: str | None = None
    notes: tuple[Note, ...] = ()
    #: BT-10.
    buyer_reference: str | None = None
    #: BT-13.
    order_reference: str | None = None
    preceding_invoice: PrecedingInvoice | None = None
    #: BT-83.
    payment_reference: str | None = None
    payment_means: tuple[PaymentMeans, ...] = ()
    #: BT-20.
    payment_terms: str | None = None
    #: BT-9.
    due_date: date | None = None
