"""HTTP API for generating branded design-proof PNG images."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.formats import format_catalogue
from app.uploads import UPLOAD_DESCRIPTION, open_upload
from app.renderer import MAX_UPLOAD_BYTES, ProofFields, ProofStyle, RenderError, font_status, normalized_artwork_size, png_bytes, render_proof

API_VERSION = "2.5.0"

app = FastAPI(
    title="Design Proof Studio API",
    version=API_VERSION,
    description="Render uploaded artwork at a normalized 1200 px proof-display width with live-preview style controls.",
)
origins = [x.strip() for x in os.getenv("PROOF_ALLOWED_ORIGINS", "").split(",") if x.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["POST", "GET"], allow_headers=["*"], max_age=600)
app_dir = Path(__file__).resolve().parent
default_logo_path = app_dir / "assets" / "nlc-logo-default.png"
project_root = Path(__file__).resolve().parents[2]
web_dir = project_root / "web"
fonts_dir = project_root / "fonts"
if fonts_dir.is_dir():
    app.mount("/fonts", StaticFiles(directory=fonts_dir), name="fonts")
if web_dir.is_dir():
    app.mount("/web", StaticFiles(directory=web_dir, html=True), name="web")


@app.get("/", include_in_schema=False)
def home() -> dict[str, str]:
    return {
        "service": "Design Proof API",
        "version": API_VERSION,
        "render_endpoint": "/api/v1/render",
        "documentation": "/docs",
        "web_test": "/web/",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": API_VERSION}


@app.get("/api/v1/formats")
def formats() -> dict:
    """Report supported formats separately from formats needing a converter/export."""
    return format_catalogue()


@app.get("/api/v1/default-logo", responses={200: {"content": {"image/png": {}}}})
def default_logo() -> Response:
    return Response(
        content=default_logo_path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/v1/defaults")
def defaults() -> dict:
    style = ProofStyle()
    return {
        "watermark_opacity": 0.16,
        "watermark_size": 1.25,
        "watermark_spacing": 1.35,
        "watermark_scope": "artwork",
        "style": style.__dict__,
        "fonts": font_status(),
    }


@app.post("/api/v1/preview-image", responses={200: {"content": {"image/png": {}}}, 422: {"description": "Invalid image or input"}, 502: {"description": "Conversion service failed"}, 503: {"description": "Converter unavailable"}})
async def preview_image(
    image: UploadFile = File(description=UPLOAD_DESCRIPTION),
    role: Literal["design", "logo"] = Form(default="design"),
) -> Response:
    """Decode uploads consistently, including formats browsers cannot display."""
    try:
        data = await image.read(MAX_UPLOAD_BYTES + 1)
        decoded = await run_in_threadpool(open_upload, data, "Logo" if role == "logo" else "Design", image.filename)
        return Response(
            content=await run_in_threadpool(png_bytes, decoded),
            media_type="image/png",
            headers={"Cache-Control": "no-store",
                     "X-Input-Format": decoded.info.get("proof_input_format", "raster"),
                     "X-Conversion-Note": decoded.info.get("proof_conversion_note", "")},
        )
    except RenderError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 422), detail=str(exc)) from exc
    finally:
        await image.close()


@app.post("/api/v1/render", responses={200: {"content": {"image/png": {}}}, 422: {"description": "Invalid image or input"}, 502: {"description": "Conversion service failed"}, 503: {"description": "Converter unavailable"}})
async def render(
    design: UploadFile = File(description=UPLOAD_DESCRIPTION),
    logo: UploadFile | None = File(default=None, description=f"Optional company logo. {UPLOAD_DESCRIPTION} If omitted, the bundled NLC logo is used."),
    category: str = Form(min_length=1, max_length=80),
    subcategory: str = Form(min_length=1, max_length=100),
    design_type: str = Form(min_length=1, max_length=100),
    design_id: str = Form(min_length=1, max_length=50),
    seller: str = Form(min_length=1, max_length=100),
    company_name: str = Form(default="NLC Design", min_length=1, max_length=80),
    company_website: str = Form(default="www.nlcdesign.in", min_length=1, max_length=120),
    watermark_opacity: float = Form(default=0.16, ge=0, le=1.0),
    watermark_size: float = Form(default=1.25, ge=0.4, le=2.5),
    watermark_spacing: float = Form(default=1.35, ge=0.5, le=2.5),
    watermark_scope: str = Form(default="artwork", pattern="^(artwork|page)$"),
    category_title_size: float = Form(default=31.0, ge=10, le=42),
    category_value_size: float = Form(default=25.5, ge=8, le=38),
    design_id_title_size: float = Form(default=19.0, ge=10, le=42),
    design_id_value_size: float = Form(default=23.0, ge=8, le=42),
    seller_title_size: float = Form(default=17.0, ge=8, le=38),
    seller_value_size: float = Form(default=18.5, ge=8, le=40),
    warning_title_size: float = Form(default=22.0, ge=10, le=42),
    warning_subtitle_size: float = Form(default=11.5, ge=8, le=28),
    footer_label_size: float = Form(default=14.5, ge=8, le=32),
    company_name_size: float = Form(default=23.0, ge=8, le=42),
    company_website_size: float = Form(default=16.0, ge=8, le=32),
    support_title_size: float = Form(default=29.0, ge=8, le=40),
    support_subtitle_size: float = Form(default=31.0, ge=8, le=40),
    logo_scale: float = Form(default=1.03, ge=0.4, le=1.8),
) -> Response:
    values = [category, subcategory, design_type, design_id, seller, company_name, company_website]
    if any(not value.strip() for value in values):
        raise HTTPException(status_code=422, detail="Text fields cannot be blank.")
    if any(any(ord(char) < 32 and char not in "\t\n" for char in value) for value in values):
        raise HTTPException(status_code=422, detail="Text fields contain invalid control characters.")

    style = ProofStyle(
        category_title_size=category_title_size,
        category_value_size=category_value_size,
        design_id_title_size=design_id_title_size,
        design_id_value_size=design_id_value_size,
        seller_title_size=seller_title_size,
        seller_value_size=seller_value_size,
        warning_title_size=warning_title_size,
        warning_subtitle_size=warning_subtitle_size,
        footer_label_size=footer_label_size,
        company_name_size=company_name_size,
        company_website_size=company_website_size,
        support_title_size=support_title_size,
        support_subtitle_size=support_subtitle_size,
        logo_scale=logo_scale,
    )

    try:
        design_bytes = await design.read(MAX_UPLOAD_BYTES + 1)
        logo_bytes = await logo.read(MAX_UPLOAD_BYTES + 1) if logo is not None else default_logo_path.read_bytes()
        artwork = await run_in_threadpool(open_upload, design_bytes, "Design", design.filename)
        branding = await run_in_threadpool(open_upload, logo_bytes, "Logo", logo.filename if logo is not None else None)
        fields = ProofFields(
            category=category.strip(),
            subcategory=subcategory.strip(),
            design_type=design_type.strip(),
            design_id=design_id.strip(),
            seller=seller.strip(),
            company_name=company_name.strip(),
            company_website=company_website.strip(),
            watermark_opacity=watermark_opacity,
            watermark_size=watermark_size,
            watermark_spacing=watermark_spacing,
            watermark_scope=watermark_scope,
            style=style,
        )
        rendered_width, rendered_height = normalized_artwork_size(artwork.width, artwork.height)
        output = await run_in_threadpool(render_proof, artwork, branding, fields)
        image_data = await run_in_threadpool(png_bytes, output)
    except RenderError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 422), detail=str(exc)) from exc
    finally:
        await design.close()
        if logo is not None:
            await logo.close()

    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", design_id).strip("-")[:48] or "design"
    return Response(
        content=image_data,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="proof-{safe_id}.png"',
            "Cache-Control": "no-store",
            "X-Source-Design-Width": str(artwork.width),
            "X-Source-Design-Height": str(artwork.height),
            "X-Rendered-Design-Width": str(rendered_width),
            "X-Rendered-Design-Height": str(rendered_height),
            "X-Output-Width": str(output.width),
            "X-Output-Height": str(output.height),
            "X-Design-Input-Format": artwork.info.get("proof_input_format", "raster"),
            "X-Design-Conversion-Note": artwork.info.get("proof_conversion_note", ""),
        },
    )
