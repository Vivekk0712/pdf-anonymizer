"""Detection engine for research paper author blocks, affiliations, emails, and identifiers."""

from dataclasses import dataclass, asdict
import re
from typing import List, Dict, Any, Optional, Tuple
import fitz  # PyMuPDF


@dataclass
class RedactionTarget:
    page_num: int
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    text: str
    reason: str
    category: str  # 'author_block', 'email', 'orcid', 'affiliation', 'footnote', 'custom'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Common institutional keywords in research papers
INSTITUTION_KEYWORDS = [
    r"\bdepartment\b",
    r"\bdept\.?\b",
    r"\buniversity\b",
    r"\buniv\.?\b",
    r"\bcollege\b",
    r"\binstitute\b",
    r"\bfaculty\b",
    r"\bschool\b",
    r"\blaboratory\b",
    r"\blab\b",
    r"\bcampus\b",
    r"\bpolytechnic\b",
    r"\bacademy\b",
    r"\bcenter for\b",
    r"\bcentre for\b",
]

# Patterns for author notes and correspondence in page 1 footnotes
FOOTNOTE_CORRESPONDENCE_REGEX = re.compile(
    r"\b(?:email\s+addresses?|e-?mails?|corresponding\s+author|authors?\s+(?:is|are)\s+with|manuscript\s+received|this\s+work\s+was\s+supported\s+by|supported\s+by|contact\s+author)\b",
    re.IGNORECASE,
)

# Regex patterns for identifiers
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.IGNORECASE)
ORCID_REGEX = re.compile(r"\b(?:https?://orcid\.org/)?(?:orcid:?\s*)?\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b", re.IGNORECASE)
GITHUB_URL_REGEX = re.compile(
    r"\b(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*[A-Za-z0-9_/-]",
    re.IGNORECASE,
)
ABSTRACT_STOP_REGEX = re.compile(
    r"^\s*(?:abstract|keywords?|index\s+terms?|1\.?\s+introduction|i\.?\s+introduction)\b",
    re.IGNORECASE,
)


class PDFDetector:
    """Detects author information, affiliations, and identifiers in academic PDFs."""

    def __init__(
        self,
        scope_to_page1: bool = True,
        detect_first_page_author_block: bool = True,
        detect_first_page_footnotes: bool = True,
        detect_emails: bool = True,
        detect_orcid: bool = True,
        detect_github_urls: bool = True,
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

    def detect_all(self, doc: fitz.Document) -> List[RedactionTarget]:
        """Detect all target redactions across the document."""
        targets: List[RedactionTarget] = []

        if len(doc) == 0:
            return targets

        # Determine which pages to scan
        # By default, academic research papers only have author identities on Page 1.
        # Scoping to Page 1 prevents destroying citations, references, or dataset names in the body.
        pages_to_scan = [0] if self.scope_to_page1 else list(range(len(doc)))

        # 1. First-page top author block detection
        if self.detect_first_page_author_block:
            page0_targets = self._detect_page1_author_block(doc[0])
            targets.extend(page0_targets)

        # 2. First-page correspondence / affiliation footnotes (IEEE / ACM / Springer style)
        if self.detect_first_page_footnotes:
            footnote_targets = self._detect_page1_footnotes(doc[0])
            targets.extend(footnote_targets)

        # 3. Standard Pattern detection (emails, ORCID, affiliations)
        for page_num in pages_to_scan:
            page = doc[page_num]

            if self.detect_emails:
                targets.extend(self._detect_regex_targets(page, page_num, EMAIL_REGEX, "Email Address", "email"))

            if self.detect_orcid:
                targets.extend(self._detect_regex_targets(page, page_num, ORCID_REGEX, "ORCID Identifier", "orcid"))

            if self.detect_affiliations_everywhere and not self.scope_to_page1:
                for kw_pattern in INSTITUTION_KEYWORDS:
                    kw_re = re.compile(kw_pattern, re.IGNORECASE)
                    targets.extend(self._detect_regex_targets(page, page_num, kw_re, "Institution Affiliation", "affiliation"))

        # 4. GitHub Repository URLs (removes code links that deanonymize authors via commit histories)
        if self.detect_github_urls:
            pages_for_github = list(range(len(doc))) if not self.scope_to_page1 else [0]
            # If user checked GitHub URLs, check first page or all pages
            for page_num in (list(range(len(doc))) if not self.scope_to_page1 else [0]):
                page = doc[page_num]
                targets.extend(
                    self._detect_regex_targets(
                        page, page_num, GITHUB_URL_REGEX, "GitHub Repository URL", "github"
                    )
                )

        # 5. Custom Keywords: Explicit user instructions, scanned across ALL pages of the document
        if self.custom_keywords:
            for page_num in range(len(doc)):
                page = doc[page_num]
                for kw in self.custom_keywords:
                    targets.extend(self._detect_custom_keyword(page, page_num, kw))

        # Deduplicate targets on same page with identical or overlapping bboxes
        deduped = self._deduplicate_targets(targets)
        return deduped

    def _detect_page1_author_block(self, page: fitz.Page) -> List[RedactionTarget]:
        """Detect author names and affiliation block on the first page between Title and Abstract."""
        targets: List[RedactionTarget] = []
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        # Filter text blocks only
        text_blocks = [b for b in blocks if b.get("type") == 0 and b.get("lines")]
        if not text_blocks:
            return targets

        # Filter text blocks, discarding vertical margin watermarks (e.g. arXiv banners)
        valid_blocks = []
        for b in text_blocks:
            b_text = " ".join(span.get("text", "") for line in b.get("lines", []) for span in line.get("spans", []))
            bbox = b.get("bbox", (0, 0, 0, 0))
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]

            # Discard arXiv vertical strips and margin banners
            if "arxiv:" in b_text.lower():
                continue
            if h > w * 2 and (bbox[0] < 60 or bbox[2] > page.rect.width - 60):
                continue
            valid_blocks.append(b)

        if not valid_blocks:
            return targets

        page_height = page.rect.height

        # Step 1: Locate candidate paper title
        # In research papers, title is near top (usually y0 < 0.45 * page_height)
        # and has maximum font size among valid horizontal blocks.
        max_font_size = 0.0

        for b in valid_blocks:
            bbox = b.get("bbox", (0, 0, 0, 0))
            if bbox[1] > 0.45 * page_height:
                continue

            block_max_font = 0.0
            block_text = ""
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    font_size = span.get("size", 0.0)
                    if font_size > block_max_font:
                        block_max_font = font_size
                    block_text += span.get("text", "") + " "

            block_text = block_text.strip()
            # Skip tiny headers at top
            if bbox[1] < 55 and block_max_font < 11:
                continue

            if block_max_font > max_font_size and len(block_text) > 3:
                max_font_size = block_max_font

        # Title bottom coordinate
        title_bottom_y = 0.0
        for b in valid_blocks:
            bbox = b.get("bbox", (0, 0, 0, 0))
            if bbox[1] > 0.45 * page_height:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("size", 0.0) >= max(11.0, max_font_size * 0.85):
                        if bbox[3] > title_bottom_y:
                            title_bottom_y = bbox[3]
                        break

        # Step 2: Locate Abstract / Stop marker
        abstract_top_y = None
        for b in valid_blocks:
            bbox = b.get("bbox", (0, 0, 0, 0))
            for line in b.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if ABSTRACT_STOP_REGEX.search(line_text):
                    if abstract_top_y is None or bbox[1] < abstract_top_y:
                        abstract_top_y = bbox[1]
                    break

        # Step 3: Identify Author Zone strictly between Title and Abstract
        if title_bottom_y > 0 and abstract_top_y and abstract_top_y > title_bottom_y:
            for b in valid_blocks:
                b_bbox = b.get("bbox", (0, 0, 0, 0))
                # Leave 2pt buffer so title and abstract themselves are never redacted
                if b_bbox[1] >= title_bottom_y - 2 and b_bbox[3] <= abstract_top_y + 2:
                    for line in b.get("lines", []):
                        line_bbox = line.get("bbox")
                        line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                        if line_text:
                            targets.append(
                                RedactionTarget(
                                    page_num=0,
                                    bbox=tuple(line_bbox),
                                    text=line_text,
                                    reason="First-page Author & Affiliation Block",
                                    category="author_block",
                                )
                            )

        # Fallback if no abstract marker detected
        if not targets:
            for b in text_blocks:
                b_bbox = b.get("bbox", (0, 0, 0, 0))
                if b_bbox[1] > 0.60 * page_height:
                    continue  # unlikely to be top author block

                for line in b.get("lines", []):
                    line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    is_affil = any(re.search(pat, line_text, re.IGNORECASE) for pat in INSTITUTION_KEYWORDS)
                    is_email = bool(EMAIL_REGEX.search(line_text))
                    is_orcid = bool(ORCID_REGEX.search(line_text))

                    if is_affil or is_email or is_orcid:
                        targets.append(
                            RedactionTarget(
                                page_num=0,
                                bbox=tuple(line.get("bbox")),
                                text=line_text,
                                reason="Author/Institution Clue on Page 1",
                                category="author_block",
                            )
                        )

            if title_bottom_y > 0 and targets:
                earliest_target_y = min(t.bbox[1] for t in targets)
                for b in text_blocks:
                    b_bbox = b.get("bbox", (0, 0, 0, 0))
                    if b_bbox[1] >= title_bottom_y - 2 and b_bbox[3] <= earliest_target_y + 4:
                        for line in b.get("lines", []):
                            line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                            if line_text:
                                targets.append(
                                    RedactionTarget(
                                        page_num=0,
                                        bbox=tuple(line.get("bbox")),
                                        text=line_text,
                                        reason="Author Names Block",
                                        category="author_block",
                                    )
                                )

        return targets

    def _detect_page1_footnotes(self, page: fitz.Page) -> List[RedactionTarget]:
        """Detect author correspondence, institutional affiliations, or grant notes in Page 1 footnotes."""
        targets: List[RedactionTarget] = []
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        page_height = page.rect.height
        # Footnotes are located in the lower 30% of the first page
        footnote_y_threshold = 0.70 * page_height

        for b in blocks:
            if b.get("type") != 0:
                continue
            bbox = b.get("bbox", (0, 0, 0, 0))
            if bbox[1] < footnote_y_threshold:
                continue

            block_text = ""
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("text", "") + " "

            # Check if this footnote contains correspondence or author affiliations
            has_corr = bool(FOOTNOTE_CORRESPONDENCE_REGEX.search(block_text))
            has_affil = any(re.search(pat, block_text, re.IGNORECASE) for pat in INSTITUTION_KEYWORDS)
            has_email = bool(EMAIL_REGEX.search(block_text))

            if has_corr or (has_affil and has_email):
                # Redact each line in the correspondence footnote
                for line in b.get("lines", []):
                    line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    if line_text:
                        targets.append(
                            RedactionTarget(
                                page_num=0,
                                bbox=tuple(line.get("bbox")),
                                text=line_text,
                                reason="First-Page Author/Correspondence Footnote",
                                category="footnote",
                            )
                        )

        return targets

    def _detect_custom_keyword(
        self, page: fitz.Page, page_num: int, keyword: str
    ) -> List[RedactionTarget]:
        """Detect custom keywords or multi-word phrases across the page."""
        targets: List[RedactionTarget] = []
        kw = keyword.strip()
        if not kw:
            return targets

        # 1. Primary: full-page text search (handles multi-word phrases, case variations, font spans)
        rects = page.search_for(kw)
        for r in rects:
            targets.append(
                RedactionTarget(
                    page_num=page_num,
                    bbox=(r.x0, r.y0, r.x1, r.y1),
                    text=kw,
                    reason=f"Custom Keyword: '{kw}'",
                    category="custom",
                )
            )

        # 2. Fallback: if search_for returned nothing, check line-by-line using case-insensitive regex
        if not rects:
            try:
                kw_re = re.compile(re.escape(kw), re.IGNORECASE)
                targets.extend(self._detect_regex_targets(page, page_num, kw_re, f"Custom Keyword: '{kw}'", "custom"))
            except Exception:
                pass

        return targets

    def _detect_regex_targets(
        self,
        page: fitz.Page,
        page_num: int,
        pattern: re.Pattern,
        reason: str,
        category: str,
    ) -> List[RedactionTarget]:
        """Detect regex occurrences and retrieve accurate bounding boxes."""
        targets: List[RedactionTarget] = []
        page_dict = page.get_text("dict")

        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                found_in_span = False
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    matches = list(pattern.finditer(span_text))
                    if not matches:
                        continue
                    found_in_span = True
                    for match in matches:
                        matched_str = match.group(0)
                        span_rect = fitz.Rect(span["bbox"])
                        rects = page.search_for(matched_str, clip=span_rect)
                        if not rects:
                            rects = [span_rect]

                        for r in rects:
                            targets.append(
                                RedactionTarget(
                                    page_num=page_num,
                                    bbox=(r.x0, r.y0, r.x1, r.y1),
                                    text=matched_str,
                                    reason=reason,
                                    category=category,
                                )
                            )

                # Fallback to line-level check if multi-word pattern crossed spans
                if not found_in_span:
                    line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                    line_matches = list(pattern.finditer(line_text))
                    for match in line_matches:
                        matched_str = match.group(0)
                        line_rect = fitz.Rect(line["bbox"])
                        rects = page.search_for(matched_str, clip=line_rect)
                        if not rects:
                            rects = [line_rect]

                        for r in rects:
                            targets.append(
                                RedactionTarget(
                                    page_num=page_num,
                                    bbox=(r.x0, r.y0, r.x1, r.y1),
                                    text=matched_str,
                                    reason=reason,
                                    category=category,
                                )
                            )

        return targets

    def _deduplicate_targets(self, targets: List[RedactionTarget]) -> List[RedactionTarget]:
        """Deduplicate targets with high coordinate overlap on the same page."""
        if not targets:
            return []

        sorted_targets = sorted(targets, key=lambda t: (t.page_num, t.bbox[1], t.bbox[0]))
        unique: List[RedactionTarget] = []

        for target in sorted_targets:
            r1 = fitz.Rect(target.bbox)
            is_duplicate = False

            for existing in unique:
                if existing.page_num != target.page_num:
                    continue
                r2 = fitz.Rect(existing.bbox)

                intersect = r1.intersect(r2)
                if not intersect.is_empty:
                    area1 = abs(r1)
                    area2 = abs(r2)
                    int_area = abs(intersect)
                    min_area = min(area1, area2) if min(area1, area2) > 0 else 1.0

                    if int_area / min_area > 0.85:
                        is_duplicate = True
                        break

            if not is_duplicate:
                unique.append(target)

        return unique
