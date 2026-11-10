# 🛡️ Multi-Format Research Paper Anonymizer (PDF, DOCX, TXT)

A privacy-focused, local-first bulk anonymization tool for preparing research papers for double-blind peer review. It removes author blocks, affiliations, departments, emails, and identifying metadata across **PDF, Microsoft Word (.docx), and Plain Text (.txt)** manuscripts.

---

## 🚀 Features

- **Multi-Format Support (PDF, DOCX, TXT)**: Seamlessly upload and sanitize individual PDF, Word (`.docx`), and Plain Text (`.txt`) documents, or a single ZIP archive containing any mix of all three formats.
- **Safe Page 1 / Preamble Scoping (Default)**: Restricts author identity redactions strictly to the first page (or top preamble before the Abstract for TXT & DOCX). Guarantees that university citations, reference lists, benchmarks, and dataset names (e.g. *"Stanford Cars Dataset"*, *"Harvard University, 2024"*) in the paper body and bibliography are 100% preserved.
- **Layout-Aware Author Block Detection**: Identifies the boundary between paper title and abstract/introduction to isolate author names, affiliations, departments, universities, and contact details.
- **First-Page Footnote Sanitizer**: Detects and redacts author correspondence notes, grants, and email footnotes.
- **Precision Pattern Identification**: Regex-based detection for email addresses, ORCID identifiers, and optional GitHub repository links (`github.com/...`).
- **Configurable GitHub URL Redaction**: Dedicated toggle (optional / unchecked by default) to sanitize code repository links that leak author identities and commit logs.
- **Format-Preserving Redaction**:
  - **PDF**: Destructive PyMuPDF vector erasure leaving white space without shifting surrounding layout.
  - **Word (.docx)**: Replaces author paragraphs/runs, scrubs core properties (`Author`, `Last Modified By`, `Comments`), and preserves formatting.
  - **Plain Text (.txt)**: Replaces author/affiliation lines with `[REDACTED]` markers while preserving line breaks and body text.
- **Verification Engine**: Automatically verifies that redacted names and identifiers are no longer extractable or searchable in the generated document.
- **Side-by-Side Visual & Text Preview**: Inspect proposed bounding boxes on PDF pages, or side-by-side text comparisons for DOCX/TXT before exporting.
- **Batch ZIP Export & Audit Logs**: Download all anonymized papers in one ZIP archive along with CSV and JSON audit reports.
- **100% Local & Private**: No external API calls or LLM dependencies; manuscripts stay private on your local machine.

---

## 📂 Architecture

```text
PDF_Anon/
├── app.py                      # Streamlit UI & interactive workflow
├── core/
│   ├── __init__.py
│   ├── detector.py             # PDF author block, email, ORCID, and affiliation detector
│   ├── redactor.py             # Permanent PyMuPDF redaction & metadata scrubber
│   ├── docx_handler.py         # Word (.docx) detection, redaction & property scrubber
│   ├── txt_handler.py          # Plain Text (.txt) preamble detection & text sanitizer
│   ├── preview.py              # Visual side-by-side & overlay preview generator
│   ├── importer.py             # Bulk ZIP extraction & validation for PDF, DOCX, TXT
│   └── exporter.py             # In-memory ZIP packager and audit reporter
├── tests/
│   └── test_pipeline.py        # Automated test suite (PDF, DOCX, TXT, multi-format ZIP)
├── requirements.txt            # Dependencies
├── docs.md                     # Project specification
└── README.md                   # Documentation
```

---

## 🛠️ Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Streamlit Application
```bash
streamlit run app.py
```

### 3. Run Automated Tests
```bash
python -m pytest tests/test_pipeline.py -v
```

---

## 🔮 Roadmap: Phase 2 (Coming Next)
- **Institution Dictionaries**: Pre-compiled lookup dictionary of 10,000+ global universities, research institutes, and funding bodies.
- **NLP / NER-Assisted Detection**: Named entity recognition (Spacy / HuggingFace) for unconventional author formats.
- **Recurring Header & Footer Stripper**: Detect and sanitize author names running across paper margins.
- **Interactive Redaction Adjuster**: Click-and-drag bounding box adjustment for fine-tuning edge cases.
