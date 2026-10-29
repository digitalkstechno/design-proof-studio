"""One format catalogue for validation, API discovery and the browser picker."""
import os

from pyembroidery import EmbPattern


RASTER_FORMATS = {
    "PNG": ("png", "apng"), "JPEG": ("jpg", "jpeg", "jfif"),
    "WEBP": ("webp",), "BMP": ("bmp",), "DIB": ("dib",),
    "GIF": ("gif",), "TIFF": ("tif", "tiff"), "ICO": ("ico",),
    "PSD": ("psd",), "PCX": ("pcx",), "TGA": ("tga",),
    "PPM": ("pbm", "pgm", "ppm", "pnm"), "JPEG2000": ("jp2", "j2k", "jpf", "jpx"),
}
RASTER_SOFTWARE = {
    "PNG": "Image editors / embroidery bitmap exports", "JPEG": "Image editors / photo software",
    "WEBP": "Web image editors", "BMP": "Windows / embroidery bitmap exports",
    "DIB": "Windows bitmap tools", "GIF": "Image / animation editors",
    "TIFF": "Graphics / scanning software", "ICO": "Icon editors",
    "PSD": "Adobe Photoshop", "PCX": "PC Paintbrush / legacy image tools",
    "TGA": "Targa / graphics tools", "PPM": "Netpbm / image processing tools",
    "JPEG2000": "JPEG 2000 image editors",
}
# JPX is also a Janome embroidery extension. Dispatch it by image signature first.
LOCAL_EMBROIDERY = {}
for _format in EmbPattern.supported_formats():
    if "reader" in _format and _format["extension"] not in {"csv", "gcode", "json", "edr", "col", "inf"}:
        _aliases = _format.get("extensions", ())
        if isinstance(_aliases, str):
            _aliases = (_aliases,)
        for _extension in dict.fromkeys((_format["extension"], *_aliases)):
            LOCAL_EMBROIDERY[_extension] = _format

# These are documented EWA input formats; do not assume other native formats work.
WILCOM_FORMATS = {
    "emb": "Wilcom EmbroideryStudio / Hatch", "emc": "Wilcom clipart",
    "emt": "Wilcom / Hatch template", "emx": "Wilcom cross stitch",
    "arx": "Bernina Artista cross stitch", "t01": "Tajima / Wilcom",
    "t03": "Barudan / Wilcom", "t04": "Zangs", "t05": "ZSK / Wilcom",
    "t09": "Pfaff / Wilcom",
}
WILCOM_FORMATS.update({f"u{i:02d}": "Barudan" for i in range(100) if f"u{i:02d}" not in LOCAL_EMBROIDERY})
WILCOM_FORMATS.update({f"z{i:02d}": "ZSK TC" for i in range(100) if f"z{i:02d}" not in LOCAL_EMBROIDERY})
NATIVE_EXPORT_ONLY = {
    "art": "Bernina ARTlink / DesignerPlus", "art42": "Bernina DesignerPlus",
    "art50": "Bernina DesignerPlus", "art60": "Bernina DesignerPlus",
    "art70": "Bernina DesignerPlus", "art80": "Bernina DesignerPlus",
    "art90": "Bernina DesignerPlus", "jan": "Janome Digitizer",
    "jmt": "Janome template", "amt": "Bernina template", "pxf": "Tajima DG/ML by Pulse",
    "pof": "Tajima DG/ML by Pulse", "ofm": "Melco DesignShop",
    "cnd": "Melco condensed design", "gnc": "Great Notions",
    "vip": "Husqvarna / Pfaff", "vp4": "Husqvarna / Pfaff",
    "csd": "Singer / Poem", "esq": "Husqvarna / Pfaff",
    "dhe": "Dahao", "cdr": "CorelDRAW", "ai": "Adobe Illustrator",
    "eps": "PostScript design software", "pdf": "PDF design exports",
    "svg": "Inkscape / Illustrator / Hatch cutting export",
}


def wilcom_enabled() -> bool:
    return bool(os.getenv("PROOF_WILCOM_APP_ID", "").strip() and os.getenv("PROOF_WILCOM_APP_KEY", "").strip())


def format_catalogue() -> dict:
    formats = [dict(extensions=list(extensions), software=RASTER_SOFTWARE[name],
                    kind="image", available=True, conversion="raster")
               for name, extensions in RASTER_FORMATS.items()]
    # Group aliases together, rather than displaying every numbered machine suffix.
    for spec in EmbPattern.supported_formats():
        extensions = [ext for ext, item in LOCAL_EMBROIDERY.items() if item["extension"] == spec["extension"]]
        if extensions:
            formats.append(dict(extensions=extensions, software=spec["description"], kind="embroidery",
                                available=True, conversion="stitches"))
    for extension, software in WILCOM_FORMATS.items():
        formats.append(dict(extensions=[extension], software=software, kind="embroidery",
                            available=wilcom_enabled(), conversion="wilcom",
                            note="Requires a configured Wilcom Embroidery Web API account."))
    for extension, software in NATIVE_EXPORT_ONLY.items():
        formats.append(dict(extensions=[extension], software=software, kind="project",
                            available=False, conversion="export",
                            note="Export PNG/BMP or a supported stitch format from the source software."))
    return {"formats": formats, "max_upload_bytes": 25 * 1024 * 1024,
            "embroidery_note": "Stitch previews are simulations, not editable project artwork. Formats without thread colors use a neutral dark thread."}
