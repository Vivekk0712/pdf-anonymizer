"""Bulk PDF, Word (.docx) & Plain Text (.txt) Anonymizer - Streamlit Application
A privacy-focused, layout-preserving tool for removing author identities from research papers.
"""

import io
import re
import html
import base64
import difflib
from typing import List, Dict, Any, Optional
import streamlit as st
import pandas as pd
from PIL import Image
import fitz  # PyMuPDF
import docx

from core.detector import PDFDetector, RedactionTarget
from core.redactor import PDFRedactor, RedactionResult
from core.preview import PreviewGenerator
from core.exporter import BatchExporter
from core.importer import extract_documents_from_zip, extract_pdfs_from_zip
from core.docx_handler import DOCXDetector, DOCXRedactor
from core.txt_handler import TXTDetector, TXTRedactor
from tests.test_pipeline import (
    create_synthetic_research_paper,
    create_synthetic_docx_paper,
    create_synthetic_txt_paper,
)


# Configure Page
st.set_page_config(
    page_title="PDF & Document Anonymizer | Double-Blind Review Sanitizer",
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
    </style>
    """,
    unsafe_allow_html=True,
)


def highlight_text_targets(raw_text: str, targets: List[RedactionTarget]) -> str:
    """Escapes raw text and highlights detected targets for web preview."""
    escaped = html.escape(raw_text)
    # Target strings sorted by length descending to prevent substring collisions
    target_strings = sorted(list({t.text.strip() for t in targets if t.text.strip()}), key=len, reverse=True)
    for ts in target_strings:
        if len(ts) < 2:
            continue
        ts_escaped = html.escape(ts)
        escaped = re.sub(
            re.escape(ts_escaped),
            r"<mark style='background-color: #fecaca; color: #991b1b; padding: 2px 4px; border-radius: 4px; font-weight: 600;'>\g<0></mark>",
            escaped,
            flags=re.IGNORECASE,
        )
    return escaped


def pil_to_base64_png(img: Image.Image) -> str:
    """Converts a PIL Image to a Base64-encoded PNG data string."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def generate_html_diff(orig_text: str, anon_text: str) -> str:
    """Generates an HTML unified line diff highlighting deletions and preserved lines."""
    orig_lines = (orig_text or "").splitlines()
    anon_lines = (anon_text or "").splitlines()
    diff = list(difflib.ndiff(orig_lines, anon_lines))

    html_lines = []
    for line in diff:
        if line.startswith("- "):
            content = html.escape(line[2:])
            html_lines.append(
                f"<div style='background-color: #fee2e2; color: #991b1b; padding: 3px 8px; border-left: 3px solid #ef4444; margin: 2px 0; border-radius: 2px;'><strong>- </strong>{content}</div>"
            )
        elif line.startswith("+ "):
            content = html.escape(line[2:])
            html_lines.append(
                f"<div style='background-color: #dcfce7; color: #166534; padding: 3px 8px; border-left: 3px solid #22c55e; margin: 2px 0; border-radius: 2px;'><strong>+ </strong>{content}</div>"
            )
        elif line.startswith("? "):
            continue
        else:
            content = html.escape(line[2:])
            html_lines.append(f"<div style='color: #475569; padding: 2px 8px;'>&nbsp;&nbsp;{content}</div>")

    return "".join(html_lines)


def get_format_label(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "PDF Manuscript"
    elif lower.endswith(".docx"):
        return "Word Document (.docx)"
    elif lower.endswith(".txt"):
        return "Plain Text (.txt)"
    return "Document"


def get_file_download_meta(filename: str):
    lower = filename.lower()
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "⬇️ Download DOCX"
    elif lower.endswith(".txt"):
        return "text/plain", "⬇️ Download TXT"
    return "application/pdf", "⬇️ Download PDF"


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
        "<span style='font-size: 0.85rem; color: #64748b;'>Configure supported formats, detection rules, and redaction depth.</span>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    st.markdown("#### **Supported Formats**")
    enable_pdf = st.checkbox(
        "PDF Documents (.pdf)",
        value=True,
        help="Full layout-preserving destructive vector redaction for PDF research papers.",
    )
    enable_docx = st.checkbox(
        "Word Documents (.docx)",
        value=True,
        help="Sanitize Microsoft Word research manuscripts, author paragraphs, and strip document properties.",
    )
    enable_txt = st.checkbox(
        "Plain Text Documents (.txt)",
        value=True,
        help="Sanitize plain text research papers and preambles before Abstract.",
    )

    allowed_extensions = set()
    if enable_pdf:
        allowed_extensions.add("pdf")
    if enable_docx:
        allowed_extensions.add("docx")
    if enable_txt:
        allowed_extensions.add("txt")

    uploader_types = list(allowed_extensions) + ["zip"] if allowed_extensions else ["zip"]

    st.markdown("---")
    st.markdown("#### **Scope & Targeting**")
    scope_page1 = st.checkbox(
        "Scope Redactions to Page 1 Only (Recommended)",
        value=True,
        help="Restricts redaction strictly to the first page (or preamble before Abstract for TXT). Preserves legitimate citations, dataset names, and institutional mentions on later pages.",
    )

    if scope_page1:
        st.caption(
            "🔒 **Safe Mode Active**: Only Page 1 / Preamble is modified. University names in citations, references, and datasets (e.g. *'Stanford Dogs Dataset'*) remain intact."
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

    detect_github = st.checkbox(
        "Remove GitHub Repository URLs",
        value=False,
        help="Removes links to GitHub repositories (e.g. github.com/username/project). Code repositories are a major identity leak in double-blind review.",
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
        "Scrub Document Metadata",
        value=True,
        help="Clears 'Author', 'Creator', 'Producer', 'Title', and modification timestamps from PDF catalog & Word core properties.",
    )

    remove_annots = st.checkbox(
        "Clear Annotations & Comments",
        value=True,
        help="Deletes author annotations, sticky notes, or comment tracks in PDF and Word manuscripts.",
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
    if st.button("🧪 Load Sample Papers (PDF, DOCX, TXT)", use_container_width=True):
        st.session_state.uploaded_files_data["sample_paper_ieee.pdf"] = create_synthetic_research_paper()
        st.session_state.uploaded_files_data["sample_paper_nlp.docx"] = create_synthetic_docx_paper()
        st.session_state.uploaded_files_data["sample_paper_preamble.txt"] = create_synthetic_txt_paper()
        st.session_state.results = []
        st.session_state.preview_cache = {}
        st.toast("Loaded sample PDF, Word (.docx), and Plain Text (.txt) papers!", icon="📄")
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
        <h1>Multi-Format Research Paper Anonymizer</h1>
        <p>Automated double-blind peer review preparation. Irreversibly strips author blocks, affiliations, emails, and document metadata from PDF, Word (.docx), and Plain Text (.txt) manuscripts.</p>
        <div class="badge-container">
            <span class="badge"><span class="badge-dot"></span> 100% Local Processing (Private & Offline)</span>
            <span class="badge"><span class="badge-dot"></span> PDF, Word (.docx) & Plain Text (.txt) Supported</span>
            <span class="badge"><span class="badge-dot"></span> Bulk Direct & ZIP Archives Supported</span>
            <span class="badge"><span class="badge-dot"></span> True Destructive Redaction</span>
            <span class="badge"><span class="badge-dot"></span> Double-Blind Review Ready</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------- UPLOAD ZONE -----------------
uploaded_files = st.file_uploader(
    "Upload Research Papers or ZIP Archive in bulk",
    type=uploader_types,
    accept_multiple_files=True,
    help="Upload individual PDF, Word (.docx), Plain Text (.txt) papers, or a ZIP archive containing any combination. Nested folders are automatically unbundled.",
)

# Store newly uploaded files into session state
if uploaded_files:
    newly_added = 0
    for f in uploaded_files:
        fname = f.name
        fbytes = f.read()

        if fname.lower().endswith(".zip"):
            extracted_dict, skipped_list = extract_documents_from_zip(fbytes, allowed_extensions=allowed_extensions)
            for doc_name, doc_data in extracted_dict.items():
                if doc_name not in st.session_state.uploaded_files_data:
                    st.session_state.uploaded_files_data[doc_name] = doc_data
                    newly_added += 1

            if extracted_dict:
                st.toast(f"📦 Unpacked {len(extracted_dict)} documents from {fname}!", icon="🎉")
            if skipped_list:
                st.warning(
                    f"⚠️ {len(skipped_list)} item(s) skipped in {fname}: {', '.join(skipped_list[:3])}"
                )

        else:
            file_ext = fname.lower().split(".")[-1]
            if file_ext in allowed_extensions:
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
                    "Format": get_format_label(name),
                }
                for name, data in st.session_state.uploaded_files_data.items()
            ]
        )
        st.dataframe(staged_df, use_container_width=True, hide_index=True)

# Track settings signature
current_settings_signature = (
    enable_pdf,
    enable_docx,
    enable_txt,
    scope_page1,
    detect_page1,
    detect_footnotes,
    detect_emails,
    detect_orcid,
    detect_github,
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
    pdf_detector = PDFDetector(
        scope_to_page1=scope_page1,
        detect_first_page_author_block=detect_page1,
        detect_first_page_footnotes=detect_footnotes,
        detect_emails=detect_emails,
        detect_orcid=detect_orcid,
        detect_github_urls=detect_github,
        detect_affiliations_everywhere=detect_affils_all,
        custom_keywords=custom_keywords,
    )
    pdf_redactor = PDFRedactor(
        strip_metadata=strip_meta,
        remove_annotations=remove_annots,
        fill_color=(1.0, 1.0, 1.0),
    )

    docx_detector = DOCXDetector(
        scope_to_page1=scope_page1,
        detect_first_page_author_block=detect_page1,
        detect_first_page_footnotes=detect_footnotes,
        detect_emails=detect_emails,
        detect_orcid=detect_orcid,
        detect_github_urls=detect_github,
        detect_affiliations_everywhere=detect_affils_all,
        custom_keywords=custom_keywords,
    )
    docx_redactor = DOCXRedactor(strip_metadata=strip_meta)

    txt_detector = TXTDetector(
        scope_to_page1=scope_page1,
        detect_first_page_author_block=detect_page1,
        detect_first_page_footnotes=detect_footnotes,
        detect_emails=detect_emails,
        detect_orcid=detect_orcid,
        detect_github_urls=detect_github,
        detect_affiliations_everywhere=detect_affils_all,
        custom_keywords=custom_keywords,
    )
    txt_redactor = TXTRedactor(strip_metadata=strip_meta)

    results: list[RedactionResult] = []
    progress_bar = st.progress(0, text="Initializing batch document processing...")

    total_files = len(st.session_state.uploaded_files_data)
    for idx, (filename, file_bytes) in enumerate(st.session_state.uploaded_files_data.items()):
        progress_bar.progress(
            (idx) / total_files,
            text=f"Sanitizing ({idx + 1}/{total_files}): {filename}...",
        )

        lower_name = filename.lower()
        try:
            if lower_name.endswith(".pdf"):
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                targets = pdf_detector.detect_all(doc)
                result = pdf_redactor.redact_document(doc, targets, filename=filename)
                results.append(result)
                doc.close()
            elif lower_name.endswith(".docx"):
                doc = docx.Document(io.BytesIO(file_bytes))
                targets = docx_detector.detect_all(doc)
                result = docx_redactor.redact_document(file_bytes, targets, filename=filename)
                results.append(result)
            elif lower_name.endswith(".txt"):
                try:
                    raw_text = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    raw_text = file_bytes.decode("latin-1")
                targets = txt_detector.detect_all(raw_text)
                result = txt_redactor.redact_document(file_bytes, targets, filename=filename)
                results.append(result)
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
        ["🔍 Side-by-Side Visual & Text Preview", "📋 Audit & Processing Log", "📦 Download Station"]
    )

    # --- TAB 1: VISUAL PREVIEW ---
    with tab_preview:
        st.markdown("#### Side-by-Side Comparison")
        st.markdown(
            """
            <div style="margin-bottom: 1rem;">
                <span class="legend-item"><span class="legend-color" style="background:#ef4444;"></span> First-Page Author Block</span>
                <span class="legend-item"><span class="legend-color" style="background:#a855f7;"></span> Page 1 Footnotes</span>
                <span class="legend-item"><span class="legend-color" style="background:#3b82f6;"></span> Email Addresses</span>
                <span class="legend-item"><span class="legend-color" style="background:#10b981;"></span> ORCID Identifiers</span>
                <span class="legend-item"><span class="legend-color" style="background:#8b5cf6;"></span> GitHub URLs</span>
                <span class="legend-item"><span class="legend-color" style="background:#f59e0b;"></span> Affiliations / Keywords</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        doc_names = [r.filename for r in st.session_state.results]
        selected_file = st.selectbox("Select document to inspect:", doc_names, index=0)

        # Get result for chosen file
        selected_res = next(r for r in st.session_state.results if r.filename == selected_file)
        orig_bytes = st.session_state.uploaded_files_data[selected_file]
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

        if selected_res.file_type == "pdf":
            # PDF Rendered Page Preview
            max_pages = max(1, selected_res.original_page_count)

            # Interactive View & Zoom Toolbar for PDF
            st.markdown(
                """
                <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px;">
                    <span style="font-weight: 600; font-size: 0.9rem; color: #1e293b;">🔍 PDF Inspection & Zoom Toolbar</span>
                    <span style="font-size: 0.8rem; color: #64748b; margin-left: 8px;">Adjust zoom level, container height, or switch between side-by-side and full-width stacked view.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            p_col1, p_col2, p_col3, p_col4 = st.columns([1.5, 2, 2.5, 2])
            with p_col1:
                page_idx = st.number_input("Page #", min_value=1, max_value=max_pages, value=1, step=1) - 1

            with p_col2:
                pdf_layout = st.selectbox(
                    "Layout Mode",
                    ["Side-by-Side (Split)", "Stacked (Full Width)"],
                    index=0,
                    help="Side-by-Side displays Original and Sanitized pages side-by-side. Stacked displays each page at full width for maximum clarity.",
                )

            with p_col3:
                pdf_zoom_pct = st.select_slider(
                    "Zoom Magnification",
                    options=[75, 100, 125, 150, 175, 200],
                    value=100,
                    format_func=lambda x: f"{x}%",
                    help="Magnify the rendered PDF pages. At >100%, an interactive pan/scroll viewer lets you inspect footnotes and small author text.",
                )

            with p_col4:
                pdf_height_choice = st.selectbox(
                    "Viewer Height",
                    ["Fit Window (650px)", "Expanded (850px)", "Tall (1100px)", "Full Document"],
                    index=0,
                    help="Adjust the maximum height of the viewer container.",
                )

            # Map height
            if "650px" in pdf_height_choice:
                pdf_c_height = "650px"
            elif "850px" in pdf_height_choice:
                pdf_c_height = "850px"
            elif "1100px" in pdf_height_choice:
                pdf_c_height = "1100px"
            else:
                pdf_c_height = "none"

            cache_key = f"{selected_file}_{page_idx}_{preview_dpi}"
            if cache_key not in st.session_state.preview_cache:
                with st.spinner("Rendering high-resolution page comparison..."):
                    preview_gen = PreviewGenerator(dpi=preview_dpi)
                    overlay_img, clean_img = preview_gen.generate_side_by_side_previews(
                        orig_bytes,
                        targets_for_file,
                        selected_res.output_pdf_bytes,
                        page_num=page_idx,
                    )
                    st.session_state.preview_cache[cache_key] = (overlay_img, clean_img)

            overlay_img, clean_img = st.session_state.preview_cache[cache_key]

            def render_zoomable_pdf_box(img: Image.Image, zoom_pct: int, height_val: str, caption: str):
                b64 = pil_to_base64_png(img)
                overflow_css = "overflow: auto;" if height_val != "none" or zoom_pct > 100 else "overflow: hidden;"
                max_h_css = f"max-height: {height_val};" if height_val != "none" else ""
                st.markdown(
                    f"""
                    <div style="{overflow_css} {max_h_css} border: 1px solid #cbd5e1; border-radius: 8px; background: #334155; padding: 12px; text-align: center; box-shadow: inset 0 2px 4px rgba(0,0,0,0.15);">
                        <img src="data:image/png;base64,{b64}" style="width: {zoom_pct}%; max-width: none; border-radius: 4px; box-shadow: 0 4px 14px rgba(0,0,0,0.35); display: inline-block;" alt="{caption}" />
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if pdf_layout == "Side-by-Side (Split)":
                col_orig, col_clean = st.columns(2)
                with col_orig:
                    st.markdown("##### 🔴 Original PDF (Detected Redaction Boundaries)")
                    render_zoomable_pdf_box(overlay_img, pdf_zoom_pct, pdf_c_height, "Original PDF")

                with col_clean:
                    st.markdown("##### ⚪ Anonymized PDF (Destructive Whitespace Fill)")
                    render_zoomable_pdf_box(clean_img, pdf_zoom_pct, pdf_c_height, "Anonymized PDF")
            else:
                # Stacked full-width mode
                st.markdown("##### 🔴 Original PDF (Detected Redaction Boundaries - Full Width)")
                render_zoomable_pdf_box(overlay_img, pdf_zoom_pct, pdf_c_height, "Original PDF")
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("##### ⚪ Anonymized PDF (Destructive Whitespace Fill - Full Width)")
                render_zoomable_pdf_box(clean_img, pdf_zoom_pct, pdf_c_height, "Anonymized PDF")

        else:
            # Word (.docx) or Plain Text (.txt) Comparison & Zoom Controls
            st.markdown(
                """
                <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px;">
                    <span style="font-weight: 600; font-size: 0.9rem; color: #1e293b;">🔍 Text Inspection & Zoom Toolbar</span>
                    <span style="font-size: 0.8rem; color: #64748b; margin-left: 8px;">Adjust font size zoom, container height, font style, and diff modes for text review.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            txt_c1, txt_c2, txt_c3, txt_c4 = st.columns([2, 2, 2, 2])
            with txt_c1:
                font_size_px = st.slider(
                    "Font Size / Text Zoom",
                    min_value=11,
                    max_value=28,
                    value=14,
                    step=1,
                    format="%d px",
                    help="Adjust font magnification from 11px up to 28px for comfortable reading.",
                )
            with txt_c2:
                container_height_choice = st.selectbox(
                    "Viewer Height",
                    ["Compact (450px)", "Standard (600px)", "Expanded (850px)", "Full Document"],
                    index=1,
                    help="Adjust the maximum height of the text box or display full document without scrolling.",
                )
            with txt_c3:
                typography_choice = st.selectbox(
                    "Typography Style",
                    ["Monospace (Raw / Code)", "Sans-Serif (Standard Text)"],
                    index=0,
                    help="Switch between monospaced font and modern readable sans-serif.",
                )
            with txt_c4:
                comparison_mode = st.selectbox(
                    "Comparison View",
                    ["Side-by-Side Split", "Original (Highlighted)", "Anonymized Only", "Unified Diff / Changes"],
                    index=0,
                    help="Side-by-side comparison, single view, or unified line-by-line diff.",
                )

            # Formatting styles
            if "450px" in container_height_choice:
                c_height_css = "max-height: 450px; overflow-y: auto;"
            elif "600px" in container_height_choice:
                c_height_css = "max-height: 600px; overflow-y: auto;"
            elif "850px" in container_height_choice:
                c_height_css = "max-height: 850px; overflow-y: auto;"
            else:
                c_height_css = "max-height: none;"

            font_family_css = (
                "'JetBrains Mono', 'Courier New', monospace"
                if "Monospace" in typography_choice
                else "'Plus Jakarta Sans', -apple-system, sans-serif"
            )
            line_height = "1.65" if "Sans" in typography_choice else "1.5"

            box_style = (
                f"{c_height_css} "
                f"background: #ffffff; "
                f"padding: 16px; "
                f"border-radius: 8px; "
                f"border: 1px solid #cbd5e1; "
                f"font-family: {font_family_css}; "
                f"white-space: pre-wrap; "
                f"font-size: {font_size_px}px; "
                f"line-height: {line_height}; "
                f"color: #1e293b; "
                f"box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.04);"
            )

            if comparison_mode == "Side-by-Side Split":
                col_orig, col_clean = st.columns(2)
                with col_orig:
                    st.markdown(f"##### 🔴 Original {selected_res.file_type.upper()} (Detected Redactions Highlighted)")
                    highlighted_html = highlight_text_targets(selected_res.original_text or "", targets_for_file)
                    st.markdown(f'<div style="{box_style}">{highlighted_html}</div>', unsafe_allow_html=True)

                with col_clean:
                    st.markdown(f"##### ⚪ Anonymized {selected_res.file_type.upper()} (Sanitized Output)")
                    sanitized_escaped = html.escape(selected_res.sanitized_text or "")
                    st.markdown(f'<div style="{box_style}">{sanitized_escaped}</div>', unsafe_allow_html=True)

            elif comparison_mode == "Original (Highlighted)":
                st.markdown(f"##### 🔴 Original {selected_res.file_type.upper()} (Detected Redactions Highlighted - Full Width)")
                highlighted_html = highlight_text_targets(selected_res.original_text or "", targets_for_file)
                st.markdown(f'<div style="{box_style}">{highlighted_html}</div>', unsafe_allow_html=True)

            elif comparison_mode == "Anonymized Only":
                st.markdown(f"##### ⚪ Anonymized {selected_res.file_type.upper()} (Sanitized Output - Full Width)")
                sanitized_escaped = html.escape(selected_res.sanitized_text or "")
                st.markdown(f'<div style="{box_style}">{sanitized_escaped}</div>', unsafe_allow_html=True)

            else:  # Unified Diff / Changes
                st.markdown(f"##### 🔄 Unified Change Inspector (Red = Redacted Identities, Green = Preserved Text)")
                diff_html = generate_html_diff(selected_res.original_text or "", selected_res.sanitized_text or "")
                st.markdown(f'<div style="{box_style}">{diff_html}</div>', unsafe_allow_html=True)

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
                                "Page/Section": item["page_num"] + 1,
                                "Category": item["category"].replace("_", " ").title(),
                                "Reason": item["reason"],
                                "Identified Text": item["text"],
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
            label="📦 Download All Anonymized Documents + Audit Report (.zip)",
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
                    f"<span style='color: #64748b; font-size: 0.85rem;'>{get_format_label(res.filename)} · {res.targets_count} redactions applied · {len(res.output_pdf_bytes) // 1024} KB</span>",
                    unsafe_allow_html=True,
                )
            with d_col2:
                mime_type, btn_label = get_file_download_meta(res.filename)
                st.download_button(
                    label=btn_label,
                    data=res.output_pdf_bytes,
                    file_name=f"anonymized_{res.filename}",
                    mime=mime_type,
                    key=f"dl_{res.filename}",
                    use_container_width=True,
                )

elif not st.session_state.uploaded_files_data:
    st.info("👆 Upload research paper PDFs, Word (.docx), or Plain Text (.txt) above, or click **Load Sample Papers** in the sidebar to test.")
