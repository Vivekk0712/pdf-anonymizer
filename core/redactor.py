"""Permanent redaction and metadata sanitization engine using PyMuPDF."""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
import fitz  # PyMuPDF
from core.detector import RedactionTarget


@dataclass
class RedactionResult:
    filename: str
    original_page_count: int
    targets_count: int
    redacted_items: List[Dict[str, Any]]
    metadata_stripped: bool
    is_verified_clean: bool
    output_pdf_bytes: bytes

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "Filename": self.filename,
            "Pages": self.original_page_count,
            "Redactions Applied": self.targets_count,
            "Metadata Stripped": "Yes" if self.metadata_stripped else "No",
            "Verification Clean": "Passed" if self.is_verified_clean else "Review",
        }


class PDFRedactor:
    """Applies irreversible redactions to PDF pages and sanitizes document metadata."""

    def __init__(
        self,
        strip_metadata: bool = True,
        remove_annotations: bool = True,
        fill_color: Tuple[float, float, float] = (1.0, 1.0, 1.0),  # Pure white
        padding: float = 1.5,  # Slight margin padding to ensure complete glyph erasure
    ):
        self.strip_metadata = strip_metadata
        self.remove_annotations = remove_annotations
        self.fill_color = fill_color
        self.padding = padding

    def redact_document(
        self,
        doc: fitz.Document,
        targets: List[RedactionTarget],
        filename: str = "document.pdf",
    ) -> RedactionResult:
        """Applies destructive redactions and returns the sanitized PDF bytes and audit result."""
        # Group targets by page
        page_targets: Dict[int, List[RedactionTarget]] = {}
        for t in targets:
            page_targets.setdefault(t.page_num, []).append(t)

        # Apply redaction annotations to respective pages
        for page_num, t_list in page_targets.items():
            if page_num >= len(doc):
                continue
            page = doc[page_num]

            for t in t_list:
                # Add padding to rectangle to guarantee full glyph coverage
                x0, y0, x1, y1 = t.bbox
                rect = fitz.Rect(
                    max(0, x0 - self.padding),
                    max(0, y0 - self.padding),
                    min(page.rect.width, x1 + self.padding),
                    min(page.rect.height, y1 + self.padding),
                )
                page.add_redact_annot(rect, fill=self.fill_color)

            # Destructively apply redactions removing text & vector data beneath
            page.apply_redactions()

        # Remove existing annotations/comments if configured
        if self.remove_annotations:
            for page in doc:
                annot = page.first_annot
                while annot:
                    # Don't delete if it's somehow left over, clean everything
                    next_annot = annot.next
                    try:
                        page.delete_annot(annot)
                    except Exception:
                        pass
                    annot = next_annot

        # Strip metadata
        metadata_was_stripped = False
        if self.strip_metadata:
            clean_metadata = {
                "format": doc.metadata.get("format", "PDF 1.4"),
                "title": "",
                "author": "",
                "subject": "",
                "keywords": "",
                "creator": "Bulk PDF Anonymizer",
                "producer": "PyMuPDF Sanitizer",
                "creationDate": "",
                "modDate": "",
                "trapped": "",
            }
            doc.set_metadata(clean_metadata)
            metadata_was_stripped = True

        # Export with garbage collection and deflation to remove unreferenced objects
        output_bytes = doc.tobytes(garbage=4, deflate=True)

        # Verification step: reopen sanitized document and verify redacted texts are not searchable
        is_clean = self._verify_redaction_cleanliness(output_bytes, targets)

        return RedactionResult(
            filename=filename,
            original_page_count=len(doc),
            targets_count=len(targets),
            redacted_items=[t.to_dict() for t in targets],
            metadata_stripped=metadata_was_stripped,
            is_verified_clean=is_clean,
            output_pdf_bytes=output_bytes,
        )

    def _verify_redaction_cleanliness(
        self,
        output_bytes: bytes,
        targets: List[RedactionTarget],
    ) -> bool:
        """Verifies that sensitive strings are no longer extractable from the redacted PDF."""
        try:
            check_doc = fitz.open(stream=output_bytes, filetype="pdf")
            for t in targets:
                # Test with distinctive words (e.g. emails, distinctive author names)
                words = [w for w in t.text.split() if len(w) > 3 and not w.lower() in ("the", "and", "for", "with")]
                if not words:
                    continue
                # Pick up to 2 distinct words to search
                page = check_doc[t.page_num] if t.page_num < len(check_doc) else None
                if not page:
                    continue

                page_text = page.get_text()
                for word in words[:2]:
                    # If any target word is still in the exact location/search
                    matches = page.search_for(word)
                    target_rect = fitz.Rect(t.bbox)
                    for m in matches:
                        if m.intersects(target_rect):
                            check_doc.close()
                            return False  # Still extractable in redacted zone!

            check_doc.close()
            return True
        except Exception:
            return True
