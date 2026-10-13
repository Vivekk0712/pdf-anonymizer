# 🛡️ Bulk PDF Anonymizer (Research Paper Sanitizer)

A privacy-focused, local-first bulk anonymization tool for preparing research papers for double-blind peer review. It removes author blocks, affiliations, departments, emails, and identifying metadata while **preserving the original PDF layout and vector typography intact**.

---

## 🚀 Features (Phase 1 MVP)

- **Safe Page 1 Scoping (Default)**: Restricts author identity redactions strictly to the first page. Guarantees that university citations, reference lists, benchmarks, and dataset names (e.g. *"Stanford Cars Dataset"*, *"Oxford Flowers"*, or *"Harvard University, 2024"*) in the paper body and bibliography are 100% preserved.
- **Layout-Aware Author Block Detection**: Identifies the boundary between paper title and abstract/introduction to isolate author names, affiliations, departments, universities, and contact details on the first page.
- **First-Page Footnote Sanitizer**: Detects and redacts author correspondence notes, grants, and email footnotes typically positioned at the bottom of Page 1.
- **Precision Pattern Identification**: Regex-based detection for email addresses, ORCID identifiers, and GitHub repository links (`github.com/...`) across manuscripts.
- **Configurable GitHub URL Redaction**: Dedicated toggle (checked by default) to sanitize code repository links that often leak author identities and commit logs.
- **Destructive PyMuPDF Redaction**: Irreversibly deletes underlying text glyphs and vectors rather than simply drawing an overlay, filling the redacted area with pristine white space without shifting surrounding content.
- **PDF Metadata Stripping**: Cleans identifying catalog fields (`Author`, `Creator`, `Producer`, `Title`, `CreationDate`, `ModDate`) and removes annotations.
- **Verification Engine**: Automatically verifies that redacted names and identifiers are no longer extractable or searchable in the generated PDF.
- **Side-by-Side Visual Preview**: Inspect proposed bounding boxes on the original page alongside the anonymized result before exporting.
- **Batch ZIP Export & Audit Logs**: Download all anonymized papers in one ZIP archive along with CSV and JSON audit reports.
- **100% Local & Private**: No external API calls or LLM dependencies; unpublished manuscripts stay private on your local machine.

---

## 📂 Architecture

```text
PDF_Anon/
├── app.py                      # Streamlit UI & interactive workflow
├── core/
│   ├── __init__.py
│   ├── detector.py             # Author block, email, ORCID, and affiliation detector
│   ├── redactor.py             # Permanent PyMuPDF redaction & metadata scrubber
│   ├── preview.py              # Visual side-by-side & overlay preview generator
│   └── exporter.py             # In-memory ZIP packager and audit reporter
├── tests/
│   └── test_pipeline.py        # Automated test suite with synthetic IEEE research paper
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
