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
| `design` | file | PNG, JPEG or WebP artwork |
| `category` | string | Main category |
| `subcategory` | string | Subcategory |
| `design_type` | string | Design type |
| `design_id` | string | Design identifier |
| `seller` | string | Seller name |

### Common optional fields

| Field | Default | Description |
|---|---:|---|
| `logo` | built-in NLC logo | Optional PNG/JPEG/WebP logo override |
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

## File limits

Artwork and logo uploads accept PNG, JPEG and WebP. Maximum upload size is 25 MB per file. Artwork is placed at its decoded pixel dimensions without stretching or cropping.
