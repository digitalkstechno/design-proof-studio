"""Exercise real binary stitch files, conversion isolation and Wilcom protocol."""
import base64
import io
import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs
from xml.etree import ElementTree as ET

import httpx
from PIL import Image
from fastapi.testclient import TestClient
from pyembroidery import EmbPattern, STITCH, JUMP, COLOR_CHANGE, END

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app
from app.formats import LOCAL_EMBROIDERY, WILCOM_FORMATS, format_catalogue
from app.embroidery import stitch_image, InvalidEmbroidery
from app.uploads import open_upload, local_stitch_png, wilcom_png, ConversionFailed, ConversionUnavailable
from app.renderer import RenderError

FIELDS = dict(category='Test', subcategory='Embroidery', design_type='Stitch file', design_id='embroidery-test', seller='Test')
WRITABLE = ('dst', 'pes', 'pec', 'exp', 'jef', 'vp3', 'xxx', 'u01', 'tbf', 'pmv')


def pattern():
    p = EmbPattern()
    p.add_thread('#ff0000')
    p.add_thread('#0000ff')
    for cmd, x, y in [(JUMP, 0, 0), (STITCH, 0, 0), (STITCH, 100, 0),
                      (STITCH, 100, 100), (COLOR_CHANGE, 100, 100), (JUMP, 200, 0),
                      (STITCH, 200, 0), (STITCH, 300, 0), (STITCH, 300, 100), (END, 300, 100)]:
        p.add_stitch_absolute(cmd, x, y)
    return p


def binary_design(extension):
    spec = LOCAL_EMBROIDERY[extension]
    out = io.BytesIO()
    design = pattern()
    if extension == 'pmv':
        # PMV is a single programmable stitch motif, not a multicolor design.
        design = EmbPattern()
        for x, y in ((0, 0), (10, 10), (20, 0), (30, 10)):
            design.add_stitch_absolute(STITCH, x, y)
        design.end()
    EmbPattern.write_embroidery(spec['writer'], design, out)
    return out.getvalue()


def png_bytes():
    output = io.BytesIO()
    Image.new('RGBA', (32, 32), 'red').save(output, 'PNG')
    return output.getvalue()


class EmbroideryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_catalogue_matches_real_readers_and_aliases(self):
        self.assertGreaterEqual(len(LOCAL_EMBROIDERY), 40)
        self.assertNotIn('s', LOCAL_EMBROIDERY)  # upstream SPX aliases are a string
        for ext in ('spx', 'exy', 'e00', 'fxy', 'f00', 'zxy', 'z00', 'u00', 'u01'):
            self.assertIn(ext, LOCAL_EMBROIDERY)
        self.assertFalse(set(LOCAL_EMBROIDERY) & set(WILCOM_FORMATS))
        with patch.dict(os.environ, {}, clear=True):
            catalogue = self.client.get('/api/v1/formats').json()
            formats = catalogue['formats']
            self.assertTrue(all(any(ext in f['extensions'] and f['available'] for f in formats) for ext in LOCAL_EMBROIDERY))
            self.assertFalse(next(f for f in formats if 'emb' in f['extensions'])['available'])
            for ext in ('col', 'edr', 'inf', 'csv', 'gcode', 'json'):
                self.assertFalse(any(ext in f['extensions'] and f['available'] for f in formats))
        with patch.dict(os.environ, {'PROOF_WILCOM_APP_ID': 'test', 'PROOF_WILCOM_APP_KEY': 'test'}, clear=True):
            self.assertTrue(next(f for f in format_catalogue()['formats'] if 'emb' in f['extensions'])['available'])

    def test_real_binary_formats_preview_and_render_for_both_roles(self):
        for extension in WRITABLE:
            with self.subTest(extension=extension):
                data = binary_design(extension)
                first = open_upload(data, 'Design', f'DESIGN.{extension.upper()}')
                second = open_upload(data, 'Design', f'design.{extension}')
                self.assertEqual(first.tobytes(), second.tobytes())
                self.assertEqual(first.info['proof_input_format'], extension.upper())
                self.assertIsNotNone(first.getbbox())
                for role in ('design', 'logo'):
                    response = self.client.post('/api/v1/preview-image', data={'role': role},
                        files={'image': (f'file.{extension}', data, 'application/octet-stream')})
                    self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else '')
                    self.assertEqual(response.headers['x-input-format'], extension.upper())
                    with Image.open(io.BytesIO(response.content)) as image:
                        self.assertEqual(image.mode, 'RGBA')
                        self.assertIsNotNone(image.getbbox())
                rendered = self.client.post('/api/v1/render', data=FIELDS, files={
                    'design': (f'design.{extension}', data), 'logo': (f'logo.{extension}', data)})
                self.assertEqual(rendered.status_code, 200)
                self.assertEqual(rendered.headers['x-design-input-format'], extension.upper())
                with Image.open(io.BytesIO(rendered.content)) as image:
                    image.verify()

    def test_every_reader_rejects_empty_input(self):
        for extension in LOCAL_EMBROIDERY:
            with self.subTest(extension=extension):
                with self.assertRaises(InvalidEmbroidery):
                    stitch_image(b'', extension)

    def test_headerless_exp_accepts_valid_printable_coordinate_bytes(self):
        # EXP has no signature: these ASCII-looking bytes are legitimate stitches.
        image = stitch_image(b'dddddd', 'exp')
        self.assertIsNotNone(image.getbbox())

    def test_missing_converter_and_project_formats_have_actionable_errors(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.uploads.httpx.stream') as network:
            for endpoint, field in (('/api/v1/preview-image', 'image'), ('/api/v1/render', 'design')):
                for extension, status in (('emb', 503), ('emt', 503), ('art', 422), ('jan', 422), ('pxf', 422), ('cdr', 422), ('vip', 422)):
                    with self.subTest(endpoint=endpoint, extension=extension):
                        response = self.client.post(endpoint, data=FIELDS, files={field: (f'design.{extension}', b'project bytes')})
                        self.assertEqual(response.status_code, status)
                        self.assertIn('PNG/BMP', response.json()['detail'])
            network.assert_not_called()

    def test_stitch_colors_jumps_and_needles(self):
        data = binary_design('pes')
        image = stitch_image(data, 'pes')
        colors = {color for _, color in image.getcolors(image.width * image.height)}
        # PES maps colors to its machine thread palette; retain the decoded colors.
        self.assertTrue(any(r > 200 and g < 50 and b < 50 and a == 255 for r, g, b, a in colors))
        self.assertTrue(any(r < 50 and g < 100 and b > 100 and a == 255 for r, g, b, a in colors))
        # Space between the two shapes stays transparent: never draw jumps.
        self.assertEqual(image.getpixel((800, 20))[3], 0)
        # Formats without colors have a deterministic fallback across processes.
        a = open_upload(binary_design('exp'), 'Design', 'design.exp')
        b = open_upload(binary_design('exp'), 'Design', 'design.exp')
        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertIn((48, 48, 48, 255), {color for _, color in a.getcolors(a.width * a.height)})

    def test_worker_timeout_and_invalid_geometry(self):
        with patch('app.uploads.subprocess.run', side_effect=subprocess.TimeoutExpired('decoder', 20)):
            with self.assertRaisesRegex(RenderError, 'too long'):
                local_stitch_png(binary_design('dst'), 'dst')
        with patch('app.embroidery.MAX_COMMANDS', 3):
            with self.assertRaises(InvalidEmbroidery):
                stitch_image(binary_design('pes'), 'pes')
        with patch('app.embroidery.MAX_COORDINATE', 10):
            with self.assertRaisesRegex(InvalidEmbroidery, 'coordinates'):
                stitch_image(binary_design('pes'), 'pes')
        response = self.client.post('/api/v1/preview-image', files={'image': ('bad.pes', b'\x00corrupt')})
        self.assertEqual(response.status_code, 422)

    def test_raster_signature_and_limits_win_over_renamed_extensions(self):
        self.assertEqual(open_upload(png_bytes(), 'Design', 'renamed.emb').size, (32, 32))
        with patch('app.renderer.MAX_SOURCE_PIXELS', 10), patch('app.uploads.local_stitch_png') as decoder:
            with self.assertRaisesRegex(RenderError, '40 million'):
                open_upload(png_bytes(), 'Design', 'renamed.dst')
            decoder.assert_not_called()


class WilcomTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'PROOF_WILCOM_APP_ID': 'test-id', 'PROOF_WILCOM_APP_KEY': 'test-key'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    @staticmethod
    @contextmanager
    def response(status=200, content=None):
        if content is None:
            b64 = base64.b64encode(png_bytes()).decode()
            content = f'<xml><files><file filename="Default.png" filecontents="{b64}" /></files></xml>'.encode()
        yield httpx.Response(status, content=content)

    def test_documented_xml_request_and_png_response(self):
        with patch('app.uploads.httpx.stream', return_value=self.response()) as request:
            image = open_upload(b'\xd0\xcf\x11\xe0native project', 'Design', 'original.emb')
        self.assertEqual(image.size, (32, 32))
        self.assertEqual(image.info['proof_input_format'], 'EMB')
        args, kwargs = request.call_args
        self.assertEqual(args[1], 'https://public.ewa.wilcomapps.com/api/designTrueview')
        posted = parse_qs(kwargs['content'].decode())
        self.assertEqual(posted['appId'], ['test-id'])
        xml = ET.fromstring(posted['requestXml'][0])
        self.assertEqual(xml.find('design').get('file'), 'design.emb')
        self.assertEqual(base64.b64decode(xml.find('files/file').get('filecontents')), b'\xd0\xcf\x11\xe0native project')
        self.assertFalse(kwargs['follow_redirects'])

    def test_errors_are_safe_and_typed(self):
        for status, error in ((401, ConversionUnavailable), (403, ConversionUnavailable), (400, RenderError), (500, ConversionFailed)):
            with self.subTest(status=status), patch('app.uploads.httpx.stream', return_value=self.response(status, b'secret-provider-message')):
                with self.assertRaises(error) as exc:
                    wilcom_png(b'project', 'emb')
                self.assertNotIn('secret-provider', str(exc.exception))
        for xml in (b'<bad', b'<xml/>', b'<!DOCTYPE xml><xml/>', b'<xml><files><file filename="a.png" filecontents="!!"/></files></xml>'):
            with self.subTest(xml=xml), patch('app.uploads.httpx.stream', return_value=self.response(content=xml)):
                with self.assertRaises(ConversionFailed):
                    wilcom_png(b'project', 'emb')
        with patch('app.uploads.httpx.stream', side_effect=httpx.ReadTimeout('secret')):
            with self.assertRaises(ConversionFailed):
                wilcom_png(b'project', 'emb')

    def test_encoded_size_and_https_enforced_before_network(self):
        with patch('app.uploads.MAX_WILCOM_REQUEST_BYTES', 10), patch('app.uploads.httpx.stream') as network:
            with self.assertRaisesRegex(RenderError, '20 MB'):
                wilcom_png(b'project', 'emb')
            network.assert_not_called()
        with patch.dict(os.environ, {'PROOF_WILCOM_URL': 'http://example.test/converter'}), patch('app.uploads.httpx.stream') as network:
            with self.assertRaises(ConversionUnavailable):
                wilcom_png(b'project', 'emb')
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
