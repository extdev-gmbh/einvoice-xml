"""The XMP metadata and the attachment parameters."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest

from einvoice_xml import ATTACHMENT_NAME, AFRelationship, EInvoiceError, attachment, xmp_metadata

CREATED = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _xmp(**fields: object) -> str:
    values: dict[str, object] = {"title": "Invoice", "author": "Example GmbH", "creator_tool": "x", "created": CREATED}
    values.update(fields)
    return xmp_metadata(**values)  # type: ignore[arg-type]


def test_metadata_names_pdf_a_3b_and_the_einvoice() -> None:
    metadata = _xmp()
    assert "<pdfaid:part>3</pdfaid:part>" in metadata and "<pdfaid:conformance>B</pdfaid:conformance>" in metadata
    assert "<fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>" in metadata
    assert "<fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>" in metadata
    assert "<fx:DocumentType>INVOICE</fx:DocumentType>" in metadata
    assert "<xmp:CreateDate>2026-10-01T12:00:00+00:00</xmp:CreateDate>" in metadata
    ET.fromstring(metadata)


def test_metadata_without_an_einvoice_has_no_extension_schema() -> None:
    metadata = _xmp(einvoice=False)
    assert "fx:" not in metadata and "<pdfaid:part>3</pdfaid:part>" in metadata


def test_metadata_is_escaped_and_stable() -> None:
    assert _xmp(title="A & <B>") == _xmp(title="A & <B>")
    assert "A &amp; &lt;B&gt;" in _xmp(title="A & <B>")
    ET.fromstring(_xmp(author="A & <B>"))


def test_a_value_xml_cannot_carry_is_refused() -> None:
    with pytest.raises(EInvoiceError, match="author"):
        _xmp(author="a\x00b")


def test_attachment_parameters() -> None:
    parameters = attachment()
    assert (parameters.file_name, parameters.mime_type, parameters.relationship) == (
        ATTACHMENT_NAME,
        "text/xml",
        AFRelationship.ALTERNATIVE,
    )
    assert attachment(AFRelationship.DATA).relationship.value == "Data"
