"""What a PDF/A-3 producer needs to carry the e-invoice: the XMP metadata with the Factur-X
extension schema, and the parameters of the attachment. Pure, no I/O, no PDF is touched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from xml.sax.saxutils import escape

from einvoice_xml.errors import EInvoiceError
from einvoice_xml.writer import NOT_XML

#: Name of the embedded file (Factur-X 1.0 / ZUGFeRD 2.1 and later).
ATTACHMENT_NAME = "factur-x.xml"
#: The conformance level named in the XMP metadata for the profile EN 16931.
CONFORMANCE_LEVEL = "EN 16931"
_MIME_TYPE = "text/xml"
_DESCRIPTION = "Factur-X/ZUGFeRD invoice (EN 16931)"

_XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
   <pdfaid:part>3</pdfaid:part>
   <pdfaid:conformance>B</pdfaid:conformance>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>{author}</rdf:li></rdf:Seq></dc:creator>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">
   <xmp:CreatorTool>{creator}</xmp:CreatorTool>
   <xmp:CreateDate>{created}</xmp:CreateDate>
   <xmp:ModifyDate>{created}</xmp:ModifyDate>
  </rdf:Description>{einvoice}
 </rdf:RDF>
</x:xmpmeta>"""
#: The Factur-X extension schema and its values: which e-invoice the PDF carries.
_XMP_EINVOICE = """
  <rdf:Description rdf:about="" xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/" \
xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#" xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
   <pdfaExtension:schemas>
    <rdf:Bag>
     <rdf:li rdf:parseType="Resource">
      <pdfaSchema:schema>Factur-X PDFA Extension Schema</pdfaSchema:schema>
      <pdfaSchema:namespaceURI>urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#</pdfaSchema:namespaceURI>
      <pdfaSchema:prefix>fx</pdfaSchema:prefix>
      <pdfaSchema:property>
       <rdf:Seq>{properties}
       </rdf:Seq>
      </pdfaSchema:property>
     </rdf:li>
    </rdf:Bag>
   </pdfaExtension:schemas>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
   <fx:DocumentType>INVOICE</fx:DocumentType>
   <fx:DocumentFileName>{file_name}</fx:DocumentFileName>
   <fx:Version>1.0</fx:Version>
   <fx:ConformanceLevel>{level}</fx:ConformanceLevel>
  </rdf:Description>"""
_XMP_PROPERTY = """
        <rdf:li rdf:parseType="Resource">
         <pdfaProperty:name>{name}</pdfaProperty:name>
         <pdfaProperty:valueType>Text</pdfaProperty:valueType>
         <pdfaProperty:category>external</pdfaProperty:category>
         <pdfaProperty:description>{description}</pdfaProperty:description>
        </rdf:li>"""
_XMP_PROPERTIES = (
    ("DocumentFileName", "The name of the embedded XML document"),
    ("DocumentType", "The type of the hybrid document in capital letters, e.g. INVOICE or ORDER"),
    ("Version", "The actual version of the standard applying to the embedded XML document"),
    ("ConformanceLevel", "The conformance level of the embedded XML document"),
)


class AFRelationship(StrEnum):
    """How the embedded file relates to the PDF (the ``/AFRelationship`` of its file specification)."""

    #: The XML is the invoice, the PDF its rendering: what ZUGFeRD asks for in Germany.
    ALTERNATIVE = "Alternative"
    #: The XML carries data the PDF shows.
    DATA = "Data"


@dataclass(frozen=True, slots=True)
class Attachment:
    """The parameters of the embedded file; the content is the output of :func:`~einvoice_xml.build_cii`."""

    file_name: str
    mime_type: str
    relationship: AFRelationship
    description: str


def attachment(relationship: AFRelationship = AFRelationship.ALTERNATIVE) -> Attachment:
    """How a PDF/A-3 producer embeds the XML."""
    return Attachment(ATTACHMENT_NAME, _MIME_TYPE, relationship, _DESCRIPTION)


def _text(value: str, what: str) -> str:
    if NOT_XML.search(value):
        raise EInvoiceError(f"the {what} contains a character XML cannot carry")
    return escape(value)


def xmp_metadata(*, title: str, author: str, creator_tool: str, created: datetime, einvoice: bool = True) -> str:
    """The XMP packet body of the PDF/A-3b document.

    ``einvoice=False`` leaves out the Factur-X part, for a PDF/A-3 without an e-invoice.
    ``created`` is stated by the caller: the same input gives the same metadata.
    """
    properties = "".join(_XMP_PROPERTY.format(name=name, description=text) for name, text in _XMP_PROPERTIES)
    return _XMP.format(
        title=_text(title, "title"),
        author=_text(author, "author"),
        creator=_text(creator_tool, "creator tool"),
        created=created.isoformat(timespec="seconds"),
        einvoice=_XMP_EINVOICE.format(properties=properties, file_name=ATTACHMENT_NAME, level=CONFORMANCE_LEVEL)
        if einvoice
        else "",
    )
