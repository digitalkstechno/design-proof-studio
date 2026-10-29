"""Decode raster images or convert embroidery designs into proof artwork."""
import base64
import binascii
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree as ET

import httpx
from PIL import UnidentifiedImageError

from app.formats import LOCAL_EMBROIDERY, WILCOM_FORMATS, NATIVE_EXPORT_ONLY, wilcom_enabled
from app.renderer import MAX_UPLOAD_BYTES, RenderError, open_image

UPLOAD_DESCRIPTION = "Raster image or embroidery design; see GET /api/v1/formats for extensions and conversion availability."
CONVERSION_NOTE = "Stitch simulation; thread colors may be absent from machine files and use a neutral dark fallback."
MAX_WILCOM_REQUEST_BYTES = 19 * 1024 * 1024  # EWA requires a request smaller than 20 MB.
MAX_WILCOM_RESPONSE_BYTES = 40 * 1024 * 1024
DECODER_SLOTS = BoundedSemaphore(2)


class ConversionUnavailable(RenderError):
    status_code = 503


class ConversionFailed(RenderError):
    status_code = 502


def wilcom_png(data: bytes, extension: str) -> bytes:
    if not wilcom_enabled():
        raise ConversionUnavailable(
            f".{extension.upper()} requires the Wilcom embroidery converter, which is not configured. "
            "Export this design as PNG/BMP or DST/PES/JEF in your embroidery software, or ask the administrator to configure Wilcom API credentials.")
    root = ET.Element("xml")
    ET.SubElement(root, "design", file=f"design.{extension}", colorwaytype="current")
    ET.SubElement(root, "trueview_options", dpi="150")
    ET.SubElement(ET.SubElement(root, "files"), "file", filename=f"design.{extension}",
                  filecontents=base64.b64encode(data).decode("ascii"))
    body = urlencode({"appId": os.environ["PROOF_WILCOM_APP_ID"].strip(),
                      "appKey": os.environ["PROOF_WILCOM_APP_KEY"].strip(),
                      "requestXml": ET.tostring(root, encoding="unicode")}).encode("utf-8")
    if len(body) >= MAX_WILCOM_REQUEST_BYTES:
        raise RenderError("Embroidery is too large for the Wilcom converter's 20 MB encoded-request limit. Export a PNG/BMP instead.")
    url = os.getenv("PROOF_WILCOM_URL", "https://public.ewa.wilcomapps.com/api/designTrueview").strip()
    if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
        raise ConversionUnavailable("The Wilcom converter must be configured with an HTTPS endpoint.")
    try:
        # No retries: each successful EWA call may count against the API plan.
        with httpx.stream("POST", url, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
                          timeout=httpx.Timeout(90.0, connect=10.0), follow_redirects=False) as response:
            if response.status_code in (401, 403):
                raise ConversionUnavailable("Wilcom converter authentication failed. Ask the administrator to check the API account.")
            if response.status_code in (400, 422):
                raise RenderError("Wilcom could not open this embroidery file or version. Re-export it from the original software.")
            if response.status_code != 200:
                raise ConversionFailed("Wilcom converter is unavailable. Try again later or upload an exported PNG/BMP.")
            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_WILCOM_RESPONSE_BYTES:
                    raise ConversionFailed("Wilcom conversion response exceeds the supported size.")
                chunks.append(chunk)
        xml = b"".join(chunks)
        # EWA uses a plain XML package; it has no need for DTDs or entities.
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ConversionFailed("Wilcom returned an invalid conversion response.")
        result = ET.fromstring(xml)
        if result.find(".//error_info") is not None:
            raise RenderError("Wilcom could not convert this design. Check its format and software version.")
        for file in result.findall(".//files/file"):
            if file.get("filename", "").lower().endswith(".png"):
                png = base64.b64decode(file.get("filecontents", ""), validate=True)
                if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > MAX_UPLOAD_BYTES:
                    raise ConversionFailed("Wilcom did not return a usable PNG preview.")
                return png
        raise ConversionFailed("Wilcom returned no PNG preview for this design.")
    except (httpx.HTTPError, ET.ParseError, binascii.Error, ValueError) as exc:
        if isinstance(exc, RenderError):
            raise
        raise ConversionFailed("Embroidery conversion failed. Try again later or upload an exported PNG/BMP.") from exc


def local_stitch_png(data: bytes, extension: str) -> bytes:
    with TemporaryDirectory(prefix="proof-embroidery-") as folder:
        source = Path(folder) / f"design.{extension}"
        target = Path(folder) / "preview.png"
        source.write_bytes(data)
        try:
            with DECODER_SLOTS:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name("embroidery.py")), str(source), str(target), extension],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=20, check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise RenderError("Embroidery decoding took too long. Export a PNG/BMP or a simpler stitch file.") from exc
        except OSError as exc:
            raise ConversionUnavailable("The embroidery decoder could not start. Ask the administrator to check the installation.") from exc
        if result.returncode != 0 or not target.is_file():
            raise RenderError(f"Invalid or unsupported .{extension.upper()} embroidery data. Re-export it from the original software.")
        if target.stat().st_size > MAX_UPLOAD_BYTES:
            raise RenderError("Converted embroidery preview is too large.")
        return target.read_bytes()


def open_upload(data: bytes, label: str, filename: str | None = None):
    if not data or len(data) > MAX_UPLOAD_BYTES:
        return open_image(data, label)  # Preserve existing empty/size errors.
    # Raster content is recognized by signature, including files with a missing
    # or incorrect extension. JPX may be either a bitmap or a Janome stitch file.
    extension = Path((filename or "").replace("\\", "/")).suffix.lower().lstrip(".")
    try:
        image = open_image(data, label)
        image.info["proof_input_format"] = "raster"
        return image
    except RenderError as exc:
        if not isinstance(exc.__cause__, UnidentifiedImageError):
            raise
        if extension not in LOCAL_EMBROIDERY and extension not in WILCOM_FORMATS and extension not in NATIVE_EXPORT_ONLY:
            raise
    if extension in NATIVE_EXPORT_ONLY:
        software = NATIVE_EXPORT_ONLY[extension]
        raise RenderError(f".{extension.upper()} is a {software} file. This server cannot decode it. Export PNG/BMP or a supported stitch format from the original software.")
    if extension in LOCAL_EMBROIDERY:
        png = local_stitch_png(data, extension)
        note = CONVERSION_NOTE
    else:
        png = wilcom_png(data, extension)
        note = "Wilcom TrueView conversion of the current colorway."
    image = open_image(png, label)
    image.info["proof_input_format"] = extension.upper()
    image.info["proof_conversion_note"] = note
    return image
