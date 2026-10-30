"""Invented invoices: parties, numbers, IBANs and amounts are made up, the IBAN is the
checksum-valid example of the IBAN registry."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from einvoice_xml import (
    Invoice,
    InvoiceKind,
    Line,
    Note,
    Party,
    PaymentMeans,
    PrecedingInvoice,
    VatCategory,
    tax_breakdown,
)

IBAN = "DE89370400440532013000"
SELLER = Party(
    name="Example Software GmbH",
    street="Musterstraße 1",
    postal_code="12345",
    city="Musterstadt",
    country="DE",
    vat_id="DE123456789",
    tax_number="12/345/67890",
    legal_registration="Amtsgericht Musterstadt, HRB 12345",
    electronic_address="billing@example.org",
    electronic_address_scheme="EM",
)
BUYER = Party(
    name="Kunde Inland AG",
    street="Beispielweg 2",
    supplement="Haus B",
    postal_code="54321",
    city="Beispielstadt",
    country="DE",
    identifier="K-1001",
    electronic_address="invoices@example.com",
    electronic_address_scheme="EM",
)
_REASONS = {
    VatCategory.REVERSE_CHARGE: "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge).",
    VatCategory.NOT_SUBJECT: "Nicht im Inland steuerbare Leistung.",
    VatCategory.EXEMPT: "Steuerfreie Leistung.",
    VatCategory.INTRA_COMMUNITY: "Steuerfreie innergemeinschaftliche Lieferung.",
    VatCategory.EXPORT: "Steuerfreie Ausfuhrlieferung.",
}


def line(
    amount: str = "100.00",
    category: VatCategory = VatCategory.STANDARD,
    rate: str | None = "19",
    *,
    id: str = "1",
    **fields: object,
) -> Line:
    values: dict[str, object] = {
        "quantity": Decimal(1),
        "unit_code": "C62",
        "unit_price": Decimal(amount),
        "name": "Softwareentwicklung",
    }
    values.update(fields)
    return Line(
        id=id,
        net_amount=Decimal(amount),
        category=category,
        rate=None if rate is None else Decimal(rate),
        **values,  # type: ignore[arg-type]
    )


def invoice(*lines: Line, **fields: object) -> Invoice:
    lines = lines or (line(),)
    values: dict[str, object] = {
        "kind": InvoiceKind.INVOICE,
        "number": "RE0001",
        "issue_date": date(2026, 10, 1),
        "currency": "EUR",
        "seller": SELLER,
        "buyer": BUYER,
        "delivery_date": date(2026, 9, 30),
        "due_date": date(2026, 10, 15),
        "payment_terms": "Zahlbar ohne Abzug innerhalb von 14 Tagen.",
        "payment_reference": "RE0001",
        "payment_means": (PaymentMeans("58", IBAN, "Example Software GmbH", "COBADEFFXXX"),),
    }
    values.update(fields)
    breakdown = tax_breakdown(lines, exemption_reasons=_REASONS)
    return Invoice(lines=lines, tax_breakdown=breakdown, **values)  # type: ignore[arg-type]


FOREIGN_BUYER = replace(
    BUYER, name="Customer GmbH", country="AT", city="Wien", postal_code="1010", vat_id="ATU12345678"
)
NON_EU_BUYER = replace(BUYER, name="Customer AG", country="CH", city="Zürich", postal_code="8000")


def per_category() -> dict[str, Invoice]:
    """One valid invoice of every VAT category, and the shapes that go beyond one."""
    seller_without_vat_id = replace(SELLER, vat_id=None)
    return {
        "S": invoice(
            line("4086.50", quantity=Decimal("42.5"), unit_code="HUR", unit_price=Decimal("96.1529"), id="1"),
            line("100.00", id="2", description="Hosting\nSeptember", unit_code="MON"),
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            buyer_reference="PO-2026-0815",
            order_reference="ORDER-1",
            notes=(Note("Vielen Dank für Ihren Auftrag."), Note("Example Software GmbH, HRB 12345", "REG")),
        ),
        "S-mixed-rates-discount-negative": invoice(
            line("134.99", quantity=Decimal(15), unit_price=Decimal("9.9992"), discount_percent=Decimal(10), id="1"),
            line("2.97", rate="7", id="2"),
            line("-25.00", quantity=Decimal(1), unit_price=Decimal("-25"), id="3"),
        ),
        "AE": invoice(line("1760.00", VatCategory.REVERSE_CHARGE, "0"), buyer=FOREIGN_BUYER),
        "O": invoice(line("3600.00", VatCategory.NOT_SUBJECT, None), seller=seller_without_vat_id, buyer=NON_EU_BUYER),
        "Z": invoice(line("50.00", VatCategory.ZERO_RATED, "0")),
        "E": invoice(line("70.00", VatCategory.EXEMPT, "0")),
        "K": invoice(line("900.00", VatCategory.INTRA_COMMUNITY, "0"), buyer=FOREIGN_BUYER, deliver_to_country="AT"),
        "G": invoice(line("800.00", VatCategory.EXPORT, "0"), buyer=NON_EU_BUYER),
        "credit-note": invoice(
            line("190.00"),
            kind=InvoiceKind.CREDIT_NOTE,
            number="GS0001",
            preceding_invoice=PrecedingInvoice("RE0001", date(2026, 10, 1)),
            due_date=None,
            payment_terms="Der Betrag wird erstattet.",
        ),
    }
