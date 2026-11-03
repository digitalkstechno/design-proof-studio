"""Regression coverage for image decoding, preview and final proof uploads."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app
from app.renderer import RenderError, _watermark, _watermark_logo, open_image


FORMATS = ("PNG", "JPEG", "WEBP", "BMP", "DIB", "GIF", "TIFF", "ICO")
FIELDS = dict(category="Test", subcategory="Upload", design_type="Artwork",
              design_id="format-test", seller="Test Seller")


def image_bytes(fmt, size=(32, 32), color="red", **options):
    output = io.BytesIO()
    if fmt == "WEBP":
        options.setdefault("lossless", True)
    Image.new("RGB", size, color).save(output, format=fmt, **options)
    return output.getvalue()


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_all_formats_decode_for_artwork_and_logo(self):
        for fmt in FORMATS:
            for label in ("Design", "Logo"):
                with self.subTest(format=fmt, label=label):
                    decoded = open_image(image_bytes(fmt), label)
                    self.assertEqual(decoded.size, (32, 32))
                    self.assertEqual(decoded.mode, "RGBA")

    def test_all_formats_preview_as_png_for_both_roles(self):
        for fmt in FORMATS:
            for role in ("design", "logo"):
                with self.subTest(format=fmt, role=role):
                    response = self.client.post(
                        "/api/v1/preview-image", data={"role": role},
                        files={"image": ("upload." + fmt.lower(), image_bytes(fmt), "application/octet-stream")})
                    self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else "")
                    self.assertEqual(response.headers["content-type"], "image/png")
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    with Image.open(io.BytesIO(response.content)) as preview:
                        self.assertEqual(preview.format, "PNG")
                        self.assertEqual(preview.size, (32, 32))

    def test_all_formats_render_with_logo_override(self):
        for fmt in FORMATS:
            with self.subTest(format=fmt):
                data = image_bytes(fmt)
                response = self.client.post("/api/v1/render", data=FIELDS, files={
                    "design": ("artwork." + fmt.lower(), data, "application/octet-stream"),
                    "logo": ("logo." + fmt.lower(), data, "application/octet-stream"),
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], "image/png")
                self.assertEqual(response.headers["x-source-design-width"], "32")
                self.assertEqual(response.headers["x-source-design-height"], "32")
                with Image.open(io.BytesIO(response.content)) as proof:
                    proof.verify()

    def test_bmp_with_default_logo(self):
        response = self.client.post("/api/v1/render", data=FIELDS,
            files={"design": ("artwork.bmp", image_bytes("BMP"), "image/bmp")})
        self.assertEqual(response.status_code, 200)

    def test_first_frame_and_page_match_preview(self):
        for fmt in ("GIF", "TIFF", "WEBP", "PNG"):
            with self.subTest(format=fmt):
                data = image_bytes(fmt, save_all=True,
                    append_images=[Image.new("RGB", (32, 32), "blue")], duration=100)
                self.assertEqual(open_image(data, "Design").getpixel((0, 0)), (255, 0, 0, 255))
                response = self.client.post("/api/v1/preview-image", files={"image": ("image", data)})
                self.assertEqual(response.status_code, 200)
                with Image.open(io.BytesIO(response.content)) as preview:
                    self.assertEqual(preview.getpixel((0, 0)), (255, 0, 0, 255))

    def test_transparency_and_exif_orientation_preserved(self):
        for fmt in ("PNG", "WEBP", "TIFF", "ICO"):
            with self.subTest(format=fmt):
                output = io.BytesIO()
                Image.new("RGBA", (32, 32), (255, 0, 0, 0)).save(output, fmt)
                self.assertEqual(open_image(output.getvalue(), "Design").getpixel((0, 0))[3], 0)
        exif = Image.Exif()
        exif[274] = 6
        self.assertEqual(open_image(image_bytes("JPEG", size=(32, 16), exif=exif), "Design").size, (16, 32))

    def test_rejects_empty_corrupt_and_unsupported_content(self):
        for data in (b"", b"not an image", b"BMbroken", image_bytes("PPM"), b"<svg/>", b"%PDF-1.7"):
            for endpoint, field in (("/api/v1/preview-image", "image"), ("/api/v1/render", "design")):
                with self.subTest(data=data[:12], endpoint=endpoint):
                    response = self.client.post(endpoint, data=FIELDS,
                        files={field: ("fake.png", data, "image/png")})
                    self.assertEqual(response.status_code, 422)

    def test_limits_apply_to_new_formats(self):
        data = image_bytes("BMP")
        with patch("app.renderer.MAX_UPLOAD_BYTES", len(data) - 1):
            with self.assertRaisesRegex(RenderError, "25 MB"):
                open_image(data, "Design")
        with patch("app.renderer.MAX_SOURCE_PIXELS", 100):
            with self.assertRaisesRegex(RenderError, "40 million"):
                open_image(data, "Design")
        with patch("app.renderer.MAX_EDGE", 16):
            with self.assertRaisesRegex(RenderError, "30,000"):
                open_image(data, "Design")
        with patch("app.renderer.MAX_LOGO_INPUT_PIXELS", 100):
            with self.assertRaisesRegex(RenderError, "100-million"):
                open_image(data, "Logo")
        for endpoint, field in (("/api/v1/preview-image", "image"), ("/api/v1/render", "design")):
            with patch("app.main.MAX_UPLOAD_BYTES", 100), patch("app.renderer.MAX_UPLOAD_BYTES", 100):
                response = self.client.post(endpoint, data=FIELDS, files={field: ("large.bmp", data)})
                self.assertEqual(response.status_code, 422)
                self.assertIn("25 MB", response.json()["detail"])

    def _render(self, design_data, *, logo_data=None, opacity="0.16", scope="artwork", filename="artwork.png"):
        files = {"design": (filename, design_data, "application/octet-stream")}
        if logo_data is not None:
            files["logo"] = ("logo.png", logo_data, "image/png")
        return self.client.post("/api/v1/render", data={
            **FIELDS, "watermark_opacity": opacity, "watermark_scope": scope,
        }, files=files)

    def _watermark_changed_pixels(self, design_data, *, logo_data=None, filename="artwork.png"):
        with_mark = self._render(design_data, logo_data=logo_data, opacity="0.16", filename=filename)
        without_mark = self._render(design_data, logo_data=logo_data, opacity="0", filename=filename)
        self.assertEqual(with_mark.status_code, 200, with_mark.text[:300])
        self.assertEqual(without_mark.status_code, 200, without_mark.text[:300])
        marked = Image.open(io.BytesIO(with_mark.content)).convert("RGB")
        plain = Image.open(io.BytesIO(without_mark.content)).convert("RGB")
        diff = ImageChops.difference(marked, plain)
        pixels = diff.get_flattened_data() if hasattr(diff, "get_flattened_data") else diff.getdata()
        return diff.getbbox(), sum(pixel != (0, 0, 0) for pixel in pixels)

    def test_watermark_is_actually_present_for_every_supported_design_format(self):
        for fmt in FORMATS:
            with self.subTest(format=fmt):
                bbox, changed = self._watermark_changed_pixels(
                    image_bytes(fmt, size=(640, 420), color=(245, 245, 245)),
                    filename="artwork." + fmt.lower(),
                )
                self.assertIsNotNone(bbox)
                self.assertGreater(changed, 1000)

    def test_watermark_survives_light_dark_and_extreme_aspect_ratios(self):
        cases = (
            ((700, 450), "white"),
            ((700, 450), "black"),
            ((2000, 150), "white"),
            ((150, 2000), "white"),
        )
        for size, color in cases:
            with self.subTest(size=size, color=color):
                bbox, changed = self._watermark_changed_pixels(image_bytes("PNG", size=size, color=color))
                self.assertIsNotNone(bbox)
                self.assertGreater(changed, 100)

    def test_contrast_layer_is_aligned_with_logo_without_ghost_pixels(self):
        logo = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((3, 2, 36, 17), fill=(0, 93, 12, 255))
        mark = _watermark_logo(logo, 40, 0.16)
        width, height = 100, 70
        x = max(2, round(mark.width * 0.10))
        y = round((height - mark.height) / 2)
        allowed = Image.new("L", (width, height), 0)
        allowed.paste(mark.getchannel("A"), (x, y))
        allowed = allowed.point(lambda pixel: 255 if pixel else 0)

        for color in ((255, 255, 255, 255), (0, 0, 0, 255)):
            with self.subTest(color=color):
                image = Image.new("RGBA", (width, height), color)
                before = image.copy()
                _watermark(image, logo, (0, 0, width, height), 1.0, 0.16)
                diff = ImageChops.difference(image.convert("RGB"), before.convert("RGB"))
                changed = diff.convert("L").point(lambda pixel: 255 if pixel else 0)
                self.assertIsNotNone(changed.getbbox())
                self.assertIsNone(ImageChops.subtract(changed, allowed).getbbox())

    def test_watermark_remains_detectable_at_small_card_thumbnail_size(self):
        for color in ((250, 250, 248), (8, 12, 10)):
            with self.subTest(color=color):
                data = image_bytes("PNG", size=(900, 700), color=color)
                marked_response = self._render(data, opacity="0.16")
                plain_response = self._render(data, opacity="0")
                self.assertEqual(marked_response.status_code, 200)
                self.assertEqual(plain_response.status_code, 200)
                marked = Image.open(io.BytesIO(marked_response.content)).convert("RGB")
                plain = Image.open(io.BytesIO(plain_response.content)).convert("RGB")
                marked.thumbnail((250, 250), Image.Resampling.LANCZOS)
                plain.thumbnail((250, 250), Image.Resampling.LANCZOS)
                diff = ImageChops.difference(marked, plain)
                pixels = diff.get_flattened_data() if hasattr(diff, "get_flattened_data") else diff.getdata()
                changed = sum(pixel != (0, 0, 0) for pixel in pixels)
                peak = max(max(pixel) for pixel in pixels)
                self.assertGreater(changed, 1000)
                self.assertGreater(peak, 20)

    def test_watermark_is_present_across_common_pixel_modes(self):
        cases = []
        for mode, color in (("L", 210), ("LA", (210, 255)), ("RGB", (210, 220, 230)), ("RGBA", (210, 220, 230, 255))):
            output = io.BytesIO()
            Image.new(mode, (640, 420), color).save(output, "PNG")
            cases.append((mode, output.getvalue(), "artwork.png"))
        output = io.BytesIO()
        Image.new("CMYK", (640, 420), (20, 5, 0, 10)).save(output, "JPEG")
        cases.append(("CMYK", output.getvalue(), "artwork.jpg"))
        palette = Image.new("P", (640, 420), 1)
        palette.putpalette([255, 255, 255, 30, 180, 70] + [0, 0, 0] * 254)
        output = io.BytesIO()
        palette.save(output, "PNG")
        cases.append(("P", output.getvalue(), "artwork.png"))

        for mode, data, filename in cases:
            with self.subTest(mode=mode):
                bbox, changed = self._watermark_changed_pixels(data, filename=filename)
                self.assertIsNotNone(bbox)
                self.assertGreater(changed, 1000)

    def test_render_reports_watermark_status_headers(self):
        data = image_bytes("PNG", size=(640, 420), color="white")
        marked = self._render(data, opacity="0.16")
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.headers["x-watermark-applied"], "true")
        self.assertEqual(marked.headers["x-watermark-scope"], "artwork")
        self.assertEqual(marked.headers["x-watermark-opacity"], "0.1600")

        plain = self._render(data, opacity="0")
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(plain.headers["x-watermark-applied"], "false")

        page = self._render(data, opacity="0.16", scope="page")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["x-watermark-applied"], "true")
        self.assertEqual(page.headers["x-watermark-scope"], "page")

    def test_opaque_white_logo_is_not_erased_and_remains_visible_on_white_artwork(self):
        logo = io.BytesIO()
        Image.new("RGBA", (300, 100), (255, 255, 255, 255)).save(logo, "PNG")
        bbox, changed = self._watermark_changed_pixels(
            image_bytes("PNG", size=(700, 450), color="white"), logo_data=logo.getvalue()
        )
        self.assertIsNotNone(bbox)
        self.assertGreater(changed, 100)

    def test_fully_transparent_logo_is_rejected_instead_of_silently_omitting_watermark(self):
        logo = io.BytesIO()
        Image.new("RGBA", (300, 100), (0, 0, 0, 0)).save(logo, "PNG")
        response = self._render(image_bytes("PNG", size=(700, 450), color="white"), logo_data=logo.getvalue())
        self.assertEqual(response.status_code, 422)
        self.assertIn("visible pixels", response.json()["detail"].lower())

    def test_preview_logo_downsampling_and_role_validation(self):
        data = image_bytes("TIFF", size=(2050, 32))
        for role, expected_width in (("logo", 2048), ("design", 2050)):
            response = self.client.post("/api/v1/preview-image", data={"role": role}, files={"image": ("logo.tiff", data)})
            self.assertEqual(response.status_code, 200)
            with Image.open(io.BytesIO(response.content)) as preview:
                self.assertEqual(preview.width, expected_width)
        response = self.client.post("/api/v1/preview-image", data={"role": "invalid"}, files={"image": ("logo.tiff", data)})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
