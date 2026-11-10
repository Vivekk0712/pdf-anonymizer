"""Module for importing and unbundling bulk PDFs, Word (.docx), TXT files, and ZIP archives."""

import io
import os
import zipfile
from typing import Dict, List, Optional, Set, Tuple, Union
import fitz  # PyMuPDF
import docx  # python-docx

DEFAULT_ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}


def extract_documents_from_zip(
    zip_source: Union[bytes, io.BytesIO],
    allowed_extensions: Optional[Set[str]] = None,
) -> Tuple[Dict[str, bytes], List[str]]:
    """Extracts and validates document files (PDF, DOCX, TXT) from a ZIP archive.
    
    Handles nested directory structures, eliminates macOS metadata artifacts,
    resolves filename collisions, and validates file integrity.
    
    Returns:
        Tuple of (extracted_docs_dict {filename: bytes}, skipped_or_warning_list)
    """
    if allowed_extensions is None:
        allowed_extensions = DEFAULT_ALLOWED_EXTENSIONS
    else:
        allowed_extensions = {ext.lower().lstrip(".") for ext in allowed_extensions}

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

                ext = os.path.splitext(raw_filename)[1].lower().lstrip(".")
                if ext not in allowed_extensions:
                    continue

                try:
                    file_bytes = zf.read(info)
                    if len(file_bytes) == 0:
                        skipped.append(f"{raw_filename} (empty file)")
                        continue

                    # Validate integrity based on file type
                    if ext == "pdf":
                        test_doc = fitz.open(stream=file_bytes, filetype="pdf")
                        if test_doc.is_encrypted:
                            test_doc.close()
                            skipped.append(f"{raw_filename} (password encrypted PDF)")
                            continue
                        test_doc.close()
                    elif ext == "docx":
                        # Validate Word document structure
                        _ = docx.Document(io.BytesIO(file_bytes))
                    elif ext == "txt":
                        # Validate text decoding
                        try:
                            _ = file_bytes.decode("utf-8")
                        except UnicodeDecodeError:
                            _ = file_bytes.decode("latin-1")

                    # Determine clean unique filename
                    base_name = os.path.basename(raw_filename)
                    if not base_name:
                        base_name = f"document.{ext}"

                    candidate_name = base_name
                    # If duplicate base name across folders, incorporate folder name
                    if candidate_name in extracted:
                        folder_prefix = "_".join(parts[:-1])
                        if folder_prefix:
                            candidate_name = f"{folder_prefix}_{base_name}"

                    # If still duplicate, add incremental suffix
                    counter = 1
                    stem, orig_ext = os.path.splitext(candidate_name)
                    while candidate_name in extracted:
                        candidate_name = f"{stem}_{counter}{orig_ext}"
                        counter += 1

                    extracted[candidate_name] = file_bytes

                except Exception as ex:
                    skipped.append(f"{raw_filename} (corrupted: {str(ex)})")

    except zipfile.BadZipFile:
        skipped.append("Uploaded file is not a valid or readable ZIP archive.")

    return extracted, skipped


def extract_pdfs_from_zip(
    zip_source: Union[bytes, io.BytesIO]
) -> Tuple[Dict[str, bytes], List[str]]:
    """Backward-compatible extraction for PDF-only archives."""
    return extract_documents_from_zip(zip_source, allowed_extensions={"pdf"})
