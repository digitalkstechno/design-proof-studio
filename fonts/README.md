# Fonts for identical proof rendering

This folder is the single client-facing place for proof fonts.

## Current reference fonts

The current macOS reference render uses:

- Regular: Arial
- Bold: Arial Bold
- Italic: Georgia Italic
- Script/footer: SignPainter

Those fonts are operating-system / licensed fonts. They are **not included in this client package**. Add only font files that you are licensed to deploy and redistribute.

Reference locations on the Mac used for the approved render:

```text
/System/Library/Fonts/Supplemental/Arial.ttf
/System/Library/Fonts/Supplemental/Arial Bold.ttf
/System/Library/Fonts/Supplemental/Georgia Italic.ttf
/System/Library/Fonts/Supplemental/SignPainter.ttc
```

These paths are provided only to identify the exact reference fonts. Do not copy or redistribute them unless your license permits it.

## Recommended filenames

Place licensed copies in this folder using these names:

- `Proof-Regular.ttf` — reference: Arial Regular
- `Proof-Bold.ttf` — reference: Arial Bold
- `Proof-Italic.ttf` — reference: Georgia Italic
- `Proof-Script.ttf`, `Proof-Script.otf`, or `Proof-Script.ttc` — reference: SignPainter

The Python renderer checks this folder before OS fallback fonts. The browser preview also loads these same filenames from `/fonts/`.

For the closest possible match between browser preview and downloaded PNG, provide all four proof fonts here and restart the API.

## Optional environment overrides

Instead of the filenames above, the backend can use explicit paths:

```bash
PROOF_FONT_REGULAR=/absolute/path/to/regular.ttf
PROOF_FONT_BOLD=/absolute/path/to/bold.ttf
PROOF_FONT_ITALIC=/absolute/path/to/italic.ttf
PROOF_FONT_SCRIPT=/absolute/path/to/script.ttf
```

You can also point the backend at another folder:

```bash
PROOF_FONT_DIR=/absolute/path/to/fonts
```

Note: the browser preview is served from this project's `fonts/` folder. If you use backend-only environment paths outside this folder, the final PNG can still use them, but the browser preview may fall back to locally installed fonts.

## Verify deployment

After starting the API, open:

`GET /api/v1/defaults`

The `fonts` section reports the active source and filename for regular, bold, italic, and script fonts.

For a deterministic production deployment, each font should report:

`"source": "project"`

or, for backend-only explicit configuration:

`"source": "env"`

If it reports `"system"`, the server is relying on an OS-installed fallback and another machine may render slightly differently.
