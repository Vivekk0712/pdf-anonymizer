"""Automated tests for Bulk PDF Anonymizer detection and redaction engine."""

import io
import zipfile
import fitz
import pytest
from core.detector import PDFDetector
from core.redactor import PDFRedactor
from core.preview import PreviewGenerator
from core.exporter import BatchExporter
from core.importer import extract_pdfs_from_zip


def create_synthetic_research_paper() -> bytes:
    """Creates a sample multi-page synthetic research paper with title, authors, affiliations, emails, and abstract."""
    doc = fitz.open()

    # Page 1
    page1 = doc.new_page(width=612, height=792)  # Standard Letter size

    # Running header (small font, near top)
    page1.insert_text((50, 40), "IEEE TRANSACTIONS ON KNOWLEDGE AND DATA ENGINEERING, VOL. 34, 2026", fontsize=8.5)

    # Title (prominent font, y ~ 90)
    page1.insert_text(
        (50, 100),
        "Privacy-Preserving Data Sanitization in Peer Review Workflows",
        fontsize=18,
        fontname="helv",
    )

    # Author Names (y ~ 140)
    page1.insert_text(
        (50, 140),
        "Dr. Alice Johnson, Prof. Bob Smith, and Dr. Charlie Davis",
        fontsize=11,
    )

    # Affiliations & Departments (y ~ 160)
    page1.insert_text(
        (50, 160),
        "Department of Computer Science, University of California, Berkeley",
        fontsize=9.5,
    )
    page1.insert_text(
        (50, 175),
        "Faculty of Information Technology, Stanford University",
        fontsize=9.5,
    )

    # Emails and ORCID (y ~ 195)
    page1.insert_text(
        (50, 195),
        "Emails: alice.j@berkeley.edu, bob.smith@stanford.edu | ORCID: 0000-0002-1825-0097",
        fontsize=9,
    )

    # Abstract Header & Content (y ~ 240) - MUST BE PRESERVED!
    page1.insert_text((50, 245), "Abstract", fontsize=12, fontname="helv")
    abstract_text = (
        "Double-blind peer review is standard in top-tier conferences. "
        "However, manual redaction of author identities is error-prone. "
        "This paper proposes automated layout-aware PDF sanitization."
    )
    page1.insert_textbox(fitz.Rect(50, 260, 560, 320), abstract_text, fontsize=10)

    # Section 1 Introduction
    page1.insert_text((50, 340), "1. Introduction", fontsize=13, fontname="helv")
    intro_text = (
        "Sanitizing scientific publications requires stripping author details while leaving "
        "the document visual layout unchanged for reviewers."
    )
    page1.insert_textbox(fitz.Rect(50, 355, 560, 420), intro_text, fontsize=10)

    # Page 1 Footnote / Author Correspondence note (y ~ 730)
    page1.insert_text(
        (50, 740),
        "*Corresponding author: Alice Johnson (alice.j@berkeley.edu). Manuscript received May 2026.",
        fontsize=8,
    )

    # Page 2 (Body, Related Work, Citations to other Universities & Datasets)
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((50, 60), "2. Methodology & Related Work", fontsize=14, fontname="helv")
    page2.insert_text(
        (50, 90),
        "Prior work by researchers at Harvard University and MIT showed baseline techniques.",
        fontsize=10,
    )
    page2.insert_text(
        (50, 110),
        "We evaluated our model on the Stanford Dogs and Oxford Flowers benchmark datasets.",
        fontsize=10,
    )
    page2.insert_text(
        (50, 130),
        "Reference [1]: J. Doe, Univ. of Cambridge, 'Benchmark datasets', contact: dataset@mit.edu",
        fontsize=10,
    )

    # Set metadata with identifying details
    doc.set_metadata({
        "title": "Privacy-Preserving Data Sanitization",
        "author": "Dr. Alice Johnson and Prof. Bob Smith",
        "creator": "LaTeX with hyperref",
        "producer": "pdfTeX-1.40.21",
    })

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_detector_finds_page1_author_block_and_footnote():
    pdf_bytes = create_synthetic_research_paper()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Safe Page 1 Scoping (default)
    detector = PDFDetector(scope_to_page1=True)
    targets = detector.detect_all(doc)

    assert len(targets) > 0, "Detector should find redaction targets"

    # All targets must be on page 0 when scoped to Page 1
    assert all(t.page_num == 0 for t in targets), "All targets should be on Page 1 when scoped to Page 1"

    p0_texts = " ".join(t.text for t in targets)
    assert "Alice Johnson" in p0_texts or "Department" in p0_texts, "Should identify author block"
    assert "berkeley.edu" in p0_texts, "Should detect author email"
    assert "Corresponding author" in p0_texts or any(t.category == "footnote" for t in targets), "Should detect correspondence footnote"

    # Ensure Abstract itself is NOT marked for redaction
    for t in targets:
        assert "Double-blind peer review" not in t.text, "Abstract text must not be targeted"
        assert t.text.strip().lower() != "abstract", "Abstract header must not be targeted"

    doc.close()


def test_page1_scoping_protects_body_citations_and_datasets():
    """Validates that university names, citations, and dataset names on Page 2 remain strictly intact."""
    pdf_bytes = create_synthetic_research_paper()
    orig_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Safe default: scope_to_page1 = True
    detector = PDFDetector(scope_to_page1=True)
    targets = detector.detect_all(orig_doc)

    redactor = PDFRedactor(strip_metadata=True)
    result = redactor.redact_document(orig_doc, targets, filename="paper_scoped.pdf")

    clean_doc = fitz.open(stream=result.output_pdf_bytes, filetype="pdf")

    # Page 1 authors must be stripped
    p1_text = clean_doc[0].get_text()
    assert "Alice Johnson" not in p1_text
    assert "alice.j@berkeley.edu" not in p1_text
    assert "Stanford University" not in p1_text  # removed from author affiliation on page 1

    # Page 2 MUST PRESERVE citations, Harvard, MIT, Stanford Dogs, and dataset references!
    p2_text = clean_doc[1].get_text()
    assert "Harvard University" in p2_text, "Page 2 university mention must be preserved"
    assert "MIT" in p2_text, "Page 2 MIT mention must be preserved"
    assert "Stanford Dogs" in p2_text, "Page 2 benchmark dataset name must be preserved"
    assert "Univ. of Cambridge" in p2_text, "Page 2 citation must be preserved"
    assert "dataset@mit.edu" in p2_text, "Page 2 citation email must be preserved when scoped to Page 1"

    clean_doc.close()


def test_redactor_and_metadata_sanitization():
    pdf_bytes = create_synthetic_research_paper()
    orig_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    orig_metadata = orig_doc.metadata
    assert orig_metadata["author"] == "Dr. Alice Johnson and Prof. Bob Smith"

    detector = PDFDetector(scope_to_page1=True)
    targets = detector.detect_all(orig_doc)

    redactor = PDFRedactor(strip_metadata=True)
    result = redactor.redact_document(orig_doc, targets, filename="paper1.pdf")

    assert result.targets_count > 0
    assert result.metadata_stripped is True
    assert result.is_verified_clean is True

    # Re-open redacted PDF and inspect
    clean_doc = fitz.open(stream=result.output_pdf_bytes, filetype="pdf")

    # Verify metadata is stripped
    assert clean_doc.metadata.get("author") in ("", None)

    # Verify author text is physically gone from page 0
    clean_p0_text = clean_doc[0].get_text()
    assert "Alice Johnson" not in clean_p0_text, "Author name must be physically removed"
    assert "bob.smith@stanford.edu" not in clean_p0_text, "Email must be physically removed"

    # Verify Abstract and Title are still intact
    assert "Privacy-Preserving Data Sanitization" in clean_p0_text, "Title must remain intact"
    assert "Double-blind peer review" in clean_p0_text, "Abstract body must remain intact"

    clean_doc.close()


def test_preview_and_exporter():
    pdf_bytes = create_synthetic_research_paper()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    detector = PDFDetector(scope_to_page1=True)
    targets = detector.detect_all(doc)
    redactor = PDFRedactor()
    result = redactor.redact_document(doc, targets, filename="sample.pdf")

    # Preview generation
    preview_gen = PreviewGenerator(dpi=100)
    overlay_img, redacted_img = preview_gen.generate_side_by_side_previews(
        pdf_bytes, targets, result.output_pdf_bytes, page_num=0
    )
    assert overlay_img.size[0] > 0
    assert redacted_img.size[0] > 0

    # Batch export to ZIP
    zip_bytes = BatchExporter.create_zip_archive([result], include_audit_report=True)
    assert len(zip_bytes) > 0

    # Inspect zip contents
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        assert "anonymized_sample.pdf" in namelist
        assert "anonymization_audit_report.csv" in namelist
        assert "audit_log_detailed.json" in namelist


def test_extract_pdfs_from_zip():
    """Validates unbundling PDFs from a ZIP archive with nested folders and metadata files."""
    pdf_bytes = create_synthetic_research_paper()

    # Create synthetic zip archive
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("conference_papers/track_a/paper_01.pdf", pdf_bytes)
        zf.writestr("conference_papers/track_b/paper_02.pdf", pdf_bytes)
        zf.writestr("readme.txt", "Instructions for authors.")
        zf.writestr("__MACOSX/._paper_01.pdf", b"fake-mac-resource-fork")

    zip_bytes = zip_buf.getvalue()

    extracted, skipped = extract_pdfs_from_zip(zip_bytes)

    assert len(extracted) == 2, f"Should extract exactly 2 PDFs, got {len(extracted)}"
    assert any("paper_01.pdf" in k for k in extracted.keys())
    assert any("paper_02.pdf" in k for k in extracted.keys())
    # Ensure macOS and txt files were not added to extracted dict
    assert not any(k.endswith(".txt") for k in extracted.keys())
    assert not any("__MACOSX" in k for k in extracted.keys())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

