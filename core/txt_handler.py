"""Handler for detecting and redacting sensitive author identities in Plain Text (.txt) files."""

import re
from typing import List, Dict, Any, Optional, Set

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


class TXTDetector:
    """Detects author information, affiliations, and identifiers in Plain Text (.txt) files."""

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

    def detect_all(self, text: str) -> List[RedactionTarget]:
        """Detect all target redactions in the text manuscript."""
        targets: List[RedactionTarget] = []
        lines = text.splitlines()
        if not lines:
            return targets

        # 1. Identify Title and Abstract Boundary
        title_idx = None
        for i, line in enumerate(lines):
            if line.strip():
                title_idx = i
                break

        if title_idx is None:
            return targets

        abstract_idx = None
        for i in range(title_idx + 1, len(lines)):
            if ABSTRACT_STOP_REGEX.search(lines[i].strip()):
                abstract_idx = i
                break

        # Define "First-Page / Preamble" boundary in plain text
        if abstract_idx is not None:
            preamble_end_idx = abstract_idx
        else:
            preamble_end_idx = min(len(lines), 40)  # Standard 40 lines ~ 1 printed page

        # 2. Author Block Detection (strictly between Title and Abstract in preamble)
        if self.detect_first_page_author_block:
            for i in range(title_idx + 1, preamble_end_idx):
                line_text = lines[i].strip()
                if line_text:
                    targets.append(
                        RedactionTarget(
                            page_num=0,
                            bbox=(0, float(i), 0, float(i)),
                            text=line_text,
                            reason="Preamble Author & Affiliation Line",
                            category="author_block",
                        )
                    )

        # 3. Preamble Footnote / Correspondence detection
        if self.detect_first_page_footnotes:
            for i in range(title_idx + 1, preamble_end_idx):
                line_text = lines[i].strip()
                if not line_text:
                    continue
                has_corr = bool(FOOTNOTE_CORRESPONDENCE_REGEX.search(line_text))
                has_affil = any(re.search(pat, line_text, re.IGNORECASE) for pat in INSTITUTION_KEYWORDS)
                has_email = bool(EMAIL_REGEX.search(line_text))
                if has_corr or (has_affil and has_email):
                    targets.append(
                        RedactionTarget(
                            page_num=0,
                            bbox=(0, float(i), 0, float(i)),
                            text=line_text,
                            reason="Preamble Correspondence / Footnote",
                            category="footnote",
                        )
                    )

        # 4. Pattern Detection (Emails, ORCID, GitHub, Affiliations)
        scan_end = preamble_end_idx if self.scope_to_page1 else len(lines)

        for line_idx in range(scan_end):
            line_text = lines[line_idx]
            if not line_text:
                continue

            if self.detect_emails:
                for match in EMAIL_REGEX.finditer(line_text):
                    targets.append(
                        RedactionTarget(
                            page_num=0 if self.scope_to_page1 else line_idx // 40,
                            bbox=(0, float(line_idx), 0, float(line_idx)),
                            text=match.group(0),
                            reason="Email Address",
                            category="email",
                        )
                    )

            if self.detect_orcid:
                for match in ORCID_REGEX.finditer(line_text):
                    targets.append(
                        RedactionTarget(
                            page_num=0 if self.scope_to_page1 else line_idx // 40,
                            bbox=(0, float(line_idx), 0, float(line_idx)),
                            text=match.group(0),
                            reason="ORCID Identifier",
                            category="orcid",
                        )
                    )

            if self.detect_github_urls:
                for match in GITHUB_URL_REGEX.finditer(line_text):
                    targets.append(
                        RedactionTarget(
                            page_num=0 if self.scope_to_page1 else line_idx // 40,
                            bbox=(0, float(line_idx), 0, float(line_idx)),
                            text=match.group(0),
                            reason="GitHub Repository URL",
                            category="github",
                        )
                    )

            if self.detect_affiliations_everywhere and not self.scope_to_page1:
                for kw_pat in INSTITUTION_KEYWORDS:
                    kw_re = re.compile(kw_pat, re.IGNORECASE)
                    for match in kw_re.finditer(line_text):
                        targets.append(
                            RedactionTarget(
                                page_num=line_idx // 40,
                                bbox=(0, float(line_idx), 0, float(line_idx)),
                                text=match.group(0),
                                reason="Institution Affiliation",
                                category="affiliation",
                            )
                        )

        # 5. Custom Keywords: Explicit user instructions, scanned across ALL lines of the document
        if self.custom_keywords:
            for kw in self.custom_keywords:
                kw_re = re.compile(re.escape(kw), re.IGNORECASE)
                for line_idx, line_text in enumerate(lines):
                    for match in kw_re.finditer(line_text):
                        targets.append(
                            RedactionTarget(
                                page_num=line_idx // 40,
                                bbox=(0, float(line_idx), 0, float(line_idx)),
                                text=match.group(0),
                                reason=f"Custom Keyword: '{kw}'",
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


class TXTRedactor:
    """Applies irreversible text redactions to Plain Text manuscripts."""

    def __init__(self, strip_metadata: bool = True):
        self.strip_metadata = strip_metadata

    def redact_document(
        self,
        txt_bytes: bytes,
        targets: List[RedactionTarget],
        filename: str = "document.txt",
    ) -> RedactionResult:
        try:
            original_text = txt_bytes.decode("utf-8")
        except UnicodeDecodeError:
            original_text = txt_bytes.decode("latin-1")

        lines = original_text.splitlines()

        # Categorize targets
        author_block_texts = {t.text.strip().lower() for t in targets if t.category in ("author_block", "footnote")}
        inline_target_texts = [t.text.strip() for t in targets if t.category not in ("author_block", "footnote")]

        sanitized_lines: List[str] = []
        for line in lines:
            line_trimmed = line.strip()
            if not line_trimmed:
                sanitized_lines.append(line)
                continue

            # If whole line is author block
            if line_trimmed.lower() in author_block_texts or any(
                abt in line_trimmed.lower() for abt in author_block_texts if len(abt) > 5
            ):
                sanitized_lines.append("[REDACTED: AUTHOR & AFFILIATION]")
                continue

            # Inline replacements
            modified_line = line
            for target_text in inline_target_texts:
                if not target_text:
                    continue
                pat = re.compile(re.escape(target_text), re.IGNORECASE)
                modified_line = pat.sub("[REDACTED]", modified_line)

            sanitized_lines.append(modified_line)

        sanitized_text = "\n".join(sanitized_lines)
        output_bytes = sanitized_text.encode("utf-8")

        # Verification
        is_clean = self._verify_cleanliness(sanitized_text, targets)

        return RedactionResult(
            filename=filename,
            original_page_count=max(1, len(lines) // 40),
            targets_count=len(targets),
            redacted_items=[t.to_dict() for t in targets],
            metadata_stripped=True,
            is_verified_clean=is_clean,
            output_pdf_bytes=output_bytes,
            file_type="txt",
            original_text=original_text,
            sanitized_text=sanitized_text,
        )

    def _verify_cleanliness(self, sanitized_text: str, targets: List[RedactionTarget]) -> bool:
        lower_sanitized = sanitized_text.lower()
        for t in targets:
            words = [w.lower() for w in t.text.split() if len(w) > 4 and w.lower() not in ("department", "university", "author")]
            for w in words[:1]:
                if w in lower_sanitized:
                    return False
        return True

