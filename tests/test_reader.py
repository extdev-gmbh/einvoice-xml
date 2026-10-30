"""Reading incoming e-invoices: ZUGFeRD/Factur-X PDFs, XRechnung (CII and UBL), and refusals."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import incoming as f
import pytest

from einvoice_xml import (
    DataFormat,
    ReadError,
    ReadTax,
    TaxTreatment,
    VatSplit,
    invoice_xml_root,
    parse_invoice_xml,
    read,
    vat_split,
)


def test_zugferd_pdf() -> None:
    reading = read(f.zugferd_pdf())
    assert reading.problems == () and reading.has_amounts
    invoice = reading.invoice
    assert invoice is not None
    assert invoice.format is DataFormat.FACTUR_X
    assert (invoice.number, invoice.type_code, invoice.currency) == ("INV-2026-0815", "380", "EUR")
    assert (invoice.issue_date, invoice.due_date) == (date(2026, 9, 1), date(2026, 9, 15))
    assert (invoice.service_period_start, invoice.service_period_end) == (date(2026, 8, 1), date(2026, 8, 31))
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (
        Decimal("100.00"),
        Decimal("19.00"),
        Decimal("119.00"),
    )
    assert all(isinstance(amount, Decimal) for amount in (invoice.net_amount, invoice.tax_amount))
    assert (invoice.seller_name, invoice.seller_vat_id, invoice.buyer_vat_id) == (
        f.SELLER,
        f.SELLER_VAT_ID,
        f.BUYER_VAT_ID,
    )


def test_zugferd_pdf_with_the_legacy_attachment_name() -> None:
    reading = read(f.pdf({"notes.txt": b"hello", "ZUGFeRD-invoice.xml": f.cii()}))
    assert reading.has_amounts and reading.invoice is not None and reading.invoice.format is DataFormat.FACTUR_X


def test_xrechnung_embedded_in_a_pdf_is_read_like_the_bare_file() -> None:
    reading = read(f.pdf({"xrechnung.xml": f.ubl()}))
    assert reading.invoice is not None and reading.invoice.format is DataFormat.XRECHNUNG_UBL


def test_xrechnung_cii() -> None:
    reading = read(b"\xef\xbb\xbf" + f.cii(number="X-1"))
    assert reading.has_amounts and reading.invoice is not None
    assert (reading.invoice.format, reading.invoice.number) == (DataFormat.XRECHNUNG_CII, "X-1")


def test_xrechnung_ubl() -> None:
    reading = read(f.ubl())
    assert reading.problems == () and reading.invoice is not None
    invoice = reading.invoice
    assert invoice.format is DataFormat.XRECHNUNG_UBL
    assert (invoice.number, invoice.issue_date, invoice.due_date) == ("R-4711", date(2026, 9, 2), date(2026, 10, 2))
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (
        Decimal("250.00"),
        Decimal("47.50"),
        Decimal("297.50"),
    )
    assert invoice.seller_name == "Example Consulting GmbH"


def test_tax_total_in_the_accounting_currency_is_ignored() -> None:
    reading = read(f.cii(extra_tax_total="21.00"))
    assert reading.invoice is not None and reading.invoice.tax_amount == Decimal("19.00")


def test_plain_pdf_has_no_amounts() -> None:
    reading = read(f.pdf())
    assert reading.invoice is None and not reading.has_amounts
    assert "no embedded ZUGFeRD/Factur-X" in reading.problems[0]


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (f.cii(gross="120.00"), "do not add up"),
        (f.cii(type_code="381"), "'381' is not an invoice"),
        (f.cii(currency="euro"), "not an ISO 4217 code"),
    ],
)
def test_doubtful_data_keeps_the_header_but_drops_the_amounts(content: bytes, problem: str) -> None:
    reading = read(content)
    assert reading.invoice is not None and reading.invoice.number == "INV-2026-0815"
    assert not reading.has_amounts
    assert reading.invoice.net_amount is None and reading.invoice.tax_amount is None
    assert any(problem in text for text in reading.problems)


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (f.ubl(root="CreditNote"), "UBL credit note"),
        (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', "DTD"),
        (b"<Invoice><unclosed>", "not well-formed"),
        (b"<Order xmlns='urn:example'/>", "unknown XML document"),
        (f.cii(issued="2026-09-01"), "not a date"),
        (f.cii(net="1OO.00"), "not a number"),
        (f.cii(net="1E+999999"), "not a number"),
        (f.cii(net="1_000.00"), "not a number"),
        (f.cii(net="NaN"), "not a number"),
        (b"\x89PNG\r\n\x1a\n", "neither a PDF nor XML"),
        (b"%PDF-1.7 broken", "cannot be read"),
        (f.pdf({"factur-x.xml": b"<Order/>"}), "no ZUGFeRD/Factur-X invoice"),
    ],
)
def test_unreadable_data_gives_a_reason_and_no_invoice(content: bytes, problem: str) -> None:
    reading = read(content)
    assert reading.invoice is None
    assert problem in reading.problems[0]


def test_a_ubl_invoice_is_not_accepted_inside_a_pdf() -> None:
    with pytest.raises(ReadError, match="unknown XML document"):
        parse_invoice_xml(f.ubl(), embedded=True)


def test_invoice_xml_root() -> None:
    assert invoice_xml_root(f.cii()) == "CII"
    assert invoice_xml_root(f.ubl()) == "UBL invoice"
    assert invoice_xml_root(f.ubl(root="CreditNote")) == "UBL credit note"
    assert invoice_xml_root(b"<Order/>") is None
    assert invoice_xml_root(b"no xml") is None
    assert invoice_xml_root(b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>') is None


@pytest.mark.parametrize("build", [f.cii, f.ubl])
def test_payee_account_payment_means_and_buyer_id(build) -> None:  # type: ignore[no-untyped-def]
    reading = read(build(payment_means=[("58", f.PAYEE_IBAN, "Example Hosting GmbH", "cobade ffxxx")], buyer_id="K-1"))
    assert reading.problems == () and reading.invoice is not None
    invoice = reading.invoice
    assert invoice.payee_account is not None
    assert (invoice.payee_account.iban, invoice.payee_account.account_name, invoice.payee_account.bic) == (
        f.PAYEE_IBAN,
        "Example Hosting GmbH",
        "COBADEFFXXX",
    )
    assert (invoice.payment_means_code, invoice.buyer_id, invoice.direct_debit) == ("58", "K-1", False)


@pytest.mark.parametrize("build", [f.cii, f.ubl])
def test_several_different_ibans_give_no_account(build) -> None:  # type: ignore[no-untyped-def]
    reading = read(build(payment_means=[("58", f.PAYEE_IBAN, None, None), ("58", f.OTHER_PAYEE_IBAN, None, None)]))
    assert reading.has_amounts and reading.invoice is not None and reading.invoice.payee_accounts == ()
    assert "2 different payee IBANs" in reading.problems[0]


def test_the_same_iban_twice_is_one_account_with_what_either_states() -> None:
    written = "DE89 3704 0044 0532 0130 00"
    reading = read(f.cii(payment_means=[("58", f.PAYEE_IBAN, None, None), ("30", written, "Name", "COBADEFF")]))
    assert reading.invoice is not None
    assert [(a.iban, a.account_name, a.bic) for a in reading.invoice.payee_accounts] == [
        (f.PAYEE_IBAN, "Name", "COBADEFF")
    ]


def test_an_invalid_iban_is_dropped_and_the_amounts_stay() -> None:
    reading = read(f.cii(payment_means=[("58", "DE00 1234 5678", None, None)]))
    assert reading.has_amounts and reading.invoice is not None and reading.invoice.payee_account is None
    assert "is invalid" in reading.problems[0]


def test_direct_debit_wins_over_the_first_stated_means() -> None:
    reading = read(f.ubl(payment_means=[("58", None, None, None), ("59", None, None, None)]))
    assert reading.invoice is not None and reading.invoice.direct_debit
    assert reading.invoice.payment_means_code == "59"


def _split(*taxes: tuple[str, str | None, str, str]) -> VatSplit | str:
    reading = read(f.cii(taxes=taxes))
    assert reading.invoice is not None
    return vat_split(reading.invoice)


def test_vat_split_per_rate_highest_first_adds_up_entries_of_one_rate() -> None:
    taxes = (("S", "7", "10.00", "0.70"), ("S", "19", "100.00", "19.00"), ("Z", "0", "1", "0"), ("E", None, "2", "0"))
    assert _split(*taxes) == (
        VatSplit(
            TaxTreatment.STANDARD,
            ((Decimal(19), Decimal("100.00"), Decimal("19.00")),
             (Decimal(7), Decimal("10.00"), Decimal("0.70")),
             (Decimal(0), Decimal(3), Decimal(0))),
        )
    )  # fmt: skip


def test_vat_split_reverse_charge() -> None:
    assert _split(("AE", "0", "100.00", "0.00")) == VatSplit(
        TaxTreatment.REVERSE_CHARGE, ((Decimal(0), Decimal("100.00"), Decimal(0)),)
    )


@pytest.mark.parametrize(
    ("taxes", "reason"),
    [
        ((), "no VAT breakdown"),
        ((("AE", "0", "100.00", "1.00"),), "states a tax"),
        ((("K", "0", "100.00", "0.00"),), "the category K"),
        ((("O", None, "1", "0"), ("K", "0", "1", "0")), "the categories K, O"),
        ((("AE", "0", "1", "0"), ("S", "19", "1", "0.19")), "the category AE"),
        ((("S", None, "100.00", "19.00"),), "has no rate"),
        ((("Z", "7", "100.00", "7.00"),), "has the rate 7"),
    ],
)
def test_vat_split_never_guesses(taxes, reason: str) -> None:  # type: ignore[no-untyped-def]
    assert reason in str(_split(*taxes))


def test_vat_split_of_an_entry_without_category_or_amounts() -> None:
    reading = read(f.cii())
    assert reading.invoice is not None
    entry = ReadTax("S", Decimal(19), None, None)
    assert "lacks" in str(vat_split(replace(reading.invoice, tax_breakdown=(entry,))))
    assert "no category" in str(vat_split(replace(reading.invoice, tax_breakdown=(replace(entry, category=None),))))
