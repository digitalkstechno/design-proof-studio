"""Regression coverage for image decoding, preview and final proof uploads."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app
from app.renderer import RenderError, open_image


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
