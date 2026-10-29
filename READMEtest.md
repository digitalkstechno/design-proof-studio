# Design Proof API

Python HTTP API for creating branded design-proof PNG files from uploaded artwork.

## Folder structure

```text
design-proof-api-client/
├── api/
│   ├── app/
│   │   ├── assets/
│   │   │   └── nlc-logo-default.png
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── renderer.py
│   └── requirements.txt
├── web/
│   └── index.html
└── README.md
```

`api/` is the production API. `web/` is an optional browser tester and preview interface.

## Requirements

Python 3.10 or newer.

## Install and run

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

After startup:

```text
API:        http://127.0.0.1:8000/api/v1/render
API docs:   http://127.0.0.1:8000/docs
Health:     http://127.0.0.1:8000/health
Web tester: http://127.0.0.1:8000/web/
```

## Main endpoint

`POST /api/v1/render`

Request type: `multipart/form-data`

### Required fields

| Field | Type | Description |
|---|---|---|
| `design` | file | Image or embroidery artwork; see [format catalogue](SUPPORTED-FORMATS.md) |
| `category` | string | Main category |
| `subcategory` | string | Subcategory |
| `design_type` | string | Design type |
| `design_id` | string | Design identifier |
| `seller` | string | Seller name |

### Common optional fields

| Field | Default | Description |
|---|---:|---|
| `logo` | built-in NLC logo | Optional image or embroidery logo override |
| `company_name` | `YOUR BRAND` | Company or brand name |
| `company_website` | `yourwebsite.com` | Website shown on proof |
| `watermark_opacity` | `0.16` | Range `0.0` to `1.0` |
| `watermark_size` | `1.25` | Range `0.4` to `2.5` |
| `watermark_spacing` | `1.35` | Range `0.5` to `2.5` |
| `watermark_scope` | `artwork` | `artwork` or `page` |
| `logo_scale` | `1.03` | Range `0.4` to `1.8` |

Typography size fields are optional and already have production defaults. They only need to be sent when the layout must be customized.

## Minimum cURL request

```bash
curl -X POST http://127.0.0.1:8000/api/v1/render \
  -F "design=@/path/to/design.png" \
  -F "category=Hot Fix Design" \
  -F "subcategory=Val jerkin Designs" \
  -F "design_type=Suit/Gala" \
  -F "design_id=NLC-8340/4" \
  -F "seller=Seller Name" \
  --output proof.png
```

The `logo` field can be omitted. The bundled NLC logo is used automatically.

## Python request example

```python
import requests

url = "http://127.0.0.1:8000/api/v1/render"

with open("design.png", "rb") as design_file:
    response = requests.post(
        url,
        files={
            "design": ("design.png", design_file, "image/png"),
        },
        data={
            "category": "Hot Fix Design",
            "subcategory": "Val jerkin Designs",
            "design_type": "Suit/Gala",
            "design_id": "NLC-8340/4",
            "seller": "Seller Name",
        },
        timeout=60,
    )

response.raise_for_status()

with open("proof.png", "wb") as output_file:
    output_file.write(response.content)
```

## Response

A successful render returns:

```text
HTTP 200
Content-Type: image/png
```

The response body is the final PNG file. The filename is also returned in the `Content-Disposition` header.

Invalid input returns HTTP `422` with a JSON error message.

## Other endpoints

`GET /health` returns service status. `GET /api/v1/defaults` returns current rendering defaults. `GET /api/v1/default-logo` returns the bundled logo. `GET /docs` opens interactive API documentation.

## CORS

If the API is called from a different browser domain, set allowed origins before starting the server:

```bash
export PROOF_ALLOWED_ORIGINS="https://example.com,https://www.example.com"
```

Multiple origins are separated by commas.

## Supported software and formats

See [SUPPORTED-FORMATS.md](SUPPORTED-FORMATS.md) for the researched extension/software matrix, conversion behavior and verification limits. `GET /api/v1/formats` reports the formats available on the running server. Both preview and final render now accept binary stitch files such as DST, PES, PEC, JEF, EXP, VP3, HUS and XXX, with 52 local extensions/aliases in total.

Native EMB and related Wilcom project formats require an active Wilcom API account. Without server credentials they return an actionable HTTP 503 instead of a generic image error. ART, JAN, PXF, OFM and other unavailable native projects require an export to a supported image or stitch format; they are not advertised as supported.

## File limits

Artwork and logo raster uploads accept PNG (`.png`), JPEG (`.jpg`, `.jpeg`, `.jfif`), WebP (`.webp`), BMP (`.bmp`, `.dib`), GIF (`.gif`), TIFF (`.tif`, `.tiff`) and ICO (`.ico`), plus PSD, PCX, TGA, Netpbm and JPEG 2000. Validation checks decoded image content, not the filename or MIME type. Maximum upload size is 25 MB per file. Existing pixel limits still apply: artwork is limited to 40 million pixels and 30,000 px per side; logos to 100 million pixels and 40,000 px per side, then downsampled to 2048 px.

Animated images use the first frame; multipage TIFFs use the first page. ICO uploads use the default (largest) icon. The final proof remains a PNG. PDF, SVG, HEIC and other unsupported formats must be exported to one of the supported raster formats first. Stitch files are converted to a bounded PNG simulation; machine formats without stored thread colors use a neutral dark fallback.

`POST /api/v1/preview-image` accepts multipart fields `image` (file) and `role` (`design` or `logo`, default `design`) and returns a decoded PNG. For embroidery uploads, retain the original filename/extension so the correct binary reader can be selected. `X-Input-Format` and `X-Conversion-Note` describe the conversion. For stitch uploads the source-size headers on final renders refer to the simulation bitmap, not the physical embroidery dimensions. The web interface uses this endpoint so every supported format previews consistently, even when a browser cannot open the original format. Final rendering receives the original upload, preserving source dimensions.

## Tests

```bash
pip install -r api/requirements.txt -r api/requirements-dev.txt
python -m unittest discover -s api/tests -v
node --test web/tests/uploads.test.cjs
```
