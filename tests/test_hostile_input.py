"""Hostile input: nothing but a Reading comes out of read(), nothing but the library's error
out of the other parsers, and neither takes long or reaches outside."""

from __future__ import annotations

import builtins
import io
import socket
import tracemalloc
from pathlib import Path

import incoming as f
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject

from einvoice_xml import (
    MAX_EMBEDDED_FILES,
    MAX_PDF_BYTES,
    MAX_XML_BYTES,
    EInvoiceError,
    LimitExceededError,
    ReadError,
    Reading,
    invoice_xml_root,
    parse_invoice_xml,
    read,
)

LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">
<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;"><!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">]>
<x>&e;</x>"""
EXTERNAL = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY file SYSTEM "file:///etc/passwd">]><x>&file;</x>"""
EXTERNAL_DTD = b"""<?xml version="1.0"?><!DOCTYPE x SYSTEM "http://example.invalid/x.dtd"><x/>"""


@pytest.mark.parametrize("data", [LAUGHS, EXTERNAL, EXTERNAL_DTD], ids=["laughs", "external-entity", "external-dtd"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_dtds_are_refused_in_every_encoding(data: bytes, encoding: str) -> None:
    content = data.decode().replace('version="1.0"?>', f'version="1.0" encoding="{encoding}"?>').encode(encoding)
    reading = read(content)
    assert reading.invoice is None and "DTD" in reading.problems[0]
    with pytest.raises(ReadError, match="DTD"):
        parse_invoice_xml(content, embedded=False)


def test_a_dtd_is_refused_inside_a_pdf() -> None:
    reading = read(f.pdf({"factur-x.xml": LAUGHS}))
    assert reading.invoice is None and "DTD" in reading.problems[0]


def test_deep_nesting() -> None:
    depth = 200_000
    content = b"<a>" * depth + b"</a>" * depth
    assert read(content).invoice is None
    assert invoice_xml_root(content) is None


def test_the_xml_limit() -> None:
    content = f.cii().replace(b"<rsm:ExchangedDocument>", b" " * MAX_XML_BYTES + b"<rsm:ExchangedDocument>")
    with pytest.raises(LimitExceededError):
        parse_invoice_xml(content, embedded=False)
    assert "larger than" in read(content).problems[0]


def test_the_xml_limit_inside_a_pdf() -> None:
    content = f.pdf({"factur-x.xml": b" " * MAX_XML_BYTES + f.cii()})
    assert "larger than" in read(content).problems[0]


def _compressed_pdf(attachments: dict[str, bytes]) -> bytes:
    """A PDF whose embedded files are Flate streams; ``f.pdf`` stores them as they are."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    for name, content in attachments.items():
        reference = writer.add_attachment(name, content).pdf_object["/EF"].raw_get("/F")
        writer._replace_object(reference, reference.get_object().flate_encode())
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_an_oversized_compressed_attachment_is_refused() -> None:
    content = _compressed_pdf({"factur-x.xml": b" " * (MAX_XML_BYTES + 1)})
    assert len(content) < MAX_XML_BYTES // 100
    reading = read(content)
    assert reading.invoice is None and "larger than" in reading.problems[0]


def test_an_oversized_attachment_leaves_the_invoice_next_to_it() -> None:
    reading = read(_compressed_pdf({"other.xml": b" " * (MAX_XML_BYTES + 1), "factur-x.xml": f.cii()}))
    assert reading.has_amounts and reading.problems == ()


def test_compressed_attachments_do_not_add_up_in_memory() -> None:
    size = MAX_XML_BYTES + 1
    files = {f"{index}.xml": bytes([index]) * size for index in range(MAX_EMBEDDED_FILES)}
    content = _compressed_pdf(files)
    del files
    tracemalloc.start()
    try:
        reading = read(content)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert reading.invoice is None and "larger than" in reading.problems[0]
    assert peak < 3 * size


def test_the_pdf_limit() -> None:
    content = f.pdf() + b"\n" * MAX_PDF_BYTES
    assert "larger than" in read(content).problems[0]


def test_the_limit_of_embedded_files() -> None:
    files = {f"{index}.txt": b"x" for index in range(MAX_EMBEDDED_FILES)}
    assert "no embedded" in read(f.pdf(files)).problems[0]
    files["one-more.txt"] = b"x"
    assert "more than" in read(f.pdf(files)).problems[0]


def test_a_cycle_in_the_name_tree_of_the_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    node = writer._add_object(DictionaryObject())
    node.get_object()[NameObject("/Kids")] = ArrayObject([node])
    names = DictionaryObject({NameObject("/EmbeddedFiles"): node})
    writer._root_object[NameObject("/Names")] = names
    buffer = io.BytesIO()
    writer.write(buffer)
    assert read(buffer.getvalue()).invoice is None


def test_big_numbers_cannot_reach_the_arithmetic() -> None:
    reading = read(f.cii(net="9" * 1000, tax="9" * 1000))
    assert reading.invoice is None and "not a number" in reading.problems[0]


def test_the_sum_of_the_totals_is_exact_for_the_longest_numbers() -> None:
    net, tax = "1" + "0" * 30, "0.000000000000000000000000001"
    assert "do not add up" in read(f.cii(net=net, tax=tax, gross=net)).problems[0]


def test_values_of_the_input_in_a_message_are_bounded() -> None:
    reading = read(f.cii(net="x" * 100_000))
    assert len(reading.problems[0]) < 200


def test_read_reaches_neither_network_nor_files(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no I/O in the library")

    content = f.zugferd_pdf()
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(Path, "open", refuse)
    assert read(content).has_amounts
    assert read(EXTERNAL).invoice is None


def _safe(content: bytes) -> None:
    reading = read(content)
    assert isinstance(reading, Reading)
    assert reading.invoice is not None or reading.problems
    try:
        parse_invoice_xml(content, embedded=False)
    except EInvoiceError:
        pass
    invoice_xml_root(content)


def _mutated(base: bytes) -> st.SearchStrategy[bytes]:
    edits = st.lists(
        st.tuples(st.integers(0, len(base) - 1), st.integers(0, 64), st.binary(max_size=32)), min_size=1, max_size=8
    )

    def apply(steps: list[tuple[int, int, bytes]]) -> bytes:
        content = base
        for position, length, replacement in steps:
            content = content[:position] + replacement + content[position + length :]
        return content

    return edits.map(apply)


@given(st.binary(max_size=2048))
def test_random_bytes(content: bytes) -> None:
    _safe(content)


@given(st.binary(max_size=512))
def test_random_bytes_behind_a_pdf_header(content: bytes) -> None:
    _safe(b"%PDF-1.7\n" + content)


@given(st.binary(max_size=512))
def test_random_bytes_behind_an_xml_start(content: bytes) -> None:
    _safe(b"<?xml version='1.0'?><a>" + content)


@given(_mutated(f.cii(payment_means=[("58", f.PAYEE_IBAN, "A", "B")], taxes=[("S", "19", "100.00", "19.00")])))
def test_mutated_cii(content: bytes) -> None:
    _safe(content)


@given(_mutated(f.ubl(payment_means=[("58", f.PAYEE_IBAN, "A", "B")], taxes=[("S", "19", "250.00", "47.50")])))
def test_mutated_ubl(content: bytes) -> None:
    _safe(content)


@given(_mutated(f.zugferd_pdf()))
def test_mutated_pdf(content: bytes) -> None:
    _safe(content)


@given(st.text(max_size=40))
def test_any_text_in_any_field(value: str) -> None:
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace("\x00", "")
    for field in ("number", "issued", "due", "net", "tax", "gross", "currency"):
        try:
            content = f.cii(**{field: escaped})
        except UnicodeEncodeError:
            return
        _safe(content)
