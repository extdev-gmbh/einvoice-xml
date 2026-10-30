"""The CII XML: what it says for each case, what problems() finds, and byte stability."""

from __future__ import annotations

import decimal
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import samples as s
from hypothesis import given
from hypothesis import strategies as st

from einvoice_xml import (
    DataFormat,
    InvalidInvoiceError,
    Invoice,
    Line,
    TaxBreakdown,
    VatCategory,
    build_cii,
    problems,
    read,
    tax_breakdown,
)

GOLDEN = Path(__file__).parent / "golden"
NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}
AGREEMENT = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement"
SETTLEMENT = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement"
LINE = "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem"
SELLER_IDS = f"{AGREEMENT}/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID"
BUYER_IDS = f"{AGREEMENT}/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID"


def _root(invoice: Invoice) -> ET.Element:
    return ET.fromstring(build_cii(invoice))


def _texts(root: ET.Element, path: str) -> list[str]:
    return [node.text or "" for node in root.findall(path, NS)]


def _one(root: ET.Element, path: str) -> str:
    (value,) = _texts(root, path)
    return value


def _ids(root: ET.Element, path: str) -> dict[str, str]:
    return {node.get("schemeID", ""): node.text or "" for node in root.findall(path, NS)}


def _tax(root: ET.Element) -> list[dict[str, str]]:
    return [
        {child.tag.split("}")[1]: child.text or "" for child in tax}
        for tax in root.findall(f"{SETTLEMENT}/ram:ApplicableTradeTax", NS)
    ]


CATEGORIES = s.per_category()


def test_standard_rated_invoice() -> None:
    root = _root(CATEGORIES["S"])
    assert _one(root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == (
        "urn:cen.eu:en16931:2017"
    )
    assert _one(root, "rsm:ExchangedDocument/ram:ID") == "RE0001"
    assert _one(root, "rsm:ExchangedDocument/ram:TypeCode") == "380"
    assert _one(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString") == "20261001"
    assert _one(root, f"{AGREEMENT}/ram:BuyerReference") == "PO-2026-0815"
    assert _one(root, f"{AGREEMENT}/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID") == "ORDER-1"
    seller = f"{AGREEMENT}/ram:SellerTradeParty"
    assert _one(root, f"{seller}/ram:Name") == "Example Software GmbH"
    assert _one(root, f"{seller}/ram:PostalTradeAddress/ram:CountryID") == "DE"
    assert _one(root, f"{seller}/ram:SpecifiedLegalOrganization/ram:ID") == "Amtsgericht Musterstadt, HRB 12345"
    assert _one(root, f"{seller}/ram:URIUniversalCommunication/ram:URIID") == "billing@example.org"
    assert _ids(root, SELLER_IDS) == {"FC": "12/345/67890", "VA": "DE123456789"}
    assert _one(root, f"{AGREEMENT}/ram:BuyerTradeParty/ram:ID") == "K-1001"
    assert _one(root, f"{AGREEMENT}/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:LineTwo") == "Haus B"
    assert _ids(root, BUYER_IDS) == {}
    assert [entry["BasisAmount"] for entry in _tax(root)] == ["4186.50"]
    assert [entry["CalculatedAmount"] for entry in _tax(root)] == ["795.44"]
    totals = f"{SETTLEMENT}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"
    assert _one(root, f"{totals}/ram:LineTotalAmount") == "4186.50"
    assert _one(root, f"{totals}/ram:TaxBasisTotalAmount") == "4186.50"
    assert _one(root, f"{totals}/ram:TaxTotalAmount") == "795.44"
    assert root.find(f"{totals}/ram:TaxTotalAmount", NS).get("currencyID") == "EUR"  # type: ignore[union-attr]
    assert _one(root, f"{totals}/ram:GrandTotalAmount") == "4981.94"
    assert _one(root, f"{totals}/ram:DuePayableAmount") == "4981.94"
    assert _one(root, f"{SETTLEMENT}/ram:InvoiceCurrencyCode") == "EUR"
    assert _one(root, f"{SETTLEMENT}/ram:PaymentReference") == "RE0001"
    means = f"{SETTLEMENT}/ram:SpecifiedTradeSettlementPaymentMeans"
    assert _one(root, f"{means}/ram:TypeCode") == "58"
    assert _one(root, f"{means}/ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == s.IBAN
    assert _one(root, f"{means}/ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID") == "COBADEFFXXX"
    terms = f"{SETTLEMENT}/ram:SpecifiedTradePaymentTerms"
    assert _one(root, f"{terms}/ram:DueDateDateTime/udt:DateTimeString") == "20261015"
    period = f"{SETTLEMENT}/ram:BillingSpecifiedPeriod"
    assert _one(root, f"{period}/ram:StartDateTime/udt:DateTimeString") == "20260901"
    assert _one(root, f"{period}/ram:EndDateTime/udt:DateTimeString") == "20260930"
    delivery = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeDelivery/ram:ActualDeliverySupplyChainEvent"
    assert _one(root, f"{delivery}/ram:OccurrenceDateTime/udt:DateTimeString") == "20260930"
    assert _texts(root, f"{LINE}/ram:SpecifiedTradeProduct/ram:Description") == ["Hosting\nSeptember"]
    quantities = root.findall(f"{LINE}/ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS)
    assert [(node.text, node.get("unitCode")) for node in quantities] == [("42.5", "HUR"), ("1", "MON")]
    notes = root.findall("rsm:ExchangedDocument/ram:IncludedNote", NS)
    assert [(n.findtext("ram:Content", None, NS), n.findtext("ram:SubjectCode", None, NS)) for n in notes] == [
        ("Vielen Dank für Ihren Auftrag.", None),
        ("Example Software GmbH, HRB 12345", "REG"),
    ]


def test_reverse_charge_names_both_vat_ids_and_the_reason() -> None:
    root = _root(CATEGORIES["AE"])
    assert _ids(root, SELLER_IDS)["VA"] == "DE123456789"
    assert _ids(root, BUYER_IDS) == {"VA": "ATU12345678"}
    assert _tax(root) == [
        {
            "CalculatedAmount": "0.00",
            "TypeCode": "VAT",
            "ExemptionReason": "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge).",
            "BasisAmount": "1760.00",
            "CategoryCode": "AE",
            "ExemptionReasonCode": "VATEX-EU-AE",
            "RateApplicablePercent": "0",
        }
    ]
    line_tax = root.find(f"{LINE}/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax", NS)
    assert line_tax is not None
    assert [(child.tag.split("}")[1], child.text) for child in line_tax] == [
        ("TypeCode", "VAT"),
        ("CategoryCode", "AE"),
        ("RateApplicablePercent", "0"),
    ]


def test_not_subject_to_vat_states_no_rate_and_no_vat_id() -> None:
    root = _root(CATEGORIES["O"])
    assert _ids(root, SELLER_IDS) == {"FC": "12/345/67890"}
    assert _ids(root, BUYER_IDS) == {}
    assert _tax(root)[0]["ExemptionReasonCode"] == "VATEX-EU-O"
    assert "RateApplicablePercent" not in _tax(root)[0]
    line_tax = root.find(f"{LINE}/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax", NS)
    assert line_tax is not None and [child.tag.split("}")[1] for child in line_tax] == ["TypeCode", "CategoryCode"]


def test_intra_community_supply_names_the_country_delivered_to() -> None:
    root = _root(CATEGORIES["K"])
    delivery = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeDelivery"
    assert _one(root, f"{delivery}/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountryID") == "AT"
    assert _tax(root)[0]["ExemptionReasonCode"] == "VATEX-EU-IC"


def test_rates_discounts_and_negative_lines() -> None:
    root = _root(CATEGORIES["S-mixed-rates-discount-negative"])
    assert [(tax["RateApplicablePercent"], tax["BasisAmount"], tax["CalculatedAmount"]) for tax in _tax(root)] == [
        ("7", "2.97", "0.21"),
        ("19", "109.99", "20.90"),
    ]
    lines = root.findall(LINE, NS)
    agreement = "ram:SpecifiedLineTradeAgreement"
    gross = f"{agreement}/ram:GrossPriceProductTradePrice"
    assert lines[0].findtext(f"{gross}/ram:ChargeAmount", None, NS) == "9.9992"
    allowance = f"{gross}/ram:AppliedTradeAllowanceCharge"
    assert lines[0].findtext(f"{allowance}/ram:ChargeIndicator/udt:Indicator", None, NS) == "false"
    assert lines[0].findtext(f"{allowance}/ram:ActualAmount", None, NS) == "0.99992"
    assert lines[0].findtext(f"{agreement}/ram:NetPriceProductTradePrice/ram:ChargeAmount", None, NS) == "8.99928"
    assert lines[1].find(gross, NS) is None
    # EN 16931 knows no negative price: the quantity carries the sign.
    assert lines[2].findtext(f"{agreement}/ram:NetPriceProductTradePrice/ram:ChargeAmount", None, NS) == "25"
    assert lines[2].findtext("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", None, NS) == "-1"


def test_credit_note_refers_to_its_invoice() -> None:
    root = _root(CATEGORIES["credit-note"])
    assert _one(root, "rsm:ExchangedDocument/ram:TypeCode") == "381"
    reference = f"{SETTLEMENT}/ram:InvoiceReferencedDocument"
    assert _one(root, f"{reference}/ram:IssuerAssignedID") == "RE0001"
    assert _one(root, f"{reference}/ram:FormattedIssueDateTime/qdt:DateTimeString") == "20261001"
    assert root.find(f"{SETTLEMENT}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime", NS) is None


def test_text_is_escaped() -> None:
    invoice = s.invoice(s.line(name='A & B <"x">'), number="R&1", currency="EUR")
    assert _one(_root(invoice), "rsm:ExchangedDocument/ram:ID") == "R&1"
    assert _one(_root(invoice), f"{LINE}/ram:SpecifiedTradeProduct/ram:Name") == 'A & B <"x">'


@pytest.mark.parametrize("name", sorted(CATEGORIES))
def test_samples_have_no_problems(name: str) -> None:
    assert problems(CATEGORIES[name]) == []


@pytest.mark.parametrize("name", sorted(CATEGORIES))
def test_golden_files(name: str) -> None:
    assert build_cii(CATEGORIES[name]) == (GOLDEN / f"{name}.xml").read_bytes()


def test_output_does_not_depend_on_the_decimal_context() -> None:
    expected = build_cii(CATEGORIES["S-mixed-rates-discount-negative"])
    with decimal.localcontext() as context:
        context.prec = 3
        context.rounding = decimal.ROUND_DOWN
        assert build_cii(CATEGORIES["S-mixed-rates-discount-negative"]) == expected


def test_building_leaves_the_xml_namespace_registry_alone() -> None:
    before = dict(ET._namespace_map)  # type: ignore[attr-defined]
    build_cii(CATEGORIES["S"])
    assert ET._namespace_map == before  # type: ignore[attr-defined]


def test_tax_breakdown_rounds_half_up_on_the_sum_per_category_and_rate() -> None:
    lines = (
        s.line("0.25", id="1"),
        s.line("0.25", id="2"),
        s.line("10.00", rate="7.0", id="3"),
        s.line("1.00", VatCategory.ZERO_RATED, "0", id="4"),
    )
    assert tax_breakdown(lines) == (
        TaxBreakdown(VatCategory.ZERO_RATED, Decimal(0), Decimal("1.00"), Decimal("0.00")),
        TaxBreakdown(VatCategory.STANDARD, Decimal(7), Decimal("10.00"), Decimal("0.70")),
        TaxBreakdown(VatCategory.STANDARD, Decimal(19), Decimal("0.50"), Decimal("0.10")),
    )


def _one_problem(invoice: Invoice, rule: str) -> None:
    found = problems(invoice)
    assert any(rule in text for text in found), found
    with pytest.raises(InvalidInvoiceError) as error:
        build_cii(invoice)
    assert error.value.problems == tuple(found)


_REVERSE = CATEGORIES["AE"]
_NOT_SUBJECT = CATEGORIES["O"]
_INTRA = CATEGORIES["K"]


@pytest.mark.parametrize(
    ("invoice", "rule"),
    [
        (replace(s.invoice(), number=""), "BR-2"),
        (replace(s.invoice(), currency="euro"), "BR-5"),
        (replace(s.invoice(), seller=replace(s.SELLER, name="")), "BR-6"),
        (replace(s.invoice(), buyer=replace(s.BUYER, name="")), "BR-7"),
        (replace(s.invoice(), seller=replace(s.SELLER, country="")), "BR-9"),
        (replace(s.invoice(), buyer=replace(s.BUYER, country="Deutschland")), "BR-11"),
        (replace(s.invoice(), lines=()), "BR-16"),
        (s.invoice(s.line(id="1"), s.line(id="1")), "BR-21"),
        (s.invoice(s.line(name=" ")), "BR-25"),
        (s.invoice(s.line(unit_code="")), "BR-23"),
        (s.invoice(period_start=date(2026, 9, 2), period_end=date(2026, 9, 1)), "BR-29"),
        (s.invoice(due_date=None, payment_terms=None), "BR-CO-25"),
        (s.invoice(payment_means=(s.PaymentMeans("58"),)), "BR-61"),
        (s.invoice(seller=replace(s.SELLER, vat_id=None, legal_registration=None)), "BR-CO-26"),
        (s.invoice(seller=replace(s.SELLER, vat_id=None, tax_number=None)), "BR-S-02"),
        (s.invoice(s.line(rate="0")), "BR-S-05"),
        (s.invoice(s.line(rate=None)), "BR-S-05"),
        (replace(_REVERSE, buyer=s.BUYER), "BR-AE-02"),
        (replace(_REVERSE, seller=replace(s.SELLER, vat_id=None)), "BR-AE-02"),
        (s.invoice(s.line("1", VatCategory.REVERSE_CHARGE, "19"), buyer=s.FOREIGN_BUYER), "BR-AE-05"),
        (replace(_NOT_SUBJECT, seller=s.SELLER), "BR-O-02"),
        (replace(_NOT_SUBJECT, buyer=s.FOREIGN_BUYER), "BR-O-02"),
        (s.invoice(s.line("1", VatCategory.NOT_SUBJECT, "0"), seller=replace(s.SELLER, vat_id=None)), "BR-O-05"),
        (s.invoice(s.line("1", VatCategory.ZERO_RATED, "19")), "BR-Z-05"),
        (s.invoice(s.line("1", VatCategory.EXEMPT, "19")), "BR-E-05"),
        (s.invoice(s.line("1", VatCategory.EXPORT, "0"), seller=replace(s.SELLER, vat_id=None)), "BR-G-02"),
        (replace(_INTRA, deliver_to_country=None), "BR-IC-12"),
        (replace(_INTRA, delivery_date=None), "BR-IC-11"),
        (replace(_INTRA, buyer=s.BUYER), "BR-IC-02"),
        (replace(s.invoice(), tax_breakdown=()), "BR-CO-18"),
        (replace(s.invoice(), seller=replace(s.SELLER, electronic_address_scheme=None)), "BR-62"),
    ],
)
def test_a_rule_broken_is_named_and_refused(invoice: Invoice, rule: str) -> None:
    _one_problem(invoice, rule)


def _with_tax(**fields: object) -> Invoice:
    invoice = s.invoice()
    return replace(invoice, tax_breakdown=(replace(invoice.tax_breakdown[0], **fields),))  # type: ignore[arg-type]


def test_amounts_below_a_cent_are_refused() -> None:
    lines = [s.line("1.004", id=str(index + 1)) for index in range(3)]
    invoice = s.invoice(*lines)
    found = problems(invoice)
    assert sum("BR-DEC-23" in text for text in found) == 3
    assert any("BR-DEC-19" in text for text in found)
    with pytest.raises(InvalidInvoiceError):
        build_cii(invoice)
    _one_problem(_with_tax(tax_amount=Decimal("19.004")), "BR-DEC-20")


def test_the_value_of_an_amount_counts_not_its_exponent() -> None:
    assert problems(s.invoice(s.line("100.0000"))) == []
    assert problems(s.invoice(s.line("1E+2"))) == []
    assert b"<ram:LineTotalAmount>100.00<" in build_cii(s.invoice(s.line("100.0000")))


def test_the_cents_of_an_amount_do_not_depend_on_the_context_of_the_caller() -> None:
    with decimal.localcontext(prec=3):
        assert problems(s.invoice(s.line("123456.78"))) == []


def test_a_wrong_breakdown_is_refused() -> None:
    _one_problem(_with_tax(tax_amount=Decimal("18.00")), "BR-CO-17")
    _one_problem(_with_tax(basis_amount=Decimal("101.00")), "do not add up")
    _one_problem(_with_tax(exemption_reason="no reason"), "takes no exemption reason")
    invoice = s.invoice(s.line("1", VatCategory.EXEMPT, "0"))
    entry = replace(invoice.tax_breakdown[0], exemption_reason=None)
    _one_problem(replace(invoice, tax_breakdown=(entry,)), "needs an")
    extra = TaxBreakdown(VatCategory.ZERO_RATED, Decimal(0), Decimal(0), Decimal(0))
    _one_problem(replace(s.invoice(), tax_breakdown=(*s.invoice().tax_breakdown, extra)), "which no line has")


@pytest.mark.parametrize(
    "other",
    [
        s.line(),
        s.line(category=VatCategory.ZERO_RATED, rate="0"),
        s.line(category=VatCategory.EXEMPT, rate="0"),
    ],
    ids=["S", "Z", "E"],
)
def test_category_o_stands_alone(other: Line) -> None:
    seller = replace(s.SELLER, vat_id=None)
    not_subject = s.line(category=VatCategory.NOT_SUBJECT, rate=None, id="1")
    invoice = s.invoice(not_subject, replace(other, id="2"), seller=seller)
    found = problems(invoice)
    assert any("BR-O-11" in text for text in found)
    assert any("BR-O-12" in text for text in found)
    with pytest.raises(InvalidInvoiceError):
        build_cii(invoice)


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        (s.line(quantity=1.5), "not a Decimal"),
        (s.line(unit_price=Decimal("NaN")), "not a finite number"),
        (s.line(quantity=Decimal("1E+30")), "out of range"),
        (s.line(quantity=Decimal("1E-30")), "decimal places"),
        (s.line(name="a\x01b"), "character XML cannot carry"),
        (s.line(discount_percent=Decimal(101)), "discount"),
    ],
)
def test_values_that_are_no_values_are_refused(line, problem: str) -> None:  # type: ignore[no-untyped-def]
    invoice = replace(s.invoice(), lines=(line,))
    assert any(problem in text for text in problems(invoice))


_money = st.decimals(min_value=Decimal("-99999"), max_value=Decimal("99999"), places=2, allow_nan=False)
_text = st.text(st.characters(exclude_categories=("Cs", "Cc")), min_size=1, max_size=20).filter(str.strip)


@given(amounts=st.lists(_money, min_size=1, max_size=5), rate=st.sampled_from(["7", "19", "20.5"]), number=_text)
def test_what_is_built_reads_back_with_the_same_amounts(amounts: list[Decimal], rate: str, number: str) -> None:
    lines = [s.line(str(amount), rate=rate, id=str(index + 1)) for index, amount in enumerate(amounts)]
    invoice = s.invoice(*lines, number=number.strip())
    assert problems(invoice) == []
    reading = read(build_cii(invoice))
    assert reading.invoice is not None and reading.invoice.format is DataFormat.XRECHNUNG_CII
    assert reading.invoice.number == number.strip()
    assert reading.invoice.net_amount == sum(amounts, Decimal(0))
    assert reading.invoice.tax_amount == invoice.tax_breakdown[0].tax_amount
