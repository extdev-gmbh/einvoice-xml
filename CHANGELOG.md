# Changelog

All notable changes to einvoice-xml are listed here. The project follows
[Semantic Versioning](https://semver.org/): everything exported from the package root is
public API, anything else is private; a breaking change needs a major version and an entry
here.

## [Unreleased]

## [0.1.1] - 2026-10-30

First published release. 0.1.0 was tagged but never published to PyPI (broken pin of the
publish action).

### Fixed

- The release workflow pins the publish action to the commit of its tag. No functional change
  to the library.

## [0.1.0] - 2026-10-30 (not published)

First release.

### Added

- Neutral model of an invoice or credit note, with the VAT categories `S`, `AE`, `O`, `Z`, `E`,
  `K`, `G`.
- `build_cii`: UN/CEFACT CII, profile EN 16931; byte-identical output for the same input.
  `problems`: what keeps an invoice from being valid. `tax_breakdown`: the VAT breakdown of lines.
- `xmp_metadata` and `attachment`: what a PDF/A-3 producer needs to carry the XML.
- `read`: ZUGFeRD/Factur-X PDFs, bare CII and UBL XML, PDFs carrying `xrechnung.xml`; header
  data, totals, VAT breakdown, payee account, buyer identifier, or the reason why none.
  `vat_split`, `parse_invoice_xml`, `invoice_xml_root`.
- Size limits, refusal of DTDs and entities through `defusedxml`, typed errors; property and
  fuzz tests on hostile XML and PDF input.
- CI validation of the generated XML and PDF/A-3 with Mustang-CLI; SBOM, provenance and trusted
  publishing to PyPI.
