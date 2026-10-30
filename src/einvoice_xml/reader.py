"""Read the structured data of an incoming e-invoice (EN 16931). Pure, no I/O.

Two carriers, three syntaxes:

* a PDF with an embedded XML file (ZUGFeRD 2.x / Factur-X; the XML is UN/CEFACT CII);
* a bare XML file — an XRechnung, in CII or in UBL (``Invoice``);
* a PDF that carries an XRechnung as the embedded file ``xrechnung.xml``; it is read like
  the bare file.

An embedded file goes by any of its names: its key in the name tree of the PDF or its file
name in the file specification.

:func:`read` returns what the XML states — header data and the document totals — or says
why there is none. It never guesses: a PDF without embedded XML, an unknown syntax, a
credit note or totals that do not add up yield no amounts, only a reason.

It also reads where the seller wants to be paid (BT-81 payment means, BT-84/85/86 the
payee's account) and the buyer's identifier at the seller (BT-46). An invalid IBAN is
dropped, several different IBANs give no account at all — each with its reason; neither
touches the amounts.

The input is hostile. It is bounded by :data:`MAX_PDF_BYTES`, :data:`MAX_XML_BYTES` and
:data:`MAX_EMBEDDED_FILES`; XML goes through ``defusedxml`` with DTDs, entities and external
references forbidden, whatever the encoding of the document; numbers and dates are checked
against their plain form before anything is computed with them.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pypdf import PdfReader
from pypdf.generic import EmbeddedFile

from einvoice_xml._iban import is_valid_iban, normalise_iban
from einvoice_xml._numbers import context
from einvoice_xml.errors import EInvoiceError, LimitExceededError, ReadError

#: The largest document :func:`read` looks at.
MAX_PDF_BYTES = 50 * 1024 * 1024
#: The largest XML file, bare or embedded.
MAX_XML_BYTES = 10 * 1024 * 1024
#: How many embedded files of a PDF are looked at; a PDF with more is refused.
MAX_EMBEDDED_FILES = 32
#: The longest number the reader accepts: 30 digits and more are no invoice amount.
_MAX_NUMBER_LENGTH = 32

CII = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_CII_NS = {
    "rsm": CII,
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
UBL_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
UBL_CREDIT_NOTE = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
_UBL_NS = {
    "inv": UBL_INVOICE,
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
#: Names of the embedded invoice XML (Factur-X, ZUGFeRD 2.x, XRechnung in a PDF), lower case.
KNOWN_ATTACHMENTS = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml")
#: The embedded file that is an XRechnung as it was sent (CII or UBL), lower case.
XRECHNUNG_ATTACHMENT = "xrechnung.xml"
#: UNTDID 1001 codes of documents that are invoices (a debt of the buyer): commercial,
#: partial, corrected and self-billed invoice. A credit note (381) is not among them.
INVOICE_TYPE_CODES = frozenset({"380", "326", "384", "389"})
#: UNTDID 4461 codes of a SEPA or non-SEPA direct debit: the seller collects the amount.
DIRECT_DEBIT_CODES = frozenset({"49", "59"})
_NUMBER = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)")
_CII_DATE = re.compile(r"[0-9]{8}")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
#: A byte order mark of UTF-16: XML, which the first bytes do not show as ``<``.
_UTF16_MARKS = (b"\xff\xfe", b"\xfe\xff")


class DataFormat(StrEnum):
    """Which carrier and syntax the data was read from."""

    #: CII embedded in a PDF (ZUGFeRD 2.x / Factur-X).
    FACTUR_X = "factur-x"
    #: A bare CII XML file (XRechnung, CII syntax).
    XRECHNUNG_CII = "xrechnung-cii"
    #: A bare UBL XML file, or one embedded as ``xrechnung.xml`` (XRechnung, UBL syntax).
    XRECHNUNG_UBL = "xrechnung-ubl"


class TaxTreatment(StrEnum):
    """How the VAT of a read invoice is to be treated (:func:`vat_split`)."""

    #: The invoice states its VAT, per rate.
    STANDARD = "standard"
    #: Reverse charge: the invoice states no VAT, the recipient owes it.
    REVERSE_CHARGE = "reverse_charge"


@dataclass(frozen=True, slots=True)
class ReadTax:
    """One entry of the VAT breakdown (BG-23): category (UNTDID 5305), rate, taxable
    amount and tax, as the XML states them."""

    category: str | None
    rate: Decimal | None
    basis: Decimal | None
    tax: Decimal | None


@dataclass(frozen=True, slots=True)
class PayeeAccount:
    """The account the seller wants to be paid to (BG-17): IBAN (BT-84, normalised),
    account name (BT-85) and BIC (BT-86), as the XML states them."""

    iban: str
    account_name: str | None
    bic: str | None


@dataclass(frozen=True, slots=True)
class ReadInvoice:
    """What the XML of an invoice states (header data, totals, payment; not its lines)."""

    format: DataFormat
    type_code: str
    number: str | None
    issue_date: date | None
    due_date: date | None
    service_period_start: date | None
    service_period_end: date | None
    currency: str | None
    net_amount: Decimal | None
    tax_amount: Decimal | None
    gross_amount: Decimal | None
    seller_name: str | None
    seller_vat_id: str | None
    buyer_vat_id: str | None
    #: The VAT breakdown per category and rate (BG-23), in document order.
    tax_breakdown: tuple[ReadTax, ...] = ()
    #: The payment means (BT-81, UNTDID 4461): a direct debit code if any payment means
    #: is one, else the first stated.
    payment_means_code: str | None = None
    #: The payee's account (BG-17): at most one — none if the XML states none, only an
    #: invalid IBAN, or several different ones (:func:`read` says why).
    payee_accounts: tuple[PayeeAccount, ...] = ()
    #: The buyer's identifier at the seller (BT-46).
    buyer_id: str | None = None

    @property
    def direct_debit(self) -> bool:
        """The seller collects the amount by direct debit (BT-81 ``49`` or ``59``)."""
        return self.payment_means_code in DIRECT_DEBIT_CODES

    @property
    def payee_account(self) -> PayeeAccount | None:
        return self.payee_accounts[0] if self.payee_accounts else None


@dataclass(frozen=True, slots=True)
class Reading:
    """The outcome of :func:`read`: the invoice (amounts only if they are consistent) and
    every reason the data is incomplete or doubtful."""

    invoice: ReadInvoice | None
    problems: tuple[str, ...]

    @property
    def has_amounts(self) -> bool:
        return self.invoice is not None and self.invoice.gross_amount is not None


def _shown(value: str) -> str:
    """A value of the input in a message: bounded, whatever the input holds."""
    return repr(value if len(value) <= 40 else f"{value[:40]}…")


def _text(node: ET.Element | None, path: str, ns: dict[str, str]) -> str | None:
    if node is None:
        return None
    found = node.find(path, ns)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _amount(value: str | None, what: str) -> Decimal | None:
    if value is None:
        return None
    if len(value) > _MAX_NUMBER_LENGTH or not _NUMBER.fullmatch(value):
        raise ReadError(f"{what} is not a number: {_shown(value)}")
    return Decimal(value)


#: A stated account before :func:`_check_payment`: IBAN as written, account name, BIC.
_RawAccount = tuple[str, str | None, str | None]


def _means_code(codes: list[str]) -> str | None:
    """The payment means code of :attr:`ReadInvoice.payment_means_code`."""
    return next((code for code in codes if code in DIRECT_DEBIT_CODES), codes[0] if codes else None)


def _cii_date(value: str | None, what: str) -> date | None:
    # Format 102 (the only one EN 16931 allows): YYYYMMDD.
    if value is None:
        return None
    try:
        if not _CII_DATE.fullmatch(value):
            raise ValueError
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError as exc:
        raise ReadError(f"{what} is not a date (YYYYMMDD): {_shown(value)}") from exc


def _iso_date(value: str | None, what: str) -> date | None:
    if value is None:
        return None
    try:
        if not _ISO_DATE.fullmatch(value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReadError(f"{what} is not a date (YYYY-MM-DD): {_shown(value)}") from exc


def _in_currency(nodes: list[ET.Element], currency: str | None, what: str) -> Decimal | None:
    """The one amount among ``nodes`` in the invoice currency (the tax total may be
    stated a second time in the accounting currency)."""
    candidates = [node for node in nodes if node.get("currencyID") in (None, currency)]
    if len(candidates) > 1:
        raise ReadError(f"{what} is stated {len(candidates)} times in {currency}")
    return _amount((candidates[0].text or "").strip() or None, what) if candidates else None


def _parse_cii(root: ET.Element, fmt: DataFormat) -> tuple[ReadInvoice, list[_RawAccount]]:
    ns = _CII_NS
    document = root.find("rsm:ExchangedDocument", ns)
    transaction = root.find("rsm:SupplyChainTradeTransaction", ns)
    agreement = transaction.find("ram:ApplicableHeaderTradeAgreement", ns) if transaction is not None else None
    settlement = transaction.find("ram:ApplicableHeaderTradeSettlement", ns) if transaction is not None else None
    totals = (
        settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", ns) if settlement is not None else None
    )
    currency = _text(settlement, "ram:InvoiceCurrencyCode", ns)
    seller = agreement.find("ram:SellerTradeParty", ns) if agreement is not None else None
    buyer = agreement.find("ram:BuyerTradeParty", ns) if agreement is not None else None
    means = settlement.findall("ram:SpecifiedTradeSettlementPaymentMeans", ns) if settlement is not None else []
    # ram:ProprietaryID is an account without an IBAN: never one a draft pays to.
    accounts: list[_RawAccount] = [
        (
            iban,
            _text(entry, "ram:PayeePartyCreditorFinancialAccount/ram:AccountName", ns),
            _text(entry, "ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID", ns),
        )
        for entry in means
        if (iban := _text(entry, "ram:PayeePartyCreditorFinancialAccount/ram:IBANID", ns)) is not None
    ]
    invoice = ReadInvoice(
        format=fmt,
        type_code=_text(document, "ram:TypeCode", ns) or "",
        number=_text(document, "ram:ID", ns),
        issue_date=_cii_date(_text(document, "ram:IssueDateTime/udt:DateTimeString", ns), "issue date"),
        due_date=_cii_date(
            _text(settlement, "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString", ns), "due date"
        ),
        service_period_start=_cii_date(
            _text(settlement, "ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString", ns),
            "service period start",
        ),
        service_period_end=_cii_date(
            _text(settlement, "ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString", ns),
            "service period end",
        ),
        currency=currency,
        net_amount=_amount(_text(totals, "ram:TaxBasisTotalAmount", ns), "net total"),
        tax_amount=_in_currency(
            totals.findall("ram:TaxTotalAmount", ns) if totals is not None else [], currency, "tax total"
        ),
        gross_amount=_amount(_text(totals, "ram:GrandTotalAmount", ns), "grand total"),
        seller_name=_text(seller, "ram:Name", ns),
        seller_vat_id=_text(seller, "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ns),
        buyer_vat_id=_text(buyer, "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ns),
        tax_breakdown=tuple(
            ReadTax(
                category=_text(entry, "ram:CategoryCode", ns),
                rate=_amount(_text(entry, "ram:RateApplicablePercent", ns), "VAT rate"),
                basis=_amount(_text(entry, "ram:BasisAmount", ns), "VAT taxable amount"),
                tax=_amount(_text(entry, "ram:CalculatedAmount", ns), "VAT amount"),
            )
            for entry in (settlement.findall("ram:ApplicableTradeTax", ns) if settlement is not None else [])
        ),
        payment_means_code=_means_code([code for entry in means if (code := _text(entry, "ram:TypeCode", ns))]),
        buyer_id=_text(buyer, "ram:ID", ns),
    )
    return invoice, accounts


def _parse_ubl(root: ET.Element) -> tuple[ReadInvoice, list[_RawAccount]]:
    ns = _UBL_NS
    currency = _text(root, "cbc:DocumentCurrencyCode", ns)
    totals = root.find("cac:LegalMonetaryTotal", ns)
    seller = root.find("cac:AccountingSupplierParty/cac:Party", ns)
    buyer = root.find("cac:AccountingCustomerParty/cac:Party", ns)
    means = root.findall("cac:PaymentMeans", ns)
    accounts: list[_RawAccount] = [
        (
            iban,
            _text(entry, "cac:PayeeFinancialAccount/cbc:Name", ns),
            _text(entry, "cac:PayeeFinancialAccount/cac:FinancialInstitutionBranch/cbc:ID", ns),
        )
        for entry in means
        if (iban := _text(entry, "cac:PayeeFinancialAccount/cbc:ID", ns)) is not None
    ]
    invoice = ReadInvoice(
        format=DataFormat.XRECHNUNG_UBL,
        type_code=_text(root, "cbc:InvoiceTypeCode", ns) or "",
        number=_text(root, "cbc:ID", ns),
        issue_date=_iso_date(_text(root, "cbc:IssueDate", ns), "issue date"),
        due_date=_iso_date(_text(root, "cbc:DueDate", ns), "due date"),
        service_period_start=_iso_date(_text(root, "cac:InvoicePeriod/cbc:StartDate", ns), "service period start"),
        service_period_end=_iso_date(_text(root, "cac:InvoicePeriod/cbc:EndDate", ns), "service period end"),
        currency=currency,
        net_amount=_amount(_text(totals, "cbc:TaxExclusiveAmount", ns), "net total"),
        tax_amount=_in_currency(root.findall("cac:TaxTotal/cbc:TaxAmount", ns), currency, "tax total"),
        gross_amount=_amount(_text(totals, "cbc:TaxInclusiveAmount", ns), "grand total"),
        seller_name=_text(seller, "cac:PartyLegalEntity/cbc:RegistrationName", ns)
        or _text(seller, "cac:PartyName/cbc:Name", ns),
        seller_vat_id=_text(seller, "cac:PartyTaxScheme/cbc:CompanyID", ns),
        buyer_vat_id=_text(buyer, "cac:PartyTaxScheme/cbc:CompanyID", ns),
        tax_breakdown=tuple(
            ReadTax(
                category=_text(entry, "cac:TaxCategory/cbc:ID", ns),
                rate=_amount(_text(entry, "cac:TaxCategory/cbc:Percent", ns), "VAT rate"),
                basis=_amount(_text(entry, "cbc:TaxableAmount", ns), "VAT taxable amount"),
                tax=_amount(_text(entry, "cbc:TaxAmount", ns), "VAT amount"),
            )
            # The tax total in the accounting currency (BT-111) has no breakdown.
            for total in root.findall("cac:TaxTotal", ns)
            if total.find("cac:TaxSubtotal", ns) is not None
            for entry in total.findall("cac:TaxSubtotal", ns)
        ),
        payment_means_code=_means_code([code for entry in means if (code := _text(entry, "cbc:PaymentMeansCode", ns))]),
        buyer_id=_text(buyer, "cac:PartyIdentification/cbc:ID", ns),
    )
    return invoice, accounts


#: VAT categories (UNTDID 5305) of an invoice that states its VAT per rate: standard
#: rate, zero rated, exempt (the last two at 0 %).
STANDARD_CATEGORIES = frozenset({"S", "Z", "E"})
#: The category of a reverse-charge invoice: the buyer owes the VAT.
REVERSE_CHARGE_CATEGORY = "AE"


@dataclass(frozen=True, slots=True)
class VatSplit:
    """The VAT of an e-invoice per rate: the treatment and (rate, net, tax), highest rate first."""

    treatment: TaxTreatment
    lines: tuple[tuple[Decimal, Decimal, Decimal], ...]


def vat_split(invoice: ReadInvoice) -> VatSplit | str:
    """The VAT of ``invoice`` per rate from its breakdown (BG-23), or why it says none.

    Categories ``S``, ``Z``, ``E`` are rates of a standard split (``Z`` and ``E`` at 0 %,
    entries of one rate added up); ``AE`` alone is reverse charge, one line at
    0 % without tax. Any other category (intra-community supply ``K``, export ``G``, not
    subject to VAT ``O`` …), a mix of reverse charge and VAT, an entry without category,
    rate or amounts: no split — never a guess. Whether the lines add up to the totals is
    left to the caller.
    """
    with localcontext(context()):
        return _vat_split(invoice)


def _vat_split(invoice: ReadInvoice) -> VatSplit | str:
    entries = invoice.tax_breakdown
    if not entries:
        return "the e-invoice data has no VAT breakdown"
    categories = {entry.category for entry in entries}
    if None in categories:
        return "an entry of the VAT breakdown has no category"
    if any(entry.basis is None or entry.tax is None for entry in entries):
        return "an entry of the VAT breakdown lacks its taxable amount or its tax"
    if categories == {REVERSE_CHARGE_CATEGORY}:
        if any(entry.tax != 0 for entry in entries):
            return "the VAT breakdown is reverse charge (AE) but states a tax"
        net = sum((entry.basis or Decimal(0) for entry in entries), Decimal(0))
        return VatSplit(TaxTreatment.REVERSE_CHARGE, ((Decimal(0), net, Decimal(0)),))
    other = sorted(category for category in categories if category and category not in STANDARD_CATEGORIES)
    if other:
        return f"the VAT breakdown has the categor{'y' if len(other) == 1 else 'ies'} {', '.join(other)} (no split)"
    by_rate: dict[Decimal, tuple[Decimal, Decimal]] = {}
    for entry in entries:
        rate = entry.rate if entry.category == "S" else (entry.rate or Decimal(0))
        assert entry.basis is not None and entry.tax is not None  # checked above
        if rate is None:
            return "a standard-rated entry of the VAT breakdown has no rate"
        if entry.category != "S" and rate != 0:
            return f"a {entry.category} entry of the VAT breakdown has the rate {rate}"
        net, tax = by_rate.get(rate, (Decimal(0), Decimal(0)))
        by_rate[rate] = (net + entry.basis, tax + entry.tax)
    lines = tuple((rate, net, tax) for rate, (net, tax) in sorted(by_rate.items(), reverse=True))
    return VatSplit(TaxTreatment.STANDARD, lines)


def parse_invoice_xml(data: bytes, *, embedded: bool) -> ReadInvoice:
    """Parse CII or UBL invoice XML. Raises :class:`~einvoice_xml.errors.ReadError` for
    anything else.

    The payee's account is taken only if it is unambiguous and valid (:func:`read` says
    why not). ``embedded`` tells that the XML comes out of a ZUGFeRD/Factur-X PDF: then it
    is CII, and UBL is refused.
    """
    return _check_payment(*_parse_invoice_xml(data, embedded=embedded))[0]


def _root(data: bytes) -> ET.Element:
    """The root element of ``data``; a DTD is refused outright: an invoice never needs
    one, and entity expansion is the classic XML attack."""
    if len(data) > MAX_XML_BYTES:
        raise LimitExceededError(f"the XML is larger than {MAX_XML_BYTES} bytes")
    try:
        root: ET.Element = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        raise ReadError("the XML declares a DTD or entities") from exc
    except ET.ParseError as exc:
        raise ReadError(f"not well-formed XML: {exc}") from exc
    except (ValueError, LookupError, RecursionError, MemoryError) as exc:  # e.g. an unknown encoding
        raise ReadError(f"not well-formed XML: {type(exc).__name__}") from exc
    return root


def _parse_invoice_xml(data: bytes, *, embedded: bool) -> tuple[ReadInvoice, list[_RawAccount]]:
    root = _root(data)
    if root.tag == f"{{{CII}}}CrossIndustryInvoice":
        return _parse_cii(root, DataFormat.FACTUR_X if embedded else DataFormat.XRECHNUNG_CII)
    if not embedded and root.tag == f"{{{UBL_INVOICE}}}Invoice":
        return _parse_ubl(root)
    if not embedded and root.tag == f"{{{UBL_CREDIT_NOTE}}}CreditNote":
        raise ReadError("the XML is a UBL credit note, not an invoice")
    raise ReadError(f"unknown XML document {_shown(root.tag)} (neither CII nor UBL invoice)")


def invoice_xml_root(data: bytes) -> str | None:
    """What kind of e-invoice the XML file ``data`` is — ``"CII"``, ``"UBL invoice"`` or
    ``"UBL credit note"`` — by its root element; ``None`` for anything else (other XML,
    XML with a DTD, no XML at all)."""
    try:
        root = _root(data)
    except ReadError:
        return None
    return {
        f"{{{CII}}}CrossIndustryInvoice": "CII",
        f"{{{UBL_INVOICE}}}Invoice": "UBL invoice",
        f"{{{UBL_CREDIT_NOTE}}}CreditNote": "UBL credit note",
    }.get(root.tag)


def _xml_names(entry: EmbeddedFile) -> list[str]:
    """The names of ``entry`` that end in ``.xml``: its key in the name tree, its file name.

    Both are input. A file name that is of the wrong type or cannot be resolved is no name,
    which leaves the entry its key; it does not cost the other files of the PDF their reading.
    """
    names = [str(entry.name)]
    try:
        file_name = entry.alternative_name
    except Exception:  # noqa: BLE001
        file_name = None
    if isinstance(file_name, str):
        names.append(str(file_name))
    return [name for name in names if name.lower().endswith(".xml")]


def _embedded_xml(pdf: bytes) -> list[tuple[list[str], EmbeddedFile]]:
    """The XML files embedded in ``pdf`` with their names, the known invoice names first;
    none decoded yet."""
    files: list[tuple[list[str], EmbeddedFile]] = []
    try:
        for index, entry in enumerate(PdfReader(io.BytesIO(pdf)).attachment_list):
            if index >= MAX_EMBEDDED_FILES:
                raise LimitExceededError(f"the PDF embeds more than {MAX_EMBEDDED_FILES} files")
            names = _xml_names(entry)
            if names:
                files.append((names, entry))
    except EInvoiceError:
        raise
    except Exception as exc:
        raise ReadError(f"the PDF cannot be read: {type(exc).__name__}") from exc
    return sorted(files, key=lambda item: not any(name.lower() in KNOWN_ATTACHMENTS for name in item[0]))


def _content(entry: EmbeddedFile) -> bytes:
    """The decompressed content of ``entry``, within :data:`MAX_XML_BYTES`.

    pypdf keeps a decoded stream on its reader. That copy is dropped here, or the content of
    every file would stay in memory however large: one file at a time is what the limit of
    pypdf on a stream bounds.
    """
    try:
        stream = entry._embedded_file
        content = stream.get_data()
    except Exception as exc:
        raise ReadError(f"the embedded file cannot be read: {type(exc).__name__}") from exc
    stream.decoded_self = None
    if len(content) > MAX_XML_BYTES:
        raise LimitExceededError(f"the XML is larger than {MAX_XML_BYTES} bytes")
    return content


def _check_payment(invoice: ReadInvoice, accounts: list[_RawAccount]) -> tuple[ReadInvoice, list[str]]:
    """The payee account of ``invoice`` from the ``accounts`` stated: an invalid IBAN is
    dropped, several different valid ones give none — never a pick; the reasons."""
    problems: list[str] = []
    valid: dict[str, PayeeAccount] = {}
    for raw, name, bic in accounts:
        iban = normalise_iban(raw)
        if not is_valid_iban(iban):
            problems.append(f"the payee IBAN {_shown(raw)} of the e-invoice data is invalid (not used)")
            continue
        known = valid.get(iban)
        valid[iban] = PayeeAccount(
            iban=iban,
            account_name=(known.account_name if known else None) or name,
            bic=((known.bic if known else None) or bic or "").replace(" ", "").upper() or None,
        )
    if len(valid) > 1:
        problems.append(f"the e-invoice data names {len(valid)} different payee IBANs: none is taken")
        valid = {}
    return replace(invoice, payee_accounts=tuple(valid.values())), problems


def _check(invoice: ReadInvoice) -> tuple[ReadInvoice, list[str]]:
    """Drop the amounts of an invoice whose data cannot be trusted; say why."""
    problems: list[str] = []
    if invoice.type_code not in INVOICE_TYPE_CODES:
        code = _shown(invoice.type_code) if invoice.type_code else "(none)"
        problems.append(f"document type code {code} is not an invoice (381 would be a credit note)")
    net, tax, gross = invoice.net_amount, invoice.tax_amount, invoice.gross_amount
    if net is None or tax is None or gross is None:
        problems.append("the XML lacks the net, tax or grand total")
    elif context().add(net, tax) != gross:
        problems.append(f"the totals do not add up: net {net} + tax {tax} ≠ grand total {gross}")
    if invoice.currency is None or not re.fullmatch(r"[A-Z]{3}", invoice.currency):
        shown = None if invoice.currency is None else _shown(invoice.currency)
        problems.append(f"invoice currency {shown} is not an ISO 4217 code")
    if problems:
        invoice = replace(invoice, net_amount=None, tax_amount=None, gross_amount=None)
    return invoice, problems


def _reading(invoice: ReadInvoice, accounts: list[_RawAccount]) -> Reading:
    invoice, problems = _check(invoice)
    invoice, payment = _check_payment(invoice, accounts)
    return Reading(invoice, (*problems, *payment))


def _read_pdf(content: bytes) -> Reading:
    if len(content) > MAX_PDF_BYTES:
        raise LimitExceededError(f"the PDF is larger than {MAX_PDF_BYTES} bytes")
    candidates = _embedded_xml(content)
    if not candidates:
        return Reading(None, ("the PDF has no embedded ZUGFeRD/Factur-X data",))
    errors: list[str] = []
    for names, entry in candidates:
        xrechnung = any(name.lower() == XRECHNUNG_ATTACHMENT for name in names)
        try:
            parsed = _parse_invoice_xml(_content(entry), embedded=not xrechnung)
        except ReadError as exc:
            errors.append(f"{_shown(names[0])}: {exc}")
            continue
        return _reading(*parsed)
    return Reading(None, (f"the embedded XML is no ZUGFeRD/Factur-X invoice ({'; '.join(errors)})",))


def read(content: bytes) -> Reading:
    """The structured invoice data of a PDF or XML file.

    Never raises for any ``bytes``: whatever is wrong with the input, including an
    exceeded limit, is a reason in :attr:`Reading.problems`.
    """
    head = content[:1024].lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        if b"%PDF-" in content[:1024]:
            return _read_pdf(content)
        if head.startswith(b"<") or content.startswith(_UTF16_MARKS):
            return _reading(*_parse_invoice_xml(content, embedded=False))
    except EInvoiceError as exc:
        return Reading(None, (f"the e-invoice data cannot be read: {exc}",))
    return Reading(None, ("the document is neither a PDF nor XML (no e-invoice data)",))
