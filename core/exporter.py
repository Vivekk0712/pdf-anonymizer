"""Batch export and audit report generator."""

import io
import zipfile
import json
from datetime import datetime
from typing import List, Dict, Any
import pandas as pd
from core.redactor import RedactionResult


class BatchExporter:
    """Handles packaging anonymized PDFs into a ZIP archive and building audit logs."""

    @staticmethod
    def create_zip_archive(results: List[RedactionResult], include_audit_report: bool = True) -> bytes:
        """Packages all processed PDFs and an optional audit summary CSV into a single ZIP in memory."""
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for res in results:
                # Add sanitized PDF
                out_name = f"anonymized_{res.filename}"
                zf.writestr(out_name, res.output_pdf_bytes)

            if include_audit_report and results:
                # Create CSV report
                summary_records = [res.to_summary_dict() for res in results]
                df = pd.DataFrame(summary_records)
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                zf.writestr("anonymization_audit_report.csv", csv_bytes)

                # Create detailed JSON log
                detailed_records = [
                    {
                        "filename": r.filename,
                        "pages": r.original_page_count,
                        "redactions_count": r.targets_count,
                        "verified_clean": r.is_verified_clean,
                        "metadata_stripped": r.metadata_stripped,
                        "details": r.redacted_items,
                    }
                    for r in results
                ]
                json_bytes = json.dumps(
                    {
                        "generated_at": datetime.now().isoformat(),
                        "total_documents": len(results),
                        "documents": detailed_records,
                    },
                    indent=2,
                ).encode("utf-8")
                zf.writestr("audit_log_detailed.json", json_bytes)

        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    @staticmethod
    def create_summary_dataframe(results: List[RedactionResult]) -> pd.DataFrame:
        """Creates a pandas DataFrame summarizing the batch run for UI display."""
        if not results:
            return pd.DataFrame()
        return pd.DataFrame([res.to_summary_dict() for res in results])
