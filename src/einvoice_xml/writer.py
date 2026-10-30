"""The e-invoice XML: UN/CEFACT CII, profile EN 16931 (Factur-X / ZUGFeRD 2.x). Pure, no I/O.

:func:`build_cii` writes what the :class:`~einvoice_xml.model.Invoice` states, byte for
byte the same for the same input. :func:`problems` says what keeps an invoice from being
valid; it covers the BR-* rules that depend on the data given here, not every rule of the
standard — the schematron of a validator stays the last word.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from xml.sax.saxutils import escape

from einvoice_xml._numbers import context, round_money
from einvoice_xml.errors import InvalidInvoiceError
from einvoice_xml.model import Invoice, Line, Party, TaxBreakdown, VatCategory

#: BT-24: the profile EN 16931 (called COMFORT in ZUGFeRD 2.0).
GUIDELINE = "urn:cen.eu:en16931:2017"

_NAMESPACES = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}
#: The CEF VATEX code :func:`tax_breakdown` states for a category with a reason.
_VATEX = {
    VatCategory.REVERSE_CHARGE: "VATEX-EU-AE",
    VatCategory.NOT_SUBJECT: "VATEX-EU-O",
    VatCategory.INTRA_COMMUNITY: "VATEX-EU-IC",
    VatCategory.EXPORT: "VATEX-EU-G",
}
#: Categories that need an exemption reason (BR-AE-10, BR-O-10, BR-E-10, BR-IC-10, BR-G-10).
_WITH_REASON = frozenset(_VATEX) | {VatCategory.EXEMPT}
#: UNTDID 4461 codes that are a credit transfer: the account is mandatory (BR-61).
_CREDIT_TRANSFER_CODES = frozenset({"30", "58"})
#: What XML 1.0 cannot carry, not even escaped.
NOT_XML = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
_CODE = re.compile(r"[0-9A-Za-z-]{1,16}")
_CURRENCY = re.compile(r"[A-Z]{3}")
_COUNTRY = re.compile(r"[A-Z]{2}")
#: Amounts beyond these are no amounts; refusing them keeps the arithmetic and the output bounded.
_MAX_MAGNITUDE = Decimal(10) ** 24
_MIN_EXPONENT = -12


def tax_breakdown(
    lines: Iterable[Line], *, exemption_reasons: Mapping[VatCategory, str] | None = None
) -> tuple[TaxBreakdown, ...]:
    """The VAT breakdown of ``lines``: one entry per category and rate, lowest rate first.

    Tax is computed on the summed net amounts of an entry (not per line) and rounded half
    up to cents. ``exemption_reasons`` gives the wording of BT-120 per category.
    """
    reasons = exemption_reasons or {}
    with localcontext(context()):
        basis: dict[tuple[VatCategory, Decimal | None], Decimal] = {}
        for line in lines:
            rate = None if line.rate is None else line.rate.normalize()
            basis[line.category, rate] = basis.get((line.category, rate), Decimal(0)) + line.net_amount
        return tuple(
            TaxBreakdown(
                category=category,
                rate=rate,
                basis_amount=net,
                tax_amount=round_money(net * (rate or 0) / 100),
                exemption_reason=reasons.get(category),
                exemption_reason_code=_VATEX.get(category),
            )
            for (category, rate), net in sorted(basis.items(), key=lambda item: (item[0][1] or 0, item[0][0].value))
        )


def _strings(value: object, path: str) -> Iterator[tuple[str, str]]:
    """Every string in a tree of dataclasses and tuples, with where it is."""
    if isinstance(value, str):
        yield path, value
    elif dataclasses.is_dataclass(value):
        for item in dataclasses.fields(value):
            yield from _strings(getattr(value, item.name), f"{path}.{item.name}" if path else item.name)
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def _amount_problem(value: object, what: str) -> str | None:
    if not isinstance(value, Decimal):
        return f"{what} is not a Decimal"
    if not value.is_finite():
        return f"{what} is not a finite number"
    if abs(value) >= _MAX_MAGNITUDE:
        return f"{what} is out of range"
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < _MIN_EXPONENT:
        return f"{what} has more than {-_MIN_EXPONENT} decimal places"
    return None


def _money(invoice: Invoice) -> Iterator[tuple[Decimal, str, str]]:
    """The amounts EN 16931 states in whole cents, with the rule that says so."""
    for index, line in enumerate(invoice.lines):
        yield line.net_amount, f"lines[{index}].net_amount", "BR-DEC-23"
    for index, entry in enumerate(invoice.tax_breakdown):
        yield entry.basis_amount, f"tax_breakdown[{index}].basis_amount", "BR-DEC-19"
        yield entry.tax_amount, f"tax_breakdown[{index}].tax_amount", "BR-DEC-20"


def _amounts(invoice: Invoice) -> Iterator[tuple[object, str]]:
    for value, what, _ in _money(invoice):
        yield value, what
    for index, line in enumerate(invoice.lines):
        yield line.quantity, f"lines[{index}].quantity"
        yield line.unit_price, f"lines[{index}].unit_price"
        yield line.discount_percent, f"lines[{index}].discount_percent"
        if line.rate is not None:
            yield line.rate, f"lines[{index}].rate"
    for index, entry in enumerate(invoice.tax_breakdown):
        if entry.rate is not None:
            yield entry.rate, f"tax_breakdown[{index}].rate"


def _form_problems(invoice: Invoice) -> list[str]:
    """What is wrong with the values as such; the rules below may rely on their absence."""
    found = [
        f"{path} contains a character XML cannot carry" for path, text in _strings(invoice, "") if NOT_XML.search(text)
    ]
    found += [problem for value, what in _amounts(invoice) if (problem := _amount_problem(value, what))]
    if found:
        return found
    # The value counts, not its exponent: 1.0000 is a whole number of cents.
    with localcontext(context()):
        return [
            f"{rule}: {what} is not a whole number of cents"
            for value, what, rule in _money(invoice)
            if value != round_money(value)
        ]


def _identification_problems(invoice: Invoice, categories: set[VatCategory]) -> list[str]:
    seller, buyer = invoice.seller, invoice.buyer
    found: list[str] = []
    if not seller.name:
        found.append("BR-6: the seller has no name")
    if not buyer.name:
        found.append("BR-7: the buyer has no name")
    if not _COUNTRY.fullmatch(seller.country or ""):
        found.append("BR-9: the seller has no ISO 3166-1 country")
    if not _COUNTRY.fullmatch(buyer.country or ""):
        found.append("BR-11: the buyer has no ISO 3166-1 country")
    if not (seller.identifier or seller.legal_registration or seller.vat_id):
        found.append("BR-CO-26: the seller has neither an identifier, a legal registration nor a VAT id")
    taxed = categories & {VatCategory.STANDARD, VatCategory.ZERO_RATED, VatCategory.EXEMPT}
    for category in sorted(taxed):
        if not (seller.vat_id or seller.tax_number):
            found.append(f"BR-{category}-02: the seller has neither a VAT id nor a tax number")
    for category, rule in ((VatCategory.REVERSE_CHARGE, "AE"), (VatCategory.INTRA_COMMUNITY, "IC")):
        if category in categories:
            if not seller.vat_id:
                found.append(f"BR-{rule}-02: the seller has no VAT id")
            if not buyer.vat_id:
                found.append(f"BR-{rule}-02: the buyer has no VAT id")
    if VatCategory.EXPORT in categories and not seller.vat_id:
        found.append("BR-G-02: the seller has no VAT id")
    if VatCategory.NOT_SUBJECT in categories and (seller.vat_id or buyer.vat_id):
        found.append("BR-O-02: an invoice not subject to VAT names no VAT id of either party")
    return found


def _not_subject_problems(invoice: Invoice, categories: set[VatCategory]) -> list[str]:
    found: list[str] = []
    stated = {entry.category for entry in invoice.tax_breakdown}
    if VatCategory.NOT_SUBJECT in stated and len(stated) > 1:
        found.append("BR-O-11: the VAT breakdown states another category next to category O")
    if VatCategory.NOT_SUBJECT in categories and len(categories) > 1:
        found.append("BR-O-12: a line has another category next to a line of category O")
    return found


def _rate_problem(category: VatCategory, rate: Decimal | None, what: str) -> str | None:
    if category is VatCategory.NOT_SUBJECT:
        return None if rate is None else f"BR-O-05: {what} states a rate, category O has none"
    rule = "IC" if category is VatCategory.INTRA_COMMUNITY else category.value
    if rate is None:
        return f"BR-{rule}-05: {what} has no VAT rate"
    if category is VatCategory.STANDARD:
        return None if rate > 0 else f"BR-S-05: {what} needs a rate above 0"
    return None if rate == 0 else f"BR-{rule}-05: {what} needs the rate 0"


def _line_problems(invoice: Invoice) -> list[str]:
    found: list[str] = []
    if not invoice.lines:
        found.append("BR-16: the invoice has no line")
    ids = [line.id for line in invoice.lines]
    if len(set(ids)) != len(ids):
        found.append("BR-21: the line ids are not unique")
    for index, line in enumerate(invoice.lines):
        what = f"line {index + 1}"
        if not line.id:
            found.append(f"BR-21: {what} has no id")
        if not line.name.strip():
            found.append(f"BR-25: {what} has no name")
        if not _CODE.fullmatch(line.unit_code):
            found.append(f"BR-23: {what} has no unit code")
        if not 0 <= line.discount_percent <= 100:
            found.append(f"{what} has a discount outside 0 to 100 %")
        problem = _rate_problem(line.category, line.rate, what)
        if problem:
            found.append(problem)
    return found


def _breakdown_problems(invoice: Invoice) -> list[str]:
    found: list[str] = []
    stated: dict[tuple[VatCategory, Decimal | None], TaxBreakdown] = {}
    for entry in invoice.tax_breakdown:
        key = (entry.category, entry.rate)
        if key in stated:
            found.append(f"the VAT breakdown states category {entry.category} at rate {entry.rate} twice")
        stated[key] = entry
        reason = entry.exemption_reason or entry.exemption_reason_code
        if entry.category in _WITH_REASON and not reason:
            found.append(f"the VAT breakdown of category {entry.category} needs an exemption reason")
        if entry.category not in _WITH_REASON and reason:
            found.append(f"the VAT breakdown of category {entry.category} takes no exemption reason")
        expected = round_money(entry.basis_amount * (entry.rate or 0) / 100)
        if abs(entry.tax_amount - expected) > Decimal("0.01"):
            found.append(f"BR-CO-17: the VAT of category {entry.category} at rate {entry.rate} should be {expected}")
    basis: dict[tuple[VatCategory, Decimal | None], Decimal] = {}
    for line in invoice.lines:
        basis[line.category, line.rate] = basis.get((line.category, line.rate), Decimal(0)) + line.net_amount
    for (category, rate), net in basis.items():
        entry_or_none = stated.get((category, rate))
        if entry_or_none is None:
            found.append(f"BR-CO-18: the VAT breakdown lacks category {category} at rate {rate}")
        elif round_money(net) != round_money(entry_or_none.basis_amount):
            found.append(f"the lines of category {category} at rate {rate} do not add up to the VAT breakdown")
    found += [
        f"the VAT breakdown states category {category} at rate {rate}, which no line has"
        for category, rate in stated
        if (category, rate) not in basis
    ]
    return found


def _header_problems(invoice: Invoice, categories: set[VatCategory]) -> list[str]:
    found: list[str] = []
    if not invoice.number:
        found.append("BR-2: the invoice has no number")
    if not _CURRENCY.fullmatch(invoice.currency or ""):
        found.append("BR-5: the currency is no ISO 4217 code")
    if invoice.period_start and invoice.period_end and invoice.period_end < invoice.period_start:
        found.append("BR-29: the period ends before it starts")
    if VatCategory.INTRA_COMMUNITY in categories:
        if not (invoice.delivery_date or invoice.period_start or invoice.period_end):
            found.append("BR-IC-11: an intra-community supply needs a delivery date or a period")
        if not invoice.deliver_to_country:
            found.append("BR-IC-12: an intra-community supply needs the country delivered to")
    if invoice.deliver_to_country and not _COUNTRY.fullmatch(invoice.deliver_to_country):
        found.append("the country delivered to is no ISO 3166-1 code")
    due = sum((entry.basis_amount + entry.tax_amount for entry in invoice.tax_breakdown), Decimal(0))
    if due > 0 and not invoice.payment_terms and invoice.due_date is None:
        found.append("BR-CO-25: the payment terms or a due date are missing")
    for means in invoice.payment_means:
        if not _CODE.fullmatch(means.code):
            found.append("BR-49: a payment means has no type code")
        elif means.code in _CREDIT_TRANSFER_CODES and not means.iban:
            found.append(f"BR-61: the payment means {means.code} needs an account")
    for party in (invoice.seller, invoice.buyer):
        if bool(party.electronic_address) != bool(party.electronic_address_scheme):
            found.append("BR-62: an electronic address needs its scheme, and the scheme an address")
        if party.electronic_address_scheme and not _CODE.fullmatch(party.electronic_address_scheme):
            found.append("BR-62: the scheme of the electronic address is no code")
    return found


def problems(invoice: Invoice) -> list[str]:
    """What keeps ``invoice`` from being a valid EN 16931 invoice (empty: nothing found)."""
    found = _form_problems(invoice)
    if found:
        return found
    categories = {line.category for line in invoice.lines}
    with localcontext(context()):
        return [
            *_header_problems(invoice, categories),
            *_identification_problems(invoice, categories),
            *_not_subject_problems(invoice, categories),
            *_line_problems(invoice),
            *_breakdown_problems(invoice),
        ]


@dataclass(slots=True)
class _Element:
    """An element of the document. The serialisation is written here, not left to
    ``xml.etree``, whose prefixes are global state of the interpreter."""

    tag: str
    text: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    children: list[_Element] = field(default_factory=list)

    def sub(self, tag: str, text: str | None = None, **attributes: str) -> _Element:
        child = _Element(tag, text, attributes)
        self.children.append(child)
        return child

    def write(self, out: list[str], depth: int) -> None:
        indent = "  " * depth
        attributes = "".join(f' {name}="{_escape_attribute(value)}"' for name, value in self.attributes.items())
        if self.children:
            out.append(f"{indent}<{self.tag}{attributes}>\n")
            for child in self.children:
                child.write(out, depth + 1)
            out.append(f"{indent}</{self.tag}>\n")
        elif self.text is None:
            out.append(f"{indent}<{self.tag}{attributes} />\n")
        else:
            out.append(f"{indent}<{self.tag}{attributes}>{escape(self.text, {chr(13): '&#13;'})}</{self.tag}>\n")


def _escape_attribute(value: str) -> str:
    return escape(value, {'"': "&quot;", "\t": "&#9;", "\n": "&#10;", "\r": "&#13;"})


def _amount(value: Decimal) -> str:
    rounded = round_money(value)
    return f"{abs(rounded) if rounded == 0 else rounded:.2f}"


def _number(value: Decimal) -> str:
    """A quantity, unit price or percentage: plain notation without trailing zeros."""
    text = format(value, "f")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if text in ("", "-", "-0") else text


def _day(value: date) -> str:
    return f"{value.year:04d}{value.month:02d}{value.day:02d}"


def _date(parent: _Element, tag: str, value: date, *, qualified: bool = False) -> None:
    parent.sub(tag).sub("qdt:DateTimeString" if qualified else "udt:DateTimeString", _day(value), format="102")


def _party(parent: _Element, tag: str, party: Party, *, with_tax_number: bool) -> None:
    element = parent.sub(tag)
    if party.identifier:
        element.sub("ram:ID", party.identifier)
    element.sub("ram:Name", party.name)
    if party.legal_registration:
        element.sub("ram:SpecifiedLegalOrganization").sub("ram:ID", party.legal_registration)
    address = element.sub("ram:PostalTradeAddress")
    for name, value in (
        ("ram:PostcodeCode", party.postal_code),
        ("ram:LineOne", party.street),
        ("ram:LineTwo", party.supplement),
        ("ram:CityName", party.city),
    ):
        if value:
            address.sub(name, value)
    address.sub("ram:CountryID", party.country)
    if party.electronic_address and party.electronic_address_scheme:
        element.sub("ram:URIUniversalCommunication").sub(
            "ram:URIID", party.electronic_address, schemeID=party.electronic_address_scheme
        )
    if with_tax_number and party.tax_number:
        element.sub("ram:SpecifiedTaxRegistration").sub("ram:ID", party.tax_number, schemeID="FC")
    if party.vat_id:
        element.sub("ram:SpecifiedTaxRegistration").sub("ram:ID", party.vat_id, schemeID="VA")


def _line(transaction: _Element, line: Line) -> None:
    # EN 16931 knows no negative price (BR-27): the sign of the line is the quantity's.
    quantity, price = (-line.quantity, -line.unit_price) if line.unit_price < 0 else (line.quantity, line.unit_price)
    net_price = price * (100 - line.discount_percent) / 100 if line.discount_percent else price

    item = transaction.sub("ram:IncludedSupplyChainTradeLineItem")
    item.sub("ram:AssociatedDocumentLineDocument").sub("ram:LineID", line.id)
    product = item.sub("ram:SpecifiedTradeProduct")
    product.sub("ram:Name", line.name)
    if line.description:
        product.sub("ram:Description", line.description)
    agreement = item.sub("ram:SpecifiedLineTradeAgreement")
    if net_price != price:
        gross = agreement.sub("ram:GrossPriceProductTradePrice")
        gross.sub("ram:ChargeAmount", _number(price))
        allowance = gross.sub("ram:AppliedTradeAllowanceCharge")
        allowance.sub("ram:ChargeIndicator").sub("udt:Indicator", "false")
        allowance.sub("ram:ActualAmount", _number(price - net_price))
    agreement.sub("ram:NetPriceProductTradePrice").sub("ram:ChargeAmount", _number(net_price))
    item.sub("ram:SpecifiedLineTradeDelivery").sub("ram:BilledQuantity", _number(quantity), unitCode=line.unit_code)
    settlement = item.sub("ram:SpecifiedLineTradeSettlement")
    tax = settlement.sub("ram:ApplicableTradeTax")
    tax.sub("ram:TypeCode", "VAT")
    tax.sub("ram:CategoryCode", line.category.value)
    if line.rate is not None:
        tax.sub("ram:RateApplicablePercent", _number(line.rate))
    settlement.sub("ram:SpecifiedTradeSettlementLineMonetarySummation").sub(
        "ram:LineTotalAmount", _amount(line.net_amount)
    )


def _settlement(transaction: _Element, invoice: Invoice) -> None:
    settlement = transaction.sub("ram:ApplicableHeaderTradeSettlement")
    if invoice.payment_reference:
        settlement.sub("ram:PaymentReference", invoice.payment_reference)
    settlement.sub("ram:InvoiceCurrencyCode", invoice.currency)
    for payment in invoice.payment_means:
        means = settlement.sub("ram:SpecifiedTradeSettlementPaymentMeans")
        means.sub("ram:TypeCode", payment.code)
        if payment.iban:
            account = means.sub("ram:PayeePartyCreditorFinancialAccount")
            account.sub("ram:IBANID", payment.iban)
            if payment.account_name:
                account.sub("ram:AccountName", payment.account_name)
        if payment.bic:
            means.sub("ram:PayeeSpecifiedCreditorFinancialInstitution").sub("ram:BICID", payment.bic)
    for entry in invoice.tax_breakdown:
        tax = settlement.sub("ram:ApplicableTradeTax")
        tax.sub("ram:CalculatedAmount", _amount(entry.tax_amount))
        tax.sub("ram:TypeCode", "VAT")
        if entry.exemption_reason:
            tax.sub("ram:ExemptionReason", entry.exemption_reason)
        tax.sub("ram:BasisAmount", _amount(entry.basis_amount))
        tax.sub("ram:CategoryCode", entry.category.value)
        if entry.exemption_reason_code:
            tax.sub("ram:ExemptionReasonCode", entry.exemption_reason_code)
        if entry.rate is not None:
            tax.sub("ram:RateApplicablePercent", _number(entry.rate))
    if invoice.period_start is not None or invoice.period_end is not None:
        period = settlement.sub("ram:BillingSpecifiedPeriod")
        if invoice.period_start is not None:
            _date(period, "ram:StartDateTime", invoice.period_start)
        if invoice.period_end is not None:
            _date(period, "ram:EndDateTime", invoice.period_end)
    if invoice.payment_terms or invoice.due_date is not None:
        terms = settlement.sub("ram:SpecifiedTradePaymentTerms")
        if invoice.payment_terms:
            terms.sub("ram:Description", invoice.payment_terms)
        if invoice.due_date is not None:
            _date(terms, "ram:DueDateDateTime", invoice.due_date)
    net = sum((entry.basis_amount for entry in invoice.tax_breakdown), Decimal(0))
    tax_total = sum((entry.tax_amount for entry in invoice.tax_breakdown), Decimal(0))
    totals = settlement.sub("ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    totals.sub("ram:LineTotalAmount", _amount(net))
    totals.sub("ram:TaxBasisTotalAmount", _amount(net))
    totals.sub("ram:TaxTotalAmount", _amount(tax_total), currencyID=invoice.currency)
    totals.sub("ram:GrandTotalAmount", _amount(net + tax_total))
    totals.sub("ram:DuePayableAmount", _amount(net + tax_total))
    if invoice.preceding_invoice is not None:
        reference = settlement.sub("ram:InvoiceReferencedDocument")
        reference.sub("ram:IssuerAssignedID", invoice.preceding_invoice.number)
        if invoice.preceding_invoice.issue_date is not None:
            _date(reference, "ram:FormattedIssueDateTime", invoice.preceding_invoice.issue_date, qualified=True)


def _document(invoice: Invoice) -> _Element:
    root = _Element("rsm:CrossIndustryInvoice")
    root.attributes.update({f"xmlns:{prefix}": uri for prefix, uri in _NAMESPACES.items()})
    context_parameter = root.sub("rsm:ExchangedDocumentContext").sub("ram:GuidelineSpecifiedDocumentContextParameter")
    context_parameter.sub("ram:ID", GUIDELINE)

    header = root.sub("rsm:ExchangedDocument")
    header.sub("ram:ID", invoice.number)
    header.sub("ram:TypeCode", invoice.kind.value)
    _date(header, "ram:IssueDateTime", invoice.issue_date)
    for item in invoice.notes:
        note = header.sub("ram:IncludedNote")
        note.sub("ram:Content", item.content)
        if item.subject_code is not None:
            note.sub("ram:SubjectCode", item.subject_code)

    transaction = root.sub("rsm:SupplyChainTradeTransaction")
    for line in invoice.lines:
        _line(transaction, line)

    agreement = transaction.sub("ram:ApplicableHeaderTradeAgreement")
    if invoice.buyer_reference:
        agreement.sub("ram:BuyerReference", invoice.buyer_reference)
    _party(agreement, "ram:SellerTradeParty", invoice.seller, with_tax_number=True)
    _party(agreement, "ram:BuyerTradeParty", invoice.buyer, with_tax_number=False)
    if invoice.order_reference:
        agreement.sub("ram:BuyerOrderReferencedDocument").sub("ram:IssuerAssignedID", invoice.order_reference)

    delivery = transaction.sub("ram:ApplicableHeaderTradeDelivery")
    if invoice.deliver_to_country:
        delivery.sub("ram:ShipToTradeParty").sub("ram:PostalTradeAddress").sub(
            "ram:CountryID", invoice.deliver_to_country
        )
    if invoice.delivery_date is not None:
        _date(delivery.sub("ram:ActualDeliverySupplyChainEvent"), "ram:OccurrenceDateTime", invoice.delivery_date)

    _settlement(transaction, invoice)
    return root


def build_cii(invoice: Invoice) -> bytes:
    """The CII XML of ``invoice`` as UTF-8 bytes.

    :class:`~einvoice_xml.errors.InvalidInvoiceError` if :func:`problems` finds anything.
    """
    found = problems(invoice)
    if found:
        raise InvalidInvoiceError(found)
    with localcontext(context()):
        out = ['<?xml version="1.0" encoding="UTF-8"?>\n']
        _document(invoice).write(out, 0)
    return "".join(out).encode("utf-8")
