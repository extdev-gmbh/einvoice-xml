# einvoice-xml

**einvoice-xml** builds EN 16931 invoices as UN/CEFACT CII XML (the profile EN 16931 of
ZUGFeRD/Factur-X, also usable for XRechnung in CII syntax), provides the XMP metadata and
the attachment parameters for a PDF/A-3 producer, and reads incoming CII, UBL and
ZUGFeRD/Factur-X PDFs into a neutral model.

It is a pure library: inputs are bytes and objects, outputs are values. No network, no
telemetry, no file access, no global state, no logging of document contents.

```bash
pip install einvoice-xml
```

Python 3.12 or later. Runtime dependencies: `pypdf` (embedded files) and `defusedxml`.

## Scope and limits

| | |
|---|---|
| Write | CII, profile EN 16931, VAT categories `S`, `AE`, `O`, `Z`, `E`, `K`, `G` |
| Embed | XMP metadata and attachment parameters for your PDF/A-3 producer |
| Read | ZUGFeRD/Factur-X PDF, bare CII, bare UBL `Invoice`, PDF carrying `xrechnung.xml` |

- **Not tax advice, no certification.** The generated files are checked in CI against the
  EN 16931 rules with an external validator; whether an invoice is right under tax law
  remains your responsibility.
- **No XRechnung UBL writer yet**, and no XRechnung-specific (CIUS) checks: `build_cii`
  writes the guideline id of EN 16931.
- PDF layout is out of scope, and so is writing into an existing PDF: this library gives a
  PDF/A-3 producer what it embeds, it does not produce or change PDFs.
- `problems` checks the BR-* rules that depend on the data of the model, not every rule of
  the standard; document level allowances and charges are not part of the model.
- `read` reads header data, totals, the VAT breakdown and the payment data, not the lines.
  A credit note gives no amounts: a UBL `CreditNote` is refused, a CII document of type
  381 keeps its header data and says why.

## Writing

```python
from datetime import date
from decimal import Decimal

from einvoice_xml import (
    Invoice, InvoiceKind, Line, Party, PaymentMeans, VatCategory,
    build_cii, problems, tax_breakdown,
)

lines = (
    Line(id="1", name="Software development", quantity=Decimal("10"), unit_code="HUR",
         unit_price=Decimal("100.00"), net_amount=Decimal("1000.00"),
         category=VatCategory.STANDARD, rate=Decimal("19")),
)
invoice = Invoice(
    kind=InvoiceKind.INVOICE,
    number="RE-1",
    issue_date=date(2026, 10, 1),
    currency="EUR",
    seller=Party(name="Example GmbH", country="DE", street="Musterstraße 1", postal_code="12345",
                 city="Musterstadt", vat_id="DE123456789"),
    buyer=Party(name="Customer AG", country="DE"),
    lines=lines,
    tax_breakdown=tax_breakdown(lines),
    delivery_date=date(2026, 9, 30),
    due_date=date(2026, 10, 15),
    payment_means=(PaymentMeans("58", iban="DE89370400440532013000"),),
)

assert problems(invoice) == []
xml: bytes = build_cii(invoice)  # raises InvalidInvoiceError if problems() finds anything
```

The model states what the invoice says. Which VAT category applies, which UN/ECE unit code
a line has, and which VAT ids a credit note repeats are decisions of your system. Amounts
are `Decimal`, never `float`; the output does not depend on the decimal context.

## Embedding in a PDF/A-3

```python
from datetime import UTC, datetime

from einvoice_xml import attachment, xmp_metadata

metadata = xmp_metadata(title="Invoice RE-1", author="Example GmbH", creator_tool="my app",
                        created=datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
parameters = attachment()
# parameters.file_name == "factur-x.xml", parameters.mime_type == "text/xml",
# parameters.relationship == AFRelationship.ALTERNATIVE
```

Give both to your PDF/A-3 producer (with fpdf2: `set_xmp_metadata` and `embed_file`).

## Reading

```python
from einvoice_xml import read, vat_split

reading = read(content)  # bytes of a PDF or an XML file; never raises for any bytes
if reading.has_amounts:
    invoice = reading.invoice
    print(invoice.number, invoice.gross_amount, invoice.currency)
    print(invoice.payee_account, invoice.buyer_id, vat_split(invoice))
else:
    print(reading.problems)
```

`read` never guesses. Totals that do not add up or an unknown currency drop the amounts,
an invalid IBAN or several different ones give no account; each with its reason in
`reading.problems`.

## Security

Incoming invoices are hostile input.

- **XML goes through `defusedxml`**, with DTDs, entities and external references forbidden.
  The check is in the parser, so it holds for every encoding of the document; a search for
  `<!DOCTYPE` in the bytes would not see one in UTF-16.
- **Size limits:** `MAX_PDF_BYTES` (50 MiB), `MAX_XML_BYTES` (10 MiB), `MAX_EMBEDDED_FILES` (32),
  and numbers of at most 32 characters in plain notation.
- **Nothing from the input is evaluated**, nothing is fetched, and no file is touched.
- **Typed errors:** `read` turns every failure into a reason. `parse_invoice_xml` raises
  `ReadError` (`LimitExceededError` for a limit), `build_cii` `InvalidInvoiceError`; all are
  `EInvoiceError`. Hypothesis tests cover the parsers with random, mutated and malicious input.
- **Compressed attachments:** embedded files are decompressed one at a time and dropped when
  they are over the limit, so a PDF of many large streams does not add up in memory. `pypdf`
  bounds the decompression of a single stream itself (75 MB in the pinned version).
- `pypdf` logs warnings about damaged PDFs to its own logger; configure the logger `pypdf` if those must not reach your logs.

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Development

```bash
scripts/test.sh     # the test gate in a container, including the validator; needs only Docker
```

Releases follow [semantic versioning](CHANGELOG.md). Packages are published from a GitHub
Actions workflow by trusted publishing, with an SBOM and build provenance.

## Trademarks and licence

ZUGFeRD and Factur-X are names of their respective owners (FeRD, FNFE-MPE); this project is
not affiliated. XRechnung is named descriptively.

Licensed under the [Apache License 2.0](LICENSE).
