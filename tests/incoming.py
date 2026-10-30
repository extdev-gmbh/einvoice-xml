"""Invented incoming invoices as XML and PDF: suppliers, VAT ids, numbers and amounts are made up."""

from __future__ import annotations

import io
from collections.abc import Collection

from pypdf import PdfWriter
from pypdf.generic import NameObject, PdfObject, TextStringObject

SELLER = "Example Hosting GmbH"
SELLER_VAT_ID = "DE999999999"
BUYER_VAT_ID = "DE123456789"
#: Checksum-valid example IBANs.
PAYEE_IBAN = "DE89370400440532013000"
OTHER_PAYEE_IBAN = "GB82WEST12345698765432"

#: A payment means of an invoice (BG-16): code (BT-81), IBAN, account name, BIC.
PaymentMeans = tuple[str, str | None, str | None, str | None]


def cii(
    *,
    number: str = "INV-2026-0815",
    type_code: str = "380",
    issued: str = "20260901",
    due: str | None = "20260915",
    currency: str = "EUR",
    net: str = "100.00",
    tax: str = "19.00",
    gross: str = "119.00",
    buyer_vat_id: str = BUYER_VAT_ID,
    extra_tax_total: str | None = None,
    taxes: Collection[tuple[str, str | None, str, str]] = (),
    payment_means: Collection[PaymentMeans] = (),
    buyer_id: str | None = None,
) -> bytes:
    """A CII invoice (the XML of ZUGFeRD 2.x / Factur-X and of an XRechnung in CII syntax);
    ``taxes`` is its VAT breakdown: (category, rate, taxable amount, tax) per entry;
    ``payment_means`` its payment means (BG-16), ``buyer_id`` the id at the seller (BT-46)."""
    means = "".join(
        f"<ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>{code}</ram:TypeCode>"
        + (
            "<ram:PayeePartyCreditorFinancialAccount>"
            + (f"<ram:IBANID>{iban}</ram:IBANID>" if iban else "")
            + (f"<ram:AccountName>{name}</ram:AccountName>" if name else "")
            + "</ram:PayeePartyCreditorFinancialAccount>"
            if iban or name
            else ""
        )
        + (
            f"<ram:PayeeSpecifiedCreditorFinancialInstitution><ram:BICID>{bic}</ram:BICID>"
            "</ram:PayeeSpecifiedCreditorFinancialInstitution>"
            if bic
            else ""
        )
        + "</ram:SpecifiedTradeSettlementPaymentMeans>"
        for code, iban, name, bic in payment_means
    )
    buyer_id_xml = f"<ram:ID>{buyer_id}</ram:ID>" if buyer_id else ""
    due_xml = (
        "<ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime>"
        f'<udt:DateTimeString format="102">{due}</udt:DateTimeString>'
        "</ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>"
        if due
        else ""
    )
    extra = f'<ram:TaxTotalAmount currencyID="USD">{extra_tax_total}</ram:TaxTotalAmount>' if extra_tax_total else ""
    breakdown = "".join(
        "<ram:ApplicableTradeTax>"
        f"<ram:CalculatedAmount>{amount}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>"
        f"<ram:BasisAmount>{basis}</ram:BasisAmount><ram:CategoryCode>{category}</ram:CategoryCode>"
        + (f"<ram:RateApplicablePercent>{rate}</ram:RateApplicablePercent>" if rate is not None else "")
        + "</ram:ApplicableTradeTax>"
        for category, rate, basis, amount in taxes
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{number}</ram:ID>
    <ram:TypeCode>{type_code}</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">{issued}</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>{SELLER}</ram:Name>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{SELLER_VAT_ID}</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        {buyer_id_xml}
        <ram:Name>Example GmbH</ram:Name>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{buyer_vat_id}</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>{currency}</ram:InvoiceCurrencyCode>
      {means}
      {breakdown}
      <ram:BillingSpecifiedPeriod>
        <ram:StartDateTime><udt:DateTimeString format="102">20260801</udt:DateTimeString></ram:StartDateTime>
        <ram:EndDateTime><udt:DateTimeString format="102">20260831</udt:DateTimeString></ram:EndDateTime>
      </ram:BillingSpecifiedPeriod>
      {due_xml}
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{net}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{net}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="{currency}">{tax}</ram:TaxTotalAmount>
        {extra}
        <ram:GrandTotalAmount>{gross}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{gross}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
""".encode()


def ubl(
    *,
    root: str = "Invoice",
    number: str = "R-4711",
    net: str = "250.00",
    tax: str = "47.50",
    gross: str = "297.50",
    taxes: Collection[tuple[str, str | None, str, str]] = (),
    payment_means: Collection[PaymentMeans] = (),
    buyer_id: str | None = None,
) -> bytes:
    """An XRechnung in UBL syntax; ``taxes`` is its VAT breakdown: (category, rate,
    taxable amount, tax) per entry; ``payment_means`` its payment means (BG-16),
    ``buyer_id`` the id at the seller (BT-46)."""
    means = "".join(
        f"<cac:PaymentMeans><cbc:PaymentMeansCode>{code}</cbc:PaymentMeansCode>"
        + (
            "<cac:PayeeFinancialAccount>"
            + (f"<cbc:ID>{iban}</cbc:ID>" if iban else "")
            + (f"<cbc:Name>{name}</cbc:Name>" if name else "")
            + (
                f"<cac:FinancialInstitutionBranch><cbc:ID>{bic}</cbc:ID></cac:FinancialInstitutionBranch>"
                if bic
                else ""
            )
            + "</cac:PayeeFinancialAccount>"
            if iban or name or bic
            else ""
        )
        + "</cac:PaymentMeans>"
        for code, iban, name, bic in payment_means
    )
    buyer_id_xml = f"<cac:PartyIdentification><cbc:ID>{buyer_id}</cbc:ID></cac:PartyIdentification>" if buyer_id else ""
    namespace = f"urn:oasis:names:specification:ubl:schema:xsd:{root}-2"
    subtotals = "".join(
        "<cac:TaxSubtotal>"
        f'<cbc:TaxableAmount currencyID="EUR">{basis}</cbc:TaxableAmount>'
        f'<cbc:TaxAmount currencyID="EUR">{amount}</cbc:TaxAmount>'
        f"<cac:TaxCategory><cbc:ID>{category}</cbc:ID>"
        + (f"<cbc:Percent>{rate}</cbc:Percent>" if rate is not None else "")
        + "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>"
        for category, rate, basis, amount in taxes
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{root} xmlns="{namespace}"
    xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ID>{number}</cbc:ID>
  <cbc:IssueDate>2026-09-02</cbc:IssueDate>
  <cbc:DueDate>2026-10-02</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:InvoicePeriod><cbc:StartDate>2026-08-01</cbc:StartDate><cbc:EndDate>2026-08-31</cbc:EndDate></cac:InvoicePeriod>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyTaxScheme><cbc:CompanyID>{SELLER_VAT_ID}</cbc:CompanyID></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Example Consulting GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    {buyer_id_xml}
    <cac:PartyTaxScheme><cbc:CompanyID>{BUYER_VAT_ID}</cbc:CompanyID></cac:PartyTaxScheme>
  </cac:Party></cac:AccountingCustomerParty>
  {means}
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{tax}</cbc:TaxAmount>{subtotals}</cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">{net}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">{net}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">{gross}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{gross}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</{root}>
""".encode()


def pdf(
    attachments: dict[str, bytes] | None = None,
    *,
    file_specs: dict[str, dict[str, str | PdfObject | None]] | None = None,
) -> bytes:
    """A blank PDF with ``attachments`` embedded. ``file_specs`` overrides entries of the file
    specification of an attachment, by its key in the name tree, such as
    ``{"attachment1": {"/F": "factur-x.xml"}}``; ``None`` removes the entry."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    for name, content in (attachments or {}).items():
        spec = writer.add_attachment(name, content).pdf_object
        for key, value in (file_specs or {}).get(name, {}).items():
            if value is None:
                del spec[key]
            else:
                spec[NameObject(key)] = TextStringObject(value) if isinstance(value, str) else value
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def zugferd_pdf() -> bytes:
    return pdf({"factur-x.xml": cii()})
