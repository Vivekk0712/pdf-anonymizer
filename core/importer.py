"""Module for importing and unbundling bulk PDFs and ZIP archives."""

import io
import os
import zipfile
from typing import Dict, List, Tuple, Union
import fitz  # PyMuPDF


def extract_pdfs_from_zip(
    zip_source: Union[bytes, io.BytesIO]
) -> Tuple[Dict[str, bytes], List[str]]:
    """Extracts and validates all PDF files from a ZIP archive.
    
    Handles nested directory structures, eliminates macOS metadata artifacts,
    resolves filename collisions, and verifies PDF file integrity.
    
    Returns:
        Tuple of (extracted_pdfs_dict {filename: bytes}, skipped_or_warning_list)
    """
    if isinstance(zip_source, bytes):
        zip_buffer = io.BytesIO(zip_source)
    else:
        zip_buffer = zip_source

    extracted: Dict[str, bytes] = {}
    skipped: List[str] = []

    try:
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            for info in zf.infolist():
                # Skip directory entries
                if info.is_dir():
                    continue

                raw_filename = info.filename
                # Skip macOS metadata and hidden files
                parts = raw_filename.replace("\\", "/").split("/")
                if any(p.startswith("__MACOSX") or p.startswith(".") for p in parts):
                    continue

                # Only process PDF files
                if not raw_filename.lower().endswith(".pdf"):
                    continue

                try:
                    pdf_bytes = zf.read(info)
                    if len(pdf_bytes) == 0:
                        skipped.append(f"{raw_filename} (empty file)")
                        continue

                    # Validate PDF stream integrity with PyMuPDF
                    test_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    if test_doc.is_encrypted:
                        test_doc.close()
                        skipped.append(f"{raw_filename} (password encrypted PDF)")
                        continue
                    test_doc.close()

                    # Determine clean unique filename
                    base_name = os.path.basename(raw_filename)
                    if not base_name:
                        base_name = "document.pdf"

                    candidate_name = base_name
                    # If duplicate base name across folders, incorporate folder name
                    if candidate_name in extracted:
                        folder_prefix = "_".join(parts[:-1])
                        if folder_prefix:
                            candidate_name = f"{folder_prefix}_{base_name}"

                    # If still duplicate, add incremental suffix
                    counter = 1
                    stem, ext = os.path.splitext(candidate_name)
                    while candidate_name in extracted:
                        candidate_name = f"{stem}_{counter}{ext}"
                        counter += 1

                    extracted[candidate_name] = pdf_bytes

                except Exception as ex:
                    skipped.append(f"{raw_filename} (corrupted: {str(ex)})")

    except zipfile.BadZipFile:
        skipped.append("Uploaded file is not a valid or readable ZIP archive.")

    return extracted, skipped
