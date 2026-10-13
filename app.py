"""Bulk PDF Anonymizer - Streamlit Application
A privacy-focused, layout-preserving tool for removing author identities from research papers.
"""

import io
import re
import streamlit as st
import pandas as pd
from PIL import Image
import fitz  # PyMuPDF

from core.detector import PDFDetector, RedactionTarget
from core.redactor import PDFRedactor, RedactionResult
from core.preview import PreviewGenerator
from core.exporter import BatchExporter
from core.importer import extract_pdfs_from_zip
from tests.test_pipeline import create_synthetic_research_paper


# Configure Page
st.set_page_config(
    page_title="PDF Anonymizer | Double-Blind Review Sanitizer",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern design aesthetics
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        padding: 2.2rem 2.5rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 2rem;
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.2), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    }

    .main-header h1 {
        font-size: 2.3rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        margin: 0;
        background: linear-gradient(90deg, #ffffff 0%, #cbd5e1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .main-header p {
        color: #94a3b8;
        font-size: 1.05rem;
        margin-top: 0.5rem;
        margin-bottom: 1.2rem;
    }

    .badge-container {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .badge {
        display: inline-flex;
        align-items: center;
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.12);
        padding: 0.35rem 0.8rem;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
        color: #e2e8f0;
    }

    .badge-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: #10b981;
        margin-right: 0.45rem;
    }

    .metric-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }

    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px -2px rgba(0, 0, 0, 0.08);
    }

    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.1;
    }

    .metric-label {
        font-size: 0.85rem;
        font-weight: 500;
        color: #64748b;
        margin-top: 0.3rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .preview-box {
        border-radius: 12px;
        border: 1px solid #cbd5e1;
        padding: 0.75rem;
        background: #f8fafc;
    }

    .legend-item {
        display: inline-flex;
        align-items: center;
        font-size: 0.85rem;
        margin-right: 1.2rem;
        font-weight: 500;
        color: #334155;
    }

    .legend-color {
        width: 14px;
        height: 14px;
        border-radius: 3px;
        margin-right: 0.4rem;
        display: inline-block;
    }

    .status-pill {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def initialize_session_state():
    """Initialize Streamlit state storage."""
    if "results" not in st.session_state:
        st.session_state.results = []
    if "uploaded_files_data" not in st.session_state:
        st.session_state.uploaded_files_data = {}  # {filename: bytes}
    if "preview_cache" not in st.session_state:
        st.session_state.preview_cache = {}


initialize_session_state()

# ----------------- SIDEBAR CONTROLS -----------------
with st.sidebar:
    st.markdown("### ⚙️ Sanitization Settings")
    st.markdown(
        "<span style='font-size: 0.85rem; color: #64748b;'>Configure detection rules and redaction depth.</span>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    st.markdown("#### **Scope & Targeting**")
    scope_page1 = st.checkbox(
        "Scope Redactions to Page 1 Only (Recommended)",
        value=True,
        help="Restricts redaction strictly to the first page. Preserves legitimate citations, dataset names, and institutional mentions on Pages 2+.",
    )

    if scope_page1:
        st.caption(
            "🔒 **Safe Mode Active**: Only Page 1 is modified. University names in citations, references, and datasets (e.g. *'Stanford Dogs Dataset'*) on Pages 2+ remain intact."
        )

    st.markdown("#### **Detection Rules**")
    detect_page1 = st.checkbox(
        "Remove First-Page Author Block",
        value=True,
        help="Detects title and abstract boundary; removes authors, institutions, and affiliations between them.",
    )

    detect_footnotes = st.checkbox(
        "Remove Page 1 Correspondence Footnotes",
        value=True,
        help="Removes author affiliation, grant, and correspondence notes in the lower footnote of Page 1.",
    )

    detect_emails = st.checkbox(
        "Remove Email Addresses",
        value=True,
        help="Locates and removes author email addresses.",
    )

    detect_orcid = st.checkbox(
        "Remove ORCID IDs",
        value=True,
        help="Locates and removes ORCID identifiers.",
    )

    detect_affils_all = st.checkbox(
        "Scan Affiliations on All Pages (Unsafe)",
        value=False,
        disabled=scope_page1,
        help="Scans all pages for university and department keywords. Disabled when Page 1 scoping is active to avoid redacting bibliography.",
    )

    custom_keywords_input = st.text_area(
        "Custom Sensitive Keywords",
        value="",
        placeholder="e.g. John Doe, CyberLab, Grant #12345\n(Separated by commas or newlines)",
        help="Additional specific strings, lab names, or author initials to remove wherever found.",
    )

    custom_keywords = [
        k.strip() for k in re.split(r"[\r\n,;]+", custom_keywords_input) if k.strip()
    ]

    if custom_keywords:
        st.caption(
            f"🎯 **{len(custom_keywords)} active keyword(s):** "
            + ", ".join([f"`{k}`" for k in custom_keywords])
        )

    st.markdown("---")
    st.markdown("#### **Document Sanitization**")
    strip_meta = st.checkbox(
        "Scrub PDF Document Metadata",
        value=True,
        help="Clears 'Author', 'Creator', 'Producer', 'Title', and modification timestamps from PDF catalog.",
    )

    remove_annots = st.checkbox(
        "Clear Annotations & Comments",
        value=True,
        help="Deletes any author annotations, sticky notes, or highlight markings in the PDF.",
    )

    preview_dpi = st.slider(
        "Preview Resolution (DPI)",
        min_value=72,
        max_value=200,
        value=130,
        step=10,
        help="Higher DPI provides sharper previews at the expense of slight rendering time.",
    )

    st.markdown("---")
    st.markdown("#### **Quick Actions**")
    if st.button("🧪 Load Sample Research Paper", use_container_width=True):
        sample_pdf_bytes = create_synthetic_research_paper()
        st.session_state.uploaded_files_data["sample_paper_ieee.pdf"] = sample_pdf_bytes
        st.session_state.results = []
        st.session_state.preview_cache = {}
        st.toast("Loaded synthetic IEEE sample paper!", icon="📄")
        st.rerun()

    if st.session_state.uploaded_files_data:
        if st.button("🗑️ Clear All Uploads", use_container_width=True):
            st.session_state.uploaded_files_data = {}
            st.session_state.results = []
            st.session_state.preview_cache = {}
            st.toast("All files cleared.", icon="🧹")
            st.rerun()


# ----------------- MAIN APP HEADER -----------------
st.markdown(
    """
    <div class="main-header">
        <h1>Bulk Research Paper Anonymizer</h1>
        <p>Automated double-blind peer review preparation. Irreversibly strips author blocks, affiliations, emails, and PDF metadata while preserving exact typography and page layout.</p>
        <div class="badge-container">
            <span class="badge"><span class="badge-dot"></span> 100% Local Processing (Private & Offline)</span>
            <span class="badge"><span class="badge-dot"></span> Bulk PDFs & ZIP Archives Supported</span>
            <span class="badge"><span class="badge-dot"></span> True PyMuPDF Destructive Redaction</span>
            <span class="badge"><span class="badge-dot"></span> Layout & Coordinate Preserving</span>
            <span class="badge"><span class="badge-dot"></span> Double-Blind Review Ready</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------- UPLOAD ZONE -----------------
uploaded_files = st.file_uploader(
    "Upload PDFs or ZIP Archive in bulk",
    type=["pdf", "zip"],
    accept_multiple_files=True,
    help="Upload individual PDF research papers or a ZIP archive containing multiple PDFs. Nested folders are automatically unbundled.",
)

# Store newly uploaded files into session state
if uploaded_files:
    newly_added = 0
    for f in uploaded_files:
        fname = f.name
        fbytes = f.read()

        if fname.lower().endswith(".zip"):
            extracted_dict, skipped_list = extract_pdfs_from_zip(fbytes)
            for pdf_name, pdf_data in extracted_dict.items():
                if pdf_name not in st.session_state.uploaded_files_data:
                    st.session_state.uploaded_files_data[pdf_name] = pdf_data
                    newly_added += 1

            if extracted_dict:
                st.toast(f"📦 Unpacked {len(extracted_dict)} PDFs from {fname}!", icon="🎉")
            if skipped_list:
                st.warning(
                    f"⚠️ {len(skipped_list)} item(s) skipped in {fname}: {', '.join(skipped_list[:3])}"
                )

        elif fname.lower().endswith(".pdf"):
            if fname not in st.session_state.uploaded_files_data:
                st.session_state.uploaded_files_data[fname] = fbytes
                newly_added += 1

    if newly_added > 0:
        st.session_state.results = []
        st.session_state.preview_cache = {}

# Staged files viewer
if st.session_state.uploaded_files_data:
    with st.expander(
        f"📁 Staged Documents ({len(st.session_state.uploaded_files_data)} files ready for anonymization)",
        expanded=False,
    ):
        staged_df = pd.DataFrame(
            [
                {
                    "Document Name": name,
                    "File Size": f"{round(len(data) / 1024, 1)} KB",
                    "Format": "PDF Manuscript",
                }
                for name, data in st.session_state.uploaded_files_data.items()
            ]
        )
        st.dataframe(staged_df, use_container_width=True, hide_index=True)

# Track settings signature
current_settings_signature = (
    scope_page1,
    detect_page1,
    detect_footnotes,
    detect_emails,
    detect_orcid,
    detect_affils_all,
    tuple(custom_keywords),
    strip_meta,
    remove_annots,
)

if st.session_state.results and st.session_state.get("applied_settings_signature") != current_settings_signature:
    st.warning(
        "⚠️ **Keywords or settings were updated!** Click **'🚀 Anonymize All Documents'** below to re-process and apply changes."
    )

# Action Bar
col_action1, col_action2, _ = st.columns([2, 2, 4])
with col_action1:
    process_btn = st.button(
        "🚀 Anonymize All Documents",
        type="primary",
        disabled=len(st.session_state.uploaded_files_data) == 0,
        use_container_width=True,
    )

with col_action2:
    if st.session_state.uploaded_files_data:
        st.markdown(
            f"<div style='padding-top: 0.6rem; font-weight: 600; color: #475569;'>📁 {len(st.session_state.uploaded_files_data)} file(s) staged</div>",
            unsafe_allow_html=True,
        )

# ----------------- PROCESSING PIPELINE -----------------
if process_btn and st.session_state.uploaded_files_data:
    detector = PDFDetector(
        scope_to_page1=scope_page1,
        detect_first_page_author_block=detect_page1,
        detect_first_page_footnotes=detect_footnotes,
        detect_emails=detect_emails,
        detect_orcid=detect_orcid,
        detect_affiliations_everywhere=detect_affils_all,
        custom_keywords=custom_keywords,
    )
    redactor = PDFRedactor(
        strip_metadata=strip_meta,
        remove_annotations=remove_annots,
        fill_color=(1.0, 1.0, 1.0),
    )

    results: list[RedactionResult] = []
    progress_bar = st.progress(0, text="Initializing PDF batch processing...")

    total_files = len(st.session_state.uploaded_files_data)
    for idx, (filename, pdf_bytes) in enumerate(st.session_state.uploaded_files_data.items()):
        progress_bar.progress(
            (idx) / total_files,
            text=f"Sanitizing ({idx + 1}/{total_files}): {filename}...",
        )

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            targets = detector.detect_all(doc)
            result = redactor.redact_document(doc, targets, filename=filename)
            results.append(result)
            doc.close()
        except Exception as e:
            st.error(f"Error processing {filename}: {str(e)}")

    progress_bar.progress(1.0, text="Sanitization complete!")
    st.session_state.results = results
    st.session_state.applied_settings_signature = current_settings_signature
    st.session_state.preview_cache = {}  # Invalidate preview cache
    st.toast("Batch sanitization finished successfully!", icon="✅")

# ----------------- RESULTS & DASHBOARD -----------------
if st.session_state.results:
    total_docs = len(st.session_state.results)
    total_redactions = sum(r.targets_count for r in st.session_state.results)
    verified_clean_count = sum(1 for r in st.session_state.results if r.is_verified_clean)
    clean_pct = int((verified_clean_count / total_docs) * 100) if total_docs > 0 else 100

    st.markdown("### 📊 Batch Overview")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)

    with m_col1:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-value">{total_docs}</div>
                <div class="metric-label">Documents Processed</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with m_col2:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-value">{total_redactions}</div>
                <div class="metric-label">Identities Redacted</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with m_col3:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-value">{clean_pct}%</div>
                <div class="metric-label">Verification Rate</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with m_col4:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-value">{'Yes' if strip_meta else 'No'}</div>
                <div class="metric-label">Metadata Scrubbed</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Tabs for Inspection, Audit Log, and Downloads
    tab_preview, tab_audit, tab_download = st.tabs(
        ["🔍 Side-by-Side Visual Preview", "📋 Audit & Processing Log", "📦 Download Station"]
    )

    # --- TAB 1: VISUAL PREVIEW ---
    with tab_preview:
        st.markdown("#### Side-by-Side Visual Comparison")
        st.markdown(
            """
            <div style="margin-bottom: 1rem;">
                <span class="legend-item"><span class="legend-color" style="background:#ef4444;"></span> First-Page Author Block</span>
                <span class="legend-item"><span class="legend-color" style="background:#a855f7;"></span> Page 1 Footnotes</span>
                <span class="legend-item"><span class="legend-color" style="background:#3b82f6;"></span> Email Addresses</span>
                <span class="legend-item"><span class="legend-color" style="background:#10b981;"></span> ORCID Identifiers</span>
                <span class="legend-item"><span class="legend-color" style="background:#f59e0b;"></span> Affiliations / Keywords</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        doc_names = [r.filename for r in st.session_state.results]
        col_select1, col_select2 = st.columns([3, 1])
        with col_select1:
            selected_file = st.selectbox("Select document to inspect:", doc_names, index=0)

        # Get result for chosen file
        selected_res = next(r for r in st.session_state.results if r.filename == selected_file)
        orig_bytes = st.session_state.uploaded_files_data[selected_file]

        with col_select2:
            max_pages = max(1, selected_res.original_page_count)
            page_idx = st.number_input("Page #", min_value=1, max_value=max_pages, value=1, step=1) - 1

        # Check cache or render
        cache_key = f"{selected_file}_{page_idx}_{preview_dpi}"
        if cache_key not in st.session_state.preview_cache:
            with st.spinner("Rendering high-resolution page comparison..."):
                preview_gen = PreviewGenerator(dpi=preview_dpi)
                targets_for_file = [
                    RedactionTarget(
                        page_num=item["page_num"],
                        bbox=tuple(item["bbox"]),
                        text=item["text"],
                        reason=item["reason"],
                        category=item["category"],
                    )
                    for item in selected_res.redacted_items
                ]
                overlay_img, clean_img = preview_gen.generate_side_by_side_previews(
                    orig_bytes,
                    targets_for_file,
                    selected_res.output_pdf_bytes,
                    page_num=page_idx,
                )
                st.session_state.preview_cache[cache_key] = (overlay_img, clean_img)

        overlay_img, clean_img = st.session_state.preview_cache[cache_key]

        col_orig, col_clean = st.columns(2)
        with col_orig:
            st.markdown("##### 🔴 Original (Detected Redaction Boundaries)")
            st.image(overlay_img, use_container_width=True)

        with col_clean:
            st.markdown("##### ⚪ Anonymized (Destructive Whitespace Fill)")
            st.image(clean_img, use_container_width=True)

    # --- TAB 2: AUDIT & PROCESSING LOG ---
    with tab_audit:
        st.markdown("#### Document Processing Audit Summary")
        summary_df = BatchExporter.create_summary_dataframe(st.session_state.results)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        st.markdown("#### Detailed Redaction Findings")
        for res in st.session_state.results:
            with st.expander(f"📄 {res.filename} ({res.targets_count} redacted elements)"):
                if res.redacted_items:
                    detail_df = pd.DataFrame(
                        [
                            {
                                "Page": item["page_num"] + 1,
                                "Category": item["category"].replace("_", " ").title(),
                                "Reason": item["reason"],
                                "Identified Text": item["text"],
                                "Coordinates (x0, y0, x1, y1)": f"({item['bbox'][0]:.1f}, {item['bbox'][1]:.1f}, {item['bbox'][2]:.1f}, {item['bbox'][3]:.1f})",
                            }
                            for item in res.redacted_items
                        ]
                    )
                    st.dataframe(detail_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No author or affiliation patterns detected on this document.")

    # --- TAB 3: DOWNLOAD STATION ---
    with tab_download:
        st.markdown("#### Export Sanitized Research Papers")

        # ZIP Package
        zip_bytes = BatchExporter.create_zip_archive(st.session_state.results, include_audit_report=True)

        st.download_button(
            label="📦 Download All Anonymized PDFs + Audit Report (.zip)",
            data=zip_bytes,
            file_name="anonymized_research_papers.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )

        st.markdown("---")
        st.markdown("##### Individual Document Downloads")

        for res in st.session_state.results:
            d_col1, d_col2 = st.columns([3, 1])
            with d_col1:
                st.markdown(
                    f"**`anonymized_{res.filename}`** &nbsp;·&nbsp; "
                    f"<span style='color: #64748b; font-size: 0.85rem;'>{res.targets_count} redactions applied · {len(res.output_pdf_bytes) // 1024} KB</span>",
                    unsafe_allow_html=True,
                )
            with d_col2:
                st.download_button(
                    label=f"⬇️ Download PDF",
                    data=res.output_pdf_bytes,
                    file_name=f"anonymized_{res.filename}",
                    mime="application/pdf",
                    key=f"dl_{res.filename}",
                    use_container_width=True,
                )

elif not st.session_state.uploaded_files_data:
    st.info("👆 Upload research paper PDFs above, or click **Load Sample Research Paper** in the sidebar to test.")
