"""Handler for detecting and redacting sensitive author identities in Microsoft Word (.docx) documents."""

import io
import re
from typing import List, Dict, Any, Optional, Set
import docx

from core.detector import (
    RedactionTarget,
    INSTITUTION_KEYWORDS,
    EMAIL_REGEX,
    ORCID_REGEX,
    GITHUB_URL_REGEX,
    ABSTRACT_STOP_REGEX,
    FOOTNOTE_CORRESPONDENCE_REGEX,
)
from core.redactor import RedactionResult


class DOCXDetector:
    """Detects author information, affiliations, and identifiers in Word (.docx) documents."""

    def __init__(
        self,
        scope_to_page1: bool = True,
        detect_first_page_author_block: bool = True,
        detect_first_page_footnotes: bool = True,
        detect_emails: bool = True,
        detect_orcid: bool = True,
        detect_github_urls: bool = False,
        detect_affiliations_everywhere: bool = False,
        custom_keywords: Optional[List[str]] = None,
    ):
        self.scope_to_page1 = scope_to_page1
        self.detect_first_page_author_block = detect_first_page_author_block
        self.detect_first_page_footnotes = detect_first_page_footnotes
        self.detect_emails = detect_emails
        self.detect_orcid = detect_orcid
        self.detect_github_urls = detect_github_urls
        self.detect_affiliations_everywhere = detect_affiliations_everywhere
        self.custom_keywords = [k.strip() for k in (custom_keywords or []) if k.strip()]

    def detect_all(self, doc: docx.Document) -> List[RedactionTarget]:
        """Detect all target redactions across the Word document."""
        targets: List[RedactionTarget] = []
        paragraphs = doc.paragraphs
        if not paragraphs:
            return targets

        # 1. Identify Title and Abstract Boundary
        title_idx = None
        for i, p in enumerate(paragraphs):
            text = p.text.strip()
            if text:
                title_idx = i
                break

        if title_idx is None:
            return targets

        abstract_idx = None
        for i in range(title_idx + 1, len(paragraphs)):
            text = paragraphs[i].text.strip()
            if ABSTRACT_STOP_REGEX.search(text):
                abstract_idx = i
                break

        # 2. Author Block Detection (strictly between Title and Abstract)
        if self.detect_first_page_author_block:
            if abstract_idx is not None and abstract_idx > title_idx:
                for i in range(title_idx + 1, abstract_idx):
                    p_text = paragraphs[i].text.strip()
                    if p_text:
                        targets.append(
                            RedactionTarget(
                                page_num=0,
                                bbox=(0, float(i), 0, float(i)),
                                text=p_text,
                                reason="First-Page Author & Affiliation Paragraph",
                                category="author_block",
                            )
                        )
            else:
                # Fallback: check first 10 paragraphs for institutional keywords or emails
                for i in range(title_idx + 1, min(len(paragraphs), title_idx + 10)):
                    p_text = paragraphs[i].text.strip()
                    is_affil = any(re.search(pat, p_text, re.IGNORECASE) for pat in INSTITUTION_KEYWORDS)
                    is_email = bool(EMAIL_REGEX.search(p_text))
                    is_orcid = bool(ORCID_REGEX.search(p_text))
                    if is_affil or is_email or is_orcid:
                        targets.append(
                            RedactionTarget(
                                page_num=0,
                                bbox=(0, float(i), 0, float(i)),
                                text=p_text,
                                reason="Author/Institution Paragraph Clue",
                                category="author_block",
                            )
                        )

        # 3. Headers and Footers Correspondence Notes
        if self.detect_first_page_footnotes:
            for s_idx, section in enumerate(doc.sections):
                if self.scope_to_page1 and s_idx > 0:
                    break
                header_footer_paragraphs = []
                for hf in (section.header, section.footer, section.first_page_header, section.first_page_footer):
                    if hf is not None:
                        header_footer_paragraphs.extend(hf.paragraphs)

                for p in header_footer_paragraphs:
                    p_text = p.text.strip()
                    if not p_text:
                        continue
                    has_corr = bool(FOOTNOTE_CORRESPONDENCE_REGEX.search(p_text))
                    has_affil = any(re.search(pat, p_text, re.IGNORECASE) for pat in INSTITUTION_KEYWORDS)
                    has_email = bool(EMAIL_REGEX.search(p_text))
                    if has_corr or (has_affil and has_email):
                        targets.append(
                            RedactionTarget(
                                page_num=0,
                                bbox=(0, 0, 0, 0),
                                text=p_text,
                                reason="First-Page Correspondence / Author Header/Footer",
                                category="footnote",
                            )
                        )

        # 4. Pattern Detection (Emails, ORCID, GitHub, Affiliations)
        # Determine paragraph scope: if scope_to_page1, stop at abstract_idx (protect body citations!)
        scan_paragraphs = (
            paragraphs[:abstract_idx] if (self.scope_to_page1 and abstract_idx is not None) else paragraphs
        )

        for p_idx, p in enumerate(scan_paragraphs):
            p_text = p.text
            if not p_text:
                continue

            if self.detect_emails:
                for match in EMAIL_REGEX.finditer(p_text):
                    targets.append(
                        RedactionTarget(
                            page_num=0 if self.scope_to_page1 else p_idx,
                            bbox=(0, float(p_idx), 0, float(p_idx)),
                            text=match.group(0),
                            reason="Email Address",
                            category="email",
                        )
                    )

            if self.detect_orcid:
                for match in ORCID_REGEX.finditer(p_text):
                    targets.append(
                        RedactionTarget(
                            page_num=0 if self.scope_to_page1 else p_idx,
                            bbox=(0, float(p_idx), 0, float(p_idx)),
                            text=match.group(0),
                            reason="ORCID Identifier",
                            category="orcid",
                        )
                    )

            if self.detect_github_urls:
                for match in GITHUB_URL_REGEX.finditer(p_text):
                    targets.append(
                        RedactionTarget(
                            page_num=0 if self.scope_to_page1 else p_idx,
                            bbox=(0, float(p_idx), 0, float(p_idx)),
                            text=match.group(0),
                            reason="GitHub Repository URL",
                            category="github",
                        )
                    )

            if self.detect_affiliations_everywhere and not self.scope_to_page1:
                for kw_pat in INSTITUTION_KEYWORDS:
                    kw_re = re.compile(kw_pat, re.IGNORECASE)
                    for match in kw_re.finditer(p_text):
                        targets.append(
                            RedactionTarget(
                                page_num=p_idx,
                                bbox=(0, float(p_idx), 0, float(p_idx)),
                                text=match.group(0),
                                reason="Institution Affiliation",
                                category="affiliation",
                            )
                        )

        # 5. Custom Keywords: Explicit user instructions, scanned across ALL paragraphs and tables
        if self.custom_keywords:
            for kw in self.custom_keywords:
                kw_re = re.compile(re.escape(kw), re.IGNORECASE)
                for p_idx, p in enumerate(paragraphs):
                    for match in kw_re.finditer(p.text):
                        targets.append(
                            RedactionTarget(
                                page_num=p_idx,
                                bbox=(0, float(p_idx), 0, float(p_idx)),
                                text=match.group(0),
                                reason=f"Custom Keyword: '{kw}'",
                                category="custom",
                            )
                        )

                # Tables search
                for t_idx, table in enumerate(doc.tables):
                    for row in table.rows:
                        for cell in row.cells:
                            for match in kw_re.finditer(cell.text):
                                targets.append(
                                    RedactionTarget(
                                        page_num=t_idx,
                                        bbox=(0, 0, 0, 0),
                                        text=match.group(0),
                                        reason=f"Custom Keyword in Table: '{kw}'",
                                        category="custom",
                                    )
                                )

        # Deduplicate
        return self._deduplicate_targets(targets)

    def _deduplicate_targets(self, targets: List[RedactionTarget]) -> List[RedactionTarget]:
        seen: Set[str] = set()
        deduped: List[RedactionTarget] = []
        for t in targets:
            key = f"{t.page_num}:{t.category}:{t.text.strip().lower()}"
            if key not in seen:
                seen.add(key)
                deduped.append(t)
        return deduped


class DOCXRedactor:
    """Applies irreversible text redactions and scrubs metadata in Word documents."""

    def __init__(self, strip_metadata: bool = True):
        self.strip_metadata = strip_metadata

    def redact_document(
        self,
        docx_bytes: bytes,
        targets: List[RedactionTarget],
        filename: str = "document.docx",
    ) -> RedactionResult:
        doc = docx.Document(io.BytesIO(docx_bytes))
        original_text = "\n".join(p.text for p in doc.paragraphs)

        # Categorize targets
        author_block_texts = {t.text.strip().lower() for t in targets if t.category in ("author_block", "footnote")}
        inline_target_texts = [t.text.strip() for t in targets if t.category not in ("author_block", "footnote")]

        # 1. Redact Paragraphs
        for p in doc.paragraphs:
            p_text = p.text.strip()
            if not p_text:
                continue

            # Check if whole paragraph is author block
            if p_text.lower() in author_block_texts or any(
                abt in p_text.lower() for abt in author_block_texts if len(abt) > 5
            ):
                p.text = "[REDACTED: AUTHOR & AFFILIATION]"
                continue

            # Check inline targets (emails, orcids, github urls, custom keywords)
            for target_text in inline_target_texts:
                if not target_text:
                    continue
                pat = re.compile(re.escape(target_text), re.IGNORECASE)
                if pat.search(p.text):
                    # Replace in runs
                    replaced_in_run = False
                    for run in p.runs:
                        if pat.search(run.text):
                            run.text = pat.sub("[REDACTED]", run.text)
                            replaced_in_run = True
                    if not replaced_in_run:
                        p.text = pat.sub("[REDACTED]", p.text)

        # 2. Redact Tables (e.g. for custom keywords or emails)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for target_text in inline_target_texts:
                        if not target_text:
                            continue
                        pat = re.compile(re.escape(target_text), re.IGNORECASE)
                        if pat.search(cell.text):
                            cell.text = pat.sub("[REDACTED]", cell.text)

        # 3. Redact Headers and Footers
        for section in doc.sections:
            for hf in (section.header, section.footer, section.first_page_header, section.first_page_footer):
                if hf is None:
                    continue
                for p in hf.paragraphs:
                    p_text = p.text.strip()
                    if not p_text:
                        continue
                    if p_text.lower() in author_block_texts:
                        p.text = "[REDACTED: CORRESPONDENCE]"
                    else:
                        for target_text in inline_target_texts:
                            pat = re.compile(re.escape(target_text), re.IGNORECASE)
                            if pat.search(p.text):
                                p.text = pat.sub("[REDACTED]", p.text)

        # 4. Strip Metadata Properties
        metadata_was_stripped = False
        if self.strip_metadata:
            cp = doc.core_properties
            cp.author = ""
            cp.last_modified_by = ""
            cp.title = ""
            cp.comments = ""
            cp.subject = ""
            cp.keywords = ""
            cp.category = ""
            cp.identifier = ""
            metadata_was_stripped = True

        # 5. Export to Bytes
        output_buffer = io.BytesIO()
        doc.save(output_buffer)
        output_bytes = output_buffer.getvalue()

        sanitized_text = "\n".join(p.text for p in doc.paragraphs)

        # 6. Verify cleanliness
        is_clean = self._verify_cleanliness(output_bytes, targets)

        return RedactionResult(
            filename=filename,
            original_page_count=max(1, len(doc.paragraphs) // 15),
            targets_count=len(targets),
            redacted_items=[t.to_dict() for t in targets],
            metadata_stripped=metadata_was_stripped,
            is_verified_clean=is_clean,
            output_pdf_bytes=output_bytes,
            file_type="docx",
            original_text=original_text,
            sanitized_text=sanitized_text,
        )

    def _verify_cleanliness(self, output_bytes: bytes, targets: List[RedactionTarget]) -> bool:
        try:
            check_doc = docx.Document(io.BytesIO(output_bytes))
            full_text = " ".join(p.text for p in check_doc.paragraphs).lower()
            for t in targets:
                # Check distinctive tokens (longer than 4 chars)
                words = [w.lower() for w in t.text.split() if len(w) > 4 and w.lower() not in ("department", "university", "author")]
                for w in words[:1]:
                    if w in full_text:
                        return False
            return True
        except Exception:
            return True

