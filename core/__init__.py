"""Core package for Multi-Format Bulk Anonymizer (PDF, DOCX, TXT)."""

from core.detector import PDFDetector, RedactionTarget
from core.redactor import PDFRedactor, RedactionResult
from core.preview import PreviewGenerator
from core.exporter import BatchExporter
from core.importer import extract_documents_from_zip, extract_pdfs_from_zip
from core.docx_handler import DOCXDetector, DOCXRedactor
from core.txt_handler import TXTDetector, TXTRedactor

__all__ = [
    "PDFDetector",
    "PDFRedactor",
    "RedactionTarget",
    "RedactionResult",
    "PreviewGenerator",
    "BatchExporter",
    "extract_documents_from_zip",
    "extract_pdfs_from_zip",
    "DOCXDetector",
    "DOCXRedactor",
    "TXTDetector",
    "TXTRedactor",
]
