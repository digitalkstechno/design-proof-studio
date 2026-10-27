"""Render uploaded artwork into a consistent branded proof sheet.

The uploaded original is never modified. A display copy is normalized to a
1200 px artwork width with aspect ratio preserved and high-quality LANCZOS
resampling so proof geometry and typography remain stable across source sizes.
The subtle tiled watermark is an intentional overlay.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

MAX_SOURCE_PIXELS = 40_000_000
MAX_PAGE_PIXELS = 85_000_000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_EDGE = 30_000
MAX_LOGO_INPUT_PIXELS = 100_000_000
LOGO_RENDER_EDGE = 2048
STANDARD_ARTWORK_WIDTH = 1200
SIDE_PADDING = 18
SUPPORTED_IMAGE_FORMATS = ("PNG", "JPEG", "WEBP", "BMP", "DIB", "GIF", "TIFF", "ICO")
SUPPORTED_IMAGE_LABEL = "PNG, JPEG, WebP, BMP, GIF, TIFF or ICO"


class RenderError(ValueError):
    pass


@dataclass(frozen=True)
class ProofStyle:
    category_title_size: float = 31.0
    category_value_size: float = 25.5
    design_id_title_size: float = 19.0
    design_id_value_size: float = 23.0
    seller_title_size: float = 17.0
    seller_value_size: float = 18.5
    warning_title_size: float = 22.0
    warning_subtitle_size: float = 11.5
    footer_label_size: float = 14.5
    company_name_size: float = 23.0
    company_website_size: float = 16.0
    support_title_size: float = 29.0
    support_subtitle_size: float = 31.0
    logo_scale: float = 1.03


@dataclass(frozen=True)
class ProofFields:
    category: str
    subcategory: str
    design_type: str
    design_id: str
    seller: str
    company_name: str = "NLC Design"
    company_website: str = "www.nlcdesign.in"
    watermark_opacity: float = 0.16
    watermark_size: float = 1.25
    watermark_spacing: float = 1.35
    watermark_scope: str = "artwork"
    style: ProofStyle = ProofStyle()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FONT_DIR = PROJECT_ROOT / "fonts"

_PROJECT_FONT_FILES = {
    "regular": ["Proof-Regular.ttf", "Arial.ttf"],
    "bold": ["Proof-Bold.ttf", "Arial Bold.ttf"],
    "italic": ["Proof-Italic.ttf", "Georgia Italic.ttf"],
    "script": ["Proof-Script.ttf", "Proof-Script.otf", "Proof-Script.ttc", "SignPainter.ttc"],
}

_FONT_CANDIDATES = {
    "regular": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ],
    "bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ],
    "italic": [
        "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
        "/Library/Fonts/Georgia Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    ],
    "script": [
        "/System/Library/Fonts/Supplemental/SignPainter.ttc",
        "/Library/Fonts/SignPainter.ttc",
        "/System/Library/Fonts/Supplemental/Brush Script.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
    ],
}


def _font_env_key(kind: str) -> str:
    return {"bold": "PROOF_FONT_BOLD", "italic": "PROOF_FONT_ITALIC",
            "script": "PROOF_FONT_SCRIPT"}.get(kind, "PROOF_FONT_REGULAR")


def _font_dir() -> Path:
    configured = os.environ.get("PROOF_FONT_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_FONT_DIR


def _font_paths(kind: str) -> list[tuple[str, str]]:
    env_path = os.environ.get(_font_env_key(kind), "").strip()
    paths: list[tuple[str, str]] = []
    if env_path:
        paths.append((env_path, "env"))
    font_dir = _font_dir()
    paths.extend((str(font_dir / name), "project") for name in _PROJECT_FONT_FILES[kind])
    paths.extend((path, "system") for path in _FONT_CANDIDATES[kind])
    return paths


def resolved_font(kind: str) -> tuple[str | None, str]:
    for path, source in _font_paths(kind):
        if not path or not Path(path).is_file():
            continue
        try:
            ImageFont.truetype(path, size=12)
            return path, source
        except OSError:
            continue
    return None, "pillow-default"


def font_status() -> dict[str, dict[str, str | bool | None]]:
    result: dict[str, dict[str, str | bool | None]] = {}
    for kind in ("regular", "bold", "italic", "script"):
        path, source = resolved_font(kind)
        result[kind] = {
            "source": source,
            "file": Path(path).name if path else None,
            "configured": source in {"env", "project"},
        }
    return result


def font(size: float, kind: str = "regular") -> ImageFont.ImageFont:
    size = max(9, int(round(size)))
    for path, _source in _font_paths(kind):
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def open_image(data: bytes, label: str) -> Image.Image:
    if not data:
        raise RenderError(f"{label} is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise RenderError(f"{label} is larger than 25 MB.")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.format not in SUPPORTED_IMAGE_FORMATS:
                raise RenderError(f"{label} must be a {SUPPORTED_IMAGE_LABEL} image.")
            # Use the first frame/page for a stable, static proof and preview.
            opened.seek(0)
            w, h = opened.size
            if label == "Logo":
                # Logos are only displayed as small marks. Downsample oversized
                # uploads in memory instead of rejecting otherwise usable logos.
                if not (0 < w <= 40_000 and 0 < h <= 40_000) or w * h > MAX_LOGO_INPUT_PIXELS:
                    raise RenderError("Logo exceeds the 100-million-pixel safety limit. Export it at 2048 px or smaller and upload again.")
                if opened.format == "JPEG":
                    opened.draft("RGB", (LOGO_RENDER_EDGE, LOGO_RENDER_EDGE))
                opened.load()
                image = ImageOps.exif_transpose(opened)
                if max(image.size) > LOGO_RENDER_EDGE:
                    image.thumbnail((LOGO_RENDER_EDGE, LOGO_RENDER_EDGE), Image.Resampling.LANCZOS)
                return image.convert("RGBA")
            if not (0 < w <= MAX_EDGE and 0 < h <= MAX_EDGE) or w * h > MAX_SOURCE_PIXELS:
                raise RenderError(f"{label} is too large (maximum 40 million pixels and 30,000 px per side).")
            opened.load()
            image = ImageOps.exif_transpose(opened)
            return image.convert("RGBA")
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, RenderError):
            raise
        raise RenderError(f"{label} is not a valid supported image.") from exc


def _fit(im: Image.Image, bounds: tuple[int, int]) -> Image.Image:
    """Logo only: preserve aspect ratio, never upscale its small originals."""
    w, h = im.size
    scale = min(bounds[0] / w, bounds[1] / h, 1.0)
    new = (max(1, round(w * scale)), max(1, round(h * scale)))
    return im if new == im.size else im.resize(new, Image.Resampling.LANCZOS)


def _wrapped(text: str, f: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=f) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            if draw.textlength(word, font=f) <= width:
                line = word
                continue
            for char in word:
                if line and draw.textlength(line + char, font=f) > width:
                    lines.append(line)
                    line = ""
                line += char
        if line:
            lines.append(line)
    return lines or [""]


def _text_block(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int],
                size: float, kind: str = "regular", color: str = "#17191D",
                align: str = "left", max_lines: int = 3, min_size: int = 9) -> None:
    x, y, max_w, max_h = rect
    for pt in range(max(9, round(size)), min_size - 1, -1):
        f = font(pt, kind)
        lines = _wrapped(text, f, max_w, draw)
        line_h = max(11, round(pt * 1.22))
        if len(lines) <= max_lines and len(lines) * line_h <= max_h:
            break
    else:
        raise RenderError("A text field is too long to fit the header. Shorten the text.")
    for i, line in enumerate(lines):
        line_w = draw.textlength(line, font=f)
        line_x = x if align == "left" else x + (max_w - line_w) / 2 if align == "center" else x + max_w - line_w
        draw.text((round(line_x), y + i * line_h), line, font=f, fill=color, stroke_width=0)


def _watermark_logo(logo: Image.Image, target_width: int, opacity: float) -> Image.Image:
    """Keep uploaded logo's actual colors and proportions; only vary opacity.

    A completely opaque logo with a white paper background is a common export
    mistake. If at least 3 corners are white, remove that *background* smoothly
    so it does not appear as a pale rectangular tile. A transparent logo keeps
    its authored transparency and colors exactly as supplied.
    """
    if not 0 <= opacity <= 1:
        raise RenderError("Watermark opacity must be between 0 and 1.")
    target_width = max(1, round(target_width))
    # Unlike the header logo, watermark size MUST be adjustable even if the
    # source logo is smaller than the desired stamp width.
    target_height = max(1, round(logo.height * target_width / logo.width))
    thumb = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)
    source_a = thumb.getchannel("A")
    # Do not accidentally erase opaque white details inside a transparent logo.
    if source_a.getextrema() == (255, 255):
        corners = [thumb.getpixel(pt)[:3] for pt in ((0, 0), (thumb.width - 1, 0),
                    (0, thumb.height - 1), (thumb.width - 1, thumb.height - 1))]
        white_corners = sum(all(c >= 245 for c in rgb) for rgb in corners)
        if white_corners >= 3:
            # White background -> alpha=0; colored logo ink stays original RGB.
            matte = ImageOps.grayscale(thumb.convert("RGB"))
            source_a = matte.point(lambda v: round(max(0, min(1, (248 - v) / 24)) * 255))
    alpha = source_a.point(lambda a: round(a * opacity))
    original_colors = thumb.copy()
    original_colors.putalpha(alpha)
    return original_colors.rotate(28, expand=True, resample=Image.Resampling.BICUBIC)


def _watermark(page: Image.Image, logo: Image.Image, box: tuple[int, int, int, int], scale: float,
               opacity: float, size: float = 1.0, spacing: float = 1.0) -> None:
    """Tile fully visible watermark marks with balanced, size-aware edge spacing.

    The old grid began at negative X/Y coordinates, so the first/last marks were
    intentionally clipped by the proof boundary. That looked accidental and also
    made the first row react poorly to watermark-size changes. This layout keeps
    every visible mark inside a small safe area and distributes rows across the
    available height while preserving the requested spacing as closely as possible.
    """
    if opacity <= 0:
        return

    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return

    region_w = x1 - x0
    region_h = y1 - y0
    width = max(40, round(region_w * 0.145 * size))
    mark = _watermark_logo(logo, width, opacity)
    step_x = max(60, round(region_w * 0.16 * spacing))
    step_y = max(60, round(172 * scale * spacing))
    layer = Image.new("RGBA", (region_w, region_h), (255, 255, 255, 0))

    # Insets scale with the rotated mark, so changing watermark size also moves
    # the first/last rows naturally instead of leaving a fixed clipped row.
    side_inset = max(2, round(mark.width * 0.10))
    top_inset = max(2, round(mark.height * 0.14))
    bottom_inset = max(2, round(mark.height * 0.14))

    min_x = side_inset
    max_x = region_w - side_inset - mark.width
    min_y = top_inset
    max_y = region_h - bottom_inset - mark.height

    def paste_row(row_idx: int, y: float) -> None:
        # Very narrow areas still get one centered, fully visible mark.
        if max_x < min_x:
            x = max(0, round((region_w - mark.width) / 2))
            layer.alpha_composite(mark, (x, round(y)))
            return

        stagger = step_x / 2 if row_idx % 2 else 0
        x = min_x + stagger

        # If a staggered row cannot fit at least one mark, center one rather
        # than allowing it to be clipped at either horizontal edge.
        if x > max_x:
            x = (min_x + max_x) / 2

        while x <= max_x + 0.5:
            layer.alpha_composite(mark, (round(x), round(y)))
            x += step_x

    if max_y < min_y:
        # Short regions get one centered row with no clipping.
        y = max(0, round((region_h - mark.height) / 2))
        paste_row(0, y)
    else:
        vertical_span = max_y - min_y
        if vertical_span < step_y * 0.5:
            row_positions = [(min_y + max_y) / 2]
        else:
            # Use the closest whole number of intervals, then distribute the
            # rows exactly between safe top/bottom bounds. This prevents a
            # large arbitrary gap at the bottom while keeping spacing stable.
            intervals = max(1, round(vertical_span / step_y))
            actual_step = vertical_span / intervals
            row_positions = [min_y + i * actual_step for i in range(intervals + 1)]

        for row_idx, y in enumerate(row_positions):
            paste_row(row_idx, y)

    page.alpha_composite(layer, (x0, y0))


def normalized_artwork_size(source_w: int, source_h: int) -> tuple[int, int]:
    if source_w <= 0 or source_h <= 0:
        raise RenderError("Design image dimensions are invalid.")
    render_w = STANDARD_ARTWORK_WIDTH
    render_h = max(1, round(source_h * render_w / source_w))
    return render_w, render_h


def render_proof(design: Image.Image, logo: Image.Image, fields: ProofFields) -> Image.Image:
    source_w, source_h = design.size
    dw, dh = normalized_artwork_size(source_w, source_h)
    style = fields.style
    # All proof geometry uses one normalized display width. The uploaded source
    # remains untouched; only the proof copy is resampled for consistent layout.
    out_w = dw + SIDE_PADDING * 2
    s = max(0.70, min(1.60, out_w / 1400))
    # Typography now uses the same reference scale for every source resolution.
    # _text_block still shrinks unusually long strings only when necessary.
    type_scale = max(0.82, min(1.35, (out_w / 1236) ** 0.85))
    # Design Details title plus a two-line centered value block.
    details_text = f"{fields.category} | {fields.subcategory}\n{fields.design_type}"
    long_header = (
        len(fields.category) > 45
        or len(fields.subcategory) > 55
        or len(fields.design_type) > 55
        or len(fields.category) + len(fields.subcategory) + len(fields.design_type) > 120
        or len(fields.seller) > 50
        or len(fields.design_id) > 26
    )
    header_h = round((192 if long_header else 148) * s)
    before = round(20 * s)
    after = round(12 * s)
    long_footer = len(fields.company_name) > 30 or len(fields.company_website) > 36
    footer_h = round((195 if long_footer else 132) * s)
    out_h = header_h + before + dh + after + footer_h
    if out_w * out_h > MAX_PAGE_PIXELS or out_h > MAX_EDGE:
        raise RenderError("The final proof would be too large. Upload a smaller design image.")

    image_y = header_h + before
    footer_y = image_y + dh + after
    page = Image.new("RGBA", (out_w, out_h), "#FFFFFF")
    design_x = (out_w - dw) // 2
    display_design = design.resize((dw, dh), Image.Resampling.LANCZOS)
    page.alpha_composite(display_design, (design_x, image_y))
    if fields.watermark_scope == "page":
        wm_box = (0, 0, out_w, out_h)
    else:
        wm_box = (design_x, image_y, design_x + dw, image_y + dh)
    _watermark(page, logo, wm_box, s, fields.watermark_opacity,
               fields.watermark_size, fields.watermark_spacing)
    d = ImageDraw.Draw(page)
    dark = "#131719"
    green = "#145143"
    rule = "#A5A6A6"

    def sx(value: float) -> int:
        return round(value * s)

    pad = sx(33)
    left_end = round(out_w * 0.342)
    cat_end = round(out_w * 0.658)
    id_end = round(out_w * 0.814)
    top = sx(19)
    available_header = header_h - top - sx(12)

    logo_bounds = (max(1, round((left_end - 2 * pad) * style.logo_scale)), max(1, round(available_header * style.logo_scale)))
    display_logo = _fit(logo, logo_bounds)
    # Center the logo inside its header zone instead of pinning it to the left padding.
    logo_x = max(pad, round((left_end - display_logo.width) / 2))
    logo_y = top + max(0, (available_header - display_logo.height) // 2)
    page.alpha_composite(display_logo, (logo_x, logo_y))

    d.line((cat_end, top, cat_end, header_h - sx(15)), fill=rule, width=max(1, sx(1)))
    d.line((id_end, top, id_end, header_h - sx(15)), fill=rule, width=max(1, sx(1)))

    # Use symmetric inner padding and vertically center each complete
    # title + value stack inside the same header area as the centered logo.
    header_inner = sx(12)
    cat_x = left_end + header_inner
    cat_w = cat_end - left_end - header_inner * 2
    id_x = cat_end + header_inner
    id_w = id_end - cat_end - header_inner * 2
    seller_x = id_end + header_inner
    seller_w = out_w - id_end - header_inner * 2

    title_h = sx(34)
    stack_gap = sx(7)
    details_value_h = sx(72 if long_header else 52)
    id_value_h = sx(44 if long_header else 30)
    seller_value_h = sx(76 if long_header else 30)

    details_stack_h = title_h + stack_gap + details_value_h
    id_stack_h = title_h + stack_gap + id_value_h
    seller_stack_h = title_h + stack_gap + seller_value_h

    details_top = top + max(0, (available_header - details_stack_h) // 2)
    id_top = top + max(0, (available_header - id_stack_h) // 2)
    seller_top = top + max(0, (available_header - seller_stack_h) // 2)

    _text_block(
        d, "Design Details", (cat_x, details_top, cat_w, title_h),
        style.category_title_size * type_scale, kind="bold", align="center", max_lines=1, min_size=10,
    )
    _text_block(
        d, details_text,
        (cat_x, details_top + title_h + stack_gap, cat_w, details_value_h),
        style.category_value_size * type_scale, align="center",
        max_lines=3 if long_header else 2, min_size=9,
    )

    _text_block(
        d, "Design ID", (id_x, id_top, id_w, title_h),
        style.design_id_title_size * type_scale, align="center", min_size=10,
    )
    _text_block(
        d, fields.design_id,
        (id_x, id_top + title_h + stack_gap, id_w, id_value_h),
        style.design_id_value_size * type_scale, kind="bold", align="center", max_lines=3, min_size=9,
    )

    _text_block(
        d, "Seller", (seller_x, seller_top, seller_w, title_h),
        style.seller_title_size * type_scale, align="center", min_size=10,
    )
    _text_block(
        d, fields.seller,
        (seller_x, seller_top + title_h + stack_gap, seller_w, seller_value_h),
        style.seller_value_size * type_scale, kind="bold", align="center",
        max_lines=8 if long_header else 3, min_size=9,
    )

    warn_x, warn_y = pad, footer_y + sx(13)
    warn_w = round(out_w * 0.285)
    warn_h = footer_h - sx(29)
    d.rounded_rectangle((warn_x, warn_y, warn_x + warn_w, warn_y + warn_h), radius=sx(12), fill="#FCE5EA")
    dot_r = sx(22)
    dot_x, dot_y = warn_x + sx(40), warn_y + warn_h // 2
    d.ellipse((dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r), fill="#AE254A")
    ex_f = font(31 * type_scale, "bold")
    d.text((dot_x, dot_y - sx(2)), "!", font=ex_f, fill="white", anchor="mm")
    txt_x = warn_x + sx(78)
    txt_w = warn_w - sx(88)
    _text_block(d, "PREVIEW ONLY", (txt_x, warn_y + sx(17), txt_w, sx(30)),
                style.warning_title_size * type_scale, "bold", "#AC284D", min_size=10)
    _text_block(d, "DO NOT COPY OR USE FOR PRODUCTION", (txt_x, warn_y + sx(53), txt_w, sx(34)),
                style.warning_subtitle_size * type_scale, "bold", "#A32446", max_lines=2, min_size=8)

    middle_x = round(out_w * 0.378)
    middle_end = round(out_w * 0.627)
    d.line((middle_x, footer_y + sx(11), middle_x, out_h - sx(12)), fill=rule, width=max(1, sx(1)))
    d.line((middle_end, footer_y + sx(11), middle_end, out_h - sx(12)), fill=rule, width=max(1, sx(1)))
    mid_x, mid_w = middle_x + sx(8), middle_end - middle_x - sx(16)
    _text_block(d, "Original Design Available Only on", (mid_x, footer_y + sx(19), mid_w, sx(25)),
                style.footer_label_size * type_scale, align="center", min_size=8)
    _text_block(d, fields.company_name, (mid_x, footer_y + sx(47), mid_w, sx(81 if long_footer else 38)),
                style.company_name_size * type_scale, "bold", green, "center", max_lines=6 if long_footer else 2, min_size=9)
    _text_block(d, fields.company_website, (mid_x, footer_y + sx(136 if long_footer else 89), mid_w, sx(48 if long_footer else 32)),
                style.company_website_size * type_scale, color=green, align="center", max_lines=5 if long_footer else 2, min_size=9)

    # Use slanted brush-script lettering anchored close
    # to the RIGHT edge, with a separate upward green signature underline.
    right_x = middle_end + sx(18)
    right_w = max(1, out_w - right_x - pad)
    right_edge = out_w - pad - sx(5)
    text_center = right_edge - min(right_w * 0.26, sx(99))
    tilt_degrees = 9

    def script_line(text: str, requested_size: float, top: int) -> tuple[float, int, int]:
        point_size = max(9, round(requested_size * type_scale))
        # Leave room for the rotated glyphs; a large slider value must not
        # push ink outside the footer or across the section divider.
        available = max(1, right_w - sx(12))
        while point_size > 9:
            candidate = font(point_size, "script")
            if d.textlength(text, font=candidate) + point_size * 0.7 <= available:
                break
            point_size -= 1
        f = font(point_size, "script")
        bbox = d.textbbox((0, 0), text, font=f)
        gutter = max(4, round(point_size * 0.30))
        patch = Image.new("RGBA", (max(1, bbox[2] - bbox[0] + gutter * 2),
                                   max(1, bbox[3] - bbox[1] + gutter * 2)), (0, 0, 0, 0))
        pd = ImageDraw.Draw(patch)
        pd.text((gutter - bbox[0], gutter - bbox[1]), text, font=f, fill=dark)
        rotated = patch.rotate(tilt_degrees, resample=Image.Resampling.BICUBIC, expand=True)
        ink_box = rotated.getchannel("A").getbbox()
        if ink_box:
            rotated = rotated.crop(ink_box)
        # The signature is intentionally right-aligned, not placed
        # in the horizontal centre of the entire footer section.
        left = max(right_x, min(round(text_center - rotated.width / 2), out_w - pad - rotated.width))
        page.alpha_composite(rotated, (left, top))
        return (left + rotated.width / 2, rotated.width, rotated.height)

    script_line("Support Designers", style.support_title_size, footer_y + sx(16))
    buy_cx, buy_width, buy_height = script_line("Buy Original", style.support_subtitle_size,
                                               footer_y + sx(59))
    line_end = min(out_w - pad - sx(3), round(buy_cx + buy_width * 0.46))
    line_start = max(right_x + sx(6), round(buy_cx - buy_width * 0.16))
    line_y = min(out_h - sx(8), footer_y + sx(59) + buy_height + sx(6))
    rise = max(4, sx(12))
    d.line((line_start, line_y, line_end, line_y - rise),
           fill="#00A15A", width=max(2, sx(4)), joint="curve")

    return page.convert("RGB")


def png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=6)
    return output.getvalue()
