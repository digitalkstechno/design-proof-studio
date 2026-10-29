# File format and software reference

The server reports its current capabilities at `GET /api/v1/formats`. The browser builds its file picker and availability table from that response. File extensions alone do not make a file supported: its decoder must produce valid image pixels or stitch geometry.

## Built-in embroidery decoding

These 40 reader families cover 52 extensions and aliases through pyembroidery 1.5.1. The software/machine column identifies the format family; software such as Wilcom/Hatch can export multiple machine formats. A machine format does not necessarily identify the program that originally created a file.

| Extensions | Software / machine family |
|---|---|
| `.pec` | Brother |
| `.pes` | Brother |
| `.exp` | Melco Expanded |
| `.dst` | Tajima |
| `.jef` | Janome |
| `.vp3` | Pfaff |
| `.xxx` | Singer |
| `.sew` | Janome |
| `.u01`, `.u00`, `.u02` | Barudan |
| `.shv` | Husqvarna Viking |
| `.10o` | Toyota |
| `.100` | Toyota |
| `.bro` | Bits & Volts |
| `.dat` | Sunstar or Barudan |
| `.dsb` | Tajima(Barudan) |
| `.dsz` | ZSK USA |
| `.emd` | Elna |
| `.exy`, `.e00`, `.e01`, `.e02` | Eltac |
| `.fxy`, `.f00`, `.f01`, `.f02` | Fortron |
| `.gt` | Gold Thread |
| `.inb` | Inbro |
| `.tbf` | Tajima |
| `.ksm` | Pfaff |
| `.tap` | Happy |
| `.spx` | Pfaff |
| `.stx` | Data Stitch |
| `.phb` | Brother |
| `.phc` | Brother |
| `.new` | Ameco |
| `.max` | Pfaff |
| `.mit` | Mitsubishi |
| `.pcd` | Pfaff |
| `.pcq` | Pfaff |
| `.pcm` | Pfaff |
| `.pcs` | Pfaff |
| `.jpx` | Janome |
| `.stc` | Gunold |
| `.zhs` | Zeng Hsing |
| `.zxy`, `.z00`, `.z01`, `.z02` | ZSK TC |
| `.pmv` | Brother Stitch Format |
| `.hus` | Husqvarna |

Both artwork and logo uploads use the same decoder. Stitches are drawn to a transparent PNG before the existing proof renderer runs. This is a static stitch simulation, not a reconstruction of editable objects or a photorealistic Wilcom TrueView. Jump moves and trims are not drawn as stitches. Colors are preserved when supplied by the file; formats such as ordinary DST and EXP can omit colors and use a deterministic neutral dark thread instead. Original machine files are never modified or executed. Headerless formats such as EXP cannot be identified reliably from a magic number: their extension selects the parser and decoded stitch geometry is validated. Some printable-looking bytes are valid stitch coordinates.

Limits: 25 MB per upload, 500,000 decoded commands, coordinates within 10 metres of the origin, a 1600 px maximum preview edge, a 20-second decoder timeout, and at most two local decoder processes per API process. On Linux each decoder also has a CPU and memory limit. Existing raster pixel limits still apply. For stitch files the `X-Source-Design-Width/Height` headers describe the generated simulation bitmap, not the source design's physical size or machine units.

## Native and vendor formats

| Extensions | Software / family | Current behavior |
|---|---|---|
| `.emb` | Wilcom EmbroideryStudio / Hatch working design | Wilcom account required |
| `.emc`, `.emt`, `.emx` | Wilcom clipart, template, cross stitch | Wilcom account required |
| `.arx` | Bernina Artista cross stitch | Wilcom account required |
| `.t01`, `.t03`, `.t04`, `.t05`, `.t09` | Wilcom machine variants: Tajima, Barudan, Zangs, ZSK, Pfaff | Wilcom account required |
| `.u00`–`.u99`, `.z00`–`.z99` | Barudan / ZSK TC numbered variants | `.u00`–`.u02`, `.z00`–`.z02` decode locally; remaining variants require Wilcom |
| `.art`, `.art42`, `.art50`, `.art60`, `.art70`, `.art80`, `.art90`, `.amt` | Bernina ARTlink / DesignerPlus / templates | Export from source software |
| `.jan`, `.jmt` | Janome Digitizer / templates | Export from source software |
| `.pxf`, `.pof` | Tajima DG/ML by Pulse project formats | Export from source software |
| `.ofm`, `.cnd` | Melco DesignShop project / condensed formats | Export from source software |
| `.gnc` | Great Notions | Export from source software |
| `.vip`, `.vp4`, `.esq` | Husqvarna / Pfaff | Export to supported VP3/HUS/SHV or PNG/BMP |
| `.csd` | Singer / Poem | Export to supported XXX or PNG/BMP |
| `.dhe` | Dahao | Export to supported DST or PNG/BMP |
| `.cdr`, `.ai`, `.eps`, `.pdf`, `.svg` | CorelDRAW, Illustrator, PostScript, PDF and vector artwork exports | Export PNG/BMP; no vector/document renderer is installed |

No Wilcom account is currently available for this project. Therefore EMB and the other converter-dependent formats remain unavailable by default, and the UI does not advertise them as uploadable. The API returns HTTP 503 with export/configuration guidance for these formats. Adding `.emb` to a file picker or renaming it `.bmp` cannot decode an embroidery project.

### Optional Wilcom integration

The implementation uses the documented `api/designTrueview` XML/base64 protocol with the current colorway at 150 DPI. Configure these server-side environment variables only when an active Wilcom API account is available:

```text
PROOF_WILCOM_APP_ID=your-application-id
PROOF_WILCOM_APP_KEY=your-application-key
# Optional: change only if Wilcom supplies a different endpoint for your account.
PROOF_WILCOM_URL=https://public.ewa.wilcomapps.com/api/designTrueview
```

Once both credentials are set, `/api/v1/formats` marks the documented Wilcom formats available. Conversion sends the uploaded design to Wilcom. Preview and final rendering each perform a conversion and can each consume API-plan usage; no automatic retries occur. EWA accepts an encoded request smaller than 20 MB, so base64/form overhead makes its effective raw file limit lower than the local 25 MB limit. Requests and responses are bounded; authentication, timeout, malformed XML/base64, and provider errors produce actionable errors without returning credentials or provider internals.

The adapter is covered by mocked protocol/error tests. It has **not** been verified against a live account or a real EMB sample; individual software versions and account entitlements must be checked before claiming direct EMB support in production. Other native formats such as ART and PXF are not added to EWA calls because its published input table does not document them.

## Raster artwork

| Extensions | Typical source | Behavior |
|---|---|---|
| `.png`, `.apng`, `.jpg`, `.jpeg`, `.jfif`, `.webp`, `.bmp`, `.dib`, `.gif`, `.tif`, `.tiff`, `.ico` | Image editors and embroidery software bitmap exports | Existing support; first frame/page; EXIF orientation applied |
| `.psd` | Adobe Photoshop | Reads the merged/composite bitmap supported by Pillow; does not reconstruct layers/effects |
| `.pcx` | Legacy PC Paintbrush / design applications | Decoded bitmap |
| `.tga` | Targa / graphics applications | Decoded bitmap |
| `.pbm`, `.pgm`, `.ppm`, `.pnm` | Netpbm / image tools | Decoded bitmap |
| `.jp2`, `.j2k`, `.jpf`, `.jpx` | JPEG 2000 image editors | Decoded bitmap using Pillow/OpenJPEG |

`.jpx` is ambiguous: valid JPEG 2000 image content is decoded as an image; otherwise the Janome stitch reader is used. JPEG 2000 requires a Pillow build with OpenJPEG; the tested wheel includes it. HEIC/HEIF, AVIF, PSB and other unlisted formats are not claimed as supported. Original image content is inspected, not trusted from the filename or MIME type.

## Verification

Run:

```bash
pip install -r api/requirements.txt -r api/requirements-dev.txt
python -m unittest discover -s api/tests -v
node --test web/tests/uploads.test.cjs
```

The tests generate actual binary DST, PES, PEC, EXP, JEF, VP3, XXX, U01, TBF and PMV files and exercise decoding, both preview roles and final PNG generation. Raster tests exercise every advertised image decoder, including a composite PSD. Other legacy stitch formats are backed by the installed library's readers, catalogue/alias checks and malformed-input tests; real customer files for every legacy format/version have not been supplied. No claim is made that every historical vendor variant is supported.

## Research sources

- [Wilcom EWA specification, supported input table and authentication](https://wilcom.com/web-api/developers/guide)
- [Hatch official software and machine format list](https://help.hatchembroidery.com/portal/en/kb/hatch/general/general/articles/what-file-formats-does-hatch-embroidery-v2-v3-read-and-write)
- [pyembroidery documentation and source readers](https://github.com/EmbroidePy/pyembroidery)
- [Melco DesignShop file formats](https://www.melco-service.com/docs/DS_V9_090309/Working_with_Files_in_DesignShop.htm)
- [Tajima Autograph / Pulse user guide (PXF)](https://media.pulsemicro.com/downloads/Autograph/documentation/5925/UsersGuide.pdf)
- [Pillow file format documentation](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)
