"""einvoice-xml: Build, embed and read EN 16931 e-invoices (ZUGFeRD/Factur-X CII, XRechnung CII/UBL).

Everything public is exported here; anything else is private.
"""

from einvoice_xml.embedding import (
    ATTACHMENT_NAME,
    CONFORMANCE_LEVEL,
    AFRelationship,
    Attachment,
    attachment,
    xmp_metadata,
)
from einvoice_xml.errors import EInvoiceError, InvalidInvoiceError, LimitExceededError, ReadError
from einvoice_xml.model import (
    Invoice,
    InvoiceKind,
    Line,
    Note,
    Party,
    PaymentMeans,
    PrecedingInvoice,
    TaxBreakdown,
    VatCategory,
)
from einvoice_xml.reader import (
    MAX_EMBEDDED_FILES,
    MAX_PDF_BYTES,
    MAX_XML_BYTES,
    DataFormat,
    PayeeAccount,
    Reading,
    ReadInvoice,
    ReadTax,
    TaxTreatment,
    VatSplit,
    invoice_xml_root,
    parse_invoice_xml,
    read,
    vat_split,
)
from einvoice_xml.writer import GUIDELINE, build_cii, problems, tax_breakdown

__version__ = "0.1.2"

__all__ = [
    "ATTACHMENT_NAME",
    "CONFORMANCE_LEVEL",
    "GUIDELINE",
    "MAX_EMBEDDED_FILES",
    "MAX_PDF_BYTES",
    "MAX_XML_BYTES",
    "AFRelationship",
    "Attachment",
    "DataFormat",
    "EInvoiceError",
    "InvalidInvoiceError",
    "Invoice",
    "InvoiceKind",
    "LimitExceededError",
    "Line",
    "Note",
    "Party",
    "PayeeAccount",
    "PaymentMeans",
    "PrecedingInvoice",
    "ReadError",
    "ReadInvoice",
    "ReadTax",
    "Reading",
    "TaxBreakdown",
    "TaxTreatment",
    "VatCategory",
    "VatSplit",
    "__version__",
    "attachment",
    "build_cii",
    "invoice_xml_root",
    "parse_invoice_xml",
    "problems",
    "read",
    "tax_breakdown",
    "vat_split",
    "xmp_metadata",
]
