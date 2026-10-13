"""Visual preview generator for original documents, detection overlays, and anonymized outputs."""

import io
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw
import fitz  # PyMuPDF
from core.detector import RedactionTarget


class PreviewGenerator:
    """Generates visual previews of PDF pages with overlays and post-redaction results."""

    def __init__(self, dpi: int = 144):
        self.dpi = dpi

    def render_page_image(self, page: fitz.Page) -> Image.Image:
        """Renders a single fitz.Page to a PIL Image."""
        zoom = self.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return img

    def render_detection_overlay(
        self,
        page: fitz.Page,
        targets: List[RedactionTarget],
    ) -> Image.Image:
        """Renders the page with semi-transparent bounding boxes over detected redaction targets."""
        base_img = self.render_page_image(page)
        base_img = base_img.convert("RGBA")

        # Create transparent overlay layer
        overlay = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        scale_x = base_img.width / page.rect.width if page.rect.width > 0 else 1.0
        scale_y = base_img.height / page.rect.height if page.rect.height > 0 else 1.0

        for t in targets:
            if t.page_num != page.number:
                continue

            x0, y0, x1, y1 = t.bbox
            sx0 = x0 * scale_x
            sy0 = y0 * scale_y
            sx1 = x1 * scale_x
            sy1 = y1 * scale_y

            # Choose color based on category
            if t.category == "author_block":
                fill_color = (239, 68, 68, 80)       # Soft crimson
                outline_color = (220, 38, 38, 220)
            elif t.category == "email":
                fill_color = (59, 130, 246, 80)      # Soft azure
                outline_color = (37, 99, 235, 220)
            elif t.category == "orcid":
                fill_color = (16, 185, 129, 80)      # Soft emerald
                outline_color = (5, 150, 105, 220)
            elif t.category == "footnote":
                fill_color = (168, 85, 247, 80)      # Soft purple
                outline_color = (147, 51, 234, 220)
            else:
                fill_color = (245, 158, 11, 80)      # Soft amber
                outline_color = (217, 119, 6, 220)

            # Draw filled rectangle with outline
            draw.rectangle([sx0, sy0, sx1, sy1], fill=fill_color, outline=outline_color, width=2)

        # Composite base and overlay
        composited = Image.alpha_composite(base_img, overlay)
        return composited.convert("RGB")

    def generate_side_by_side_previews(
        self,
        doc_bytes: bytes,
        targets: List[RedactionTarget],
        redacted_doc_bytes: bytes,
        page_num: int = 0,
    ) -> Tuple[Image.Image, Image.Image]:
        """Generates a tuple of (Original with Overlays, Redacted Preview) for side-by-side inspection."""
        orig_doc = fitz.open(stream=doc_bytes, filetype="pdf")
        clean_doc = fitz.open(stream=redacted_doc_bytes, filetype="pdf")

        if page_num >= len(orig_doc):
            page_num = 0

        orig_page = orig_doc[page_num]
        overlay_img = self.render_detection_overlay(orig_page, targets)

        clean_page = clean_doc[page_num] if page_num < len(clean_doc) else orig_page
        redacted_img = self.render_page_image(clean_page)

        orig_doc.close()
        clean_doc.close()

        return overlay_img, redacted_img
