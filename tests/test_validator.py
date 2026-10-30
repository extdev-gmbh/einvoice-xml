"""The generated files pass the external validator (Mustang): the XML of every sample against
the XML schema and the EN 16931 rules, and a PDF/A-3 built here with the XMP metadata and the
attachment parameters of the library. A failing validation fails the test.

The validator is part of the test gate: the CI jobs and scripts/test.sh install it with
scripts/install-einvoice-validator.sh. Without it this test fails — it never skips.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest
import samples as s
from fpdf import FPDF
from fpdf.enums import AssociatedFileRelationship, DocumentCompliance, OutputIntentSubType
from fpdf.output import PDFICCProfile
from PIL import ImageCms

from einvoice_xml import AFRelationship, Invoice, attachment, build_cii, read, xmp_metadata

#: Path of the Mustang-CLI jar.
VALIDATOR_ENV = "EINVOICE_VALIDATOR_JAR"
CATEGORIES = s.per_category()
CREATED = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_NO_LOG_FILE = ("--disable-file-logging",)


def _validator() -> str:
    jar = os.environ.get(VALIDATOR_ENV, "")
    assert jar and Path(jar).is_file() and shutil.which("java"), (
        f"the e-invoice validator is not installed: run scripts/install-einvoice-validator.sh and set "
        f"{VALIDATOR_ENV} to the jar (scripts/test.sh brings it along)"
    )
    return jar


def _report(path: Path) -> tuple[int, ET.Element | None, str]:
    """Mustang's verdict on ``path``: exit code, the validation report, the raw output."""
    run = subprocess.run(
        [*("java", "-Xmx512m", "-jar", _validator()), "--action", "validate", "--source", str(path), *_NO_LOG_FILE],
        capture_output=True,
        text=True,
        cwd=path.parent,
        timeout=300,
        check=False,
    )
    start, end = run.stdout.find("<validation"), run.stdout.rfind("</validation>")
    if start < 0 or end < 0:
        return run.returncode, None, f"{run.stdout[-2000:]} {run.stderr[-2000:]}"
    return run.returncode, ET.fromstring(run.stdout[start : end + len("</validation>")]), run.stdout


def _validate(path: Path, summaries_expected: int) -> list[str]:
    """What Mustang objects to (empty: valid). Errors and warnings count; notices are rules
    of other profiles it reports for information."""
    code, report, output = _report(path)
    if report is None:
        return [f"no validation report (exit code {code}): {output}"]
    findings = [
        f"{element.tag} {element.get('type', '')} {element.get('location', '')}: {(element.text or '').strip()}"
        for element in report.iter()
        if element.tag in ("error", "exception", "warning")
    ]
    summaries = [summary.get("status") for summary in report.iter("summary")]
    if code == 0 and len(summaries) == summaries_expected and all(status == "valid" for status in summaries):
        return findings
    return findings or [f"invalid (exit code {code}, summaries {summaries})"]


def _pdf(xml: bytes) -> bytes:
    """A minimal PDF/A-3b with ``xml`` embedded the way the library says."""
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    parameters = attachment(AFRelationship.ALTERNATIVE)
    pdf = FPDF(enforce_compliance=DocumentCompliance.PDFA_3B)
    pdf.add_output_intent(
        OutputIntentSubType.PDFA, "sRGB", "IEC 61966-2-1:1999", "http://www.color.org",
        PDFICCProfile(contents=icc, n=3, alternate="DeviceRGB"), "sRGB",
    )  # fmt: skip
    pdf.set_title("Invoice RE0001")
    pdf.set_author("Example Software GmbH")
    pdf.set_creator("einvoice-xml tests")
    pdf.set_creation_date(CREATED)
    pdf.set_lang("en")
    pdf.set_xmp_metadata(
        xmp_metadata(
            title="Invoice RE0001", author="Example Software GmbH", creator_tool="einvoice-xml tests", created=CREATED
        )
    )
    pdf.add_page()
    pdf.embed_file(
        bytes=xml,
        basename=parameters.file_name,
        mime_type=parameters.mime_type,
        associated_file_relationship=AssociatedFileRelationship.ALTERNATIVE,
        desc=parameters.description,
        creation_date=CREATED,
        modification_date=CREATED,
    )
    return bytes(pdf.output())


@pytest.mark.parametrize("name", sorted(CATEGORIES))
def test_xml_passes_the_validator(name: str, tmp_path: Path) -> None:
    invoice: Invoice = CATEGORIES[name]
    path = tmp_path / f"{name}.xml"
    path.write_bytes(build_cii(invoice))
    assert _validate(path, 2) == []


def test_pdf_a_3_with_the_einvoice_passes_the_validator(tmp_path: Path) -> None:
    xml = build_cii(CATEGORIES["S"])
    content = _pdf(xml)
    path = tmp_path / "invoice.pdf"
    path.write_bytes(content)
    assert _validate(path, 3) == []
    reading = read(content)
    assert reading.problems == () and reading.invoice is not None and reading.invoice.number == "RE0001"


def test_the_validator_objects_to_a_broken_invoice(tmp_path: Path) -> None:
    # The check of the check: the same XML with a wrong total must not pass.
    path = tmp_path / "broken.xml"
    path.write_bytes(build_cii(CATEGORIES["Z"]).replace(b"<ram:GrandTotalAmount>50.00", b"<ram:GrandTotalAmount>51.00"))
    assert _validate(path, 2) != []
