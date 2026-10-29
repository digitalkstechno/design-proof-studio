"""Bounded, isolated stitch decoder and deterministic transparent preview renderer.

Run as a worker process so malformed binary readers cannot hang the API worker.
"""
import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from pyembroidery import (EmbPattern, STITCH, JUMP, TRIM, STOP, END, COLOR_CHANGE,
                         NEEDLE_SET, SEQUIN_EJECT, COMMAND_MASK, decode_embroidery_command)

if __package__:
    from .formats import LOCAL_EMBROIDERY
else:
    from formats import LOCAL_EMBROIDERY

MAX_COMMANDS = 500_000
MAX_COORDINATE = 100_000  # 10 metres in the library's 0.1 mm units.
PREVIEW_EDGE = 1600
FALLBACK_THREAD = "#303030"


class InvalidEmbroidery(ValueError):
    pass


class BoundedStitches(list):
    def append(self, value):
        if len(self) >= MAX_COMMANDS:
            raise InvalidEmbroidery("Embroidery exceeds the 500,000-command limit.")
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


def stitch_image(data: bytes, extension: str) -> Image.Image:
    readers = {ext: fmt["reader"] for ext, fmt in LOCAL_EMBROIDERY.items()}
    if extension not in readers:
        raise InvalidEmbroidery("Unsupported embroidery format.")
    # Legacy formats such as EXP have no magic number and even printable byte
    # sequences can be valid coordinates. Use their reader and validate geometry.
    if not data:
        raise InvalidEmbroidery("File does not contain binary embroidery stitch data.")
    signatures = {"pes": b"#PES", "pec": b"#PEC", "vp3": b"%vsm%", "dst": b"LA:"}
    if extension in signatures and not data.startswith(signatures[extension]):
        raise InvalidEmbroidery("File content does not match its embroidery extension.")
    pattern = EmbPattern()
    pattern.stitches = BoundedStitches()
    EmbPattern.read_embroidery(readers[extension], io.BytesIO(data), pattern=pattern)
    if not pattern.stitches or len(pattern.stitches) > MAX_COMMANDS:
        raise InvalidEmbroidery("No usable embroidery stitches found.")
    points = []
    for x, y, command in pattern.stitches:
        if not (math.isfinite(x) and math.isfinite(y)) or max(abs(x), abs(y)) > MAX_COORDINATE:
            raise InvalidEmbroidery("Embroidery coordinates exceed the supported range.")
        if command & COMMAND_MASK in (STITCH, SEQUIN_EJECT):
            points.append((x, y))
    if len(points) < 2:
        raise InvalidEmbroidery("No usable embroidery stitches found.")
    min_x = min(x for x, _ in points)
    max_x = max(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    width, height = max_x - min_x, max_y - min_y
    if max(width, height) <= 0:
        raise InvalidEmbroidery("Embroidery has no visible design area.")
    margin = 12
    scale = (PREVIEW_EDGE - margin * 2) / max(width, height)
    size = (max(32, math.ceil(width * scale) + margin * 2),
            max(32, math.ceil(height * scale) + margin * 2))
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    thread_index = 0
    previous = None
    # A consistent physical thread width, bounded for legibility on small designs.
    line_width = max(1, min(5, round(scale * 2)))
    for x, y, flags in pattern.stitches:
        command, thread, needle, _ = decode_embroidery_command(flags)
        point = ((x - min_x) * scale + margin, (y - min_y) * scale + margin)
        if command == END:
            break
        if command in (COLOR_CHANGE, NEEDLE_SET):
            thread_index = thread if thread is not None else (max(0, needle - 1) if needle is not None else thread_index + 1)
            # Color changes do not draw a connecting stitch; the needle's last
            # position remains available for the next real stitch.
            continue
        if command in (JUMP, TRIM, STOP):
            previous = point if command == JUMP else None
            continue
        if command in (STITCH, SEQUIN_EJECT):
            color = pattern.threadlist[thread_index].hex_color() if thread_index < len(pattern.threadlist) else FALLBACK_THREAD
            if previous is not None:
                draw.line([previous, point], fill=color, width=line_width)
            else:
                draw.ellipse((point[0] - 1, point[1] - 1, point[0] + 1, point[1] + 1), fill=color)
            previous = point
    return image


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        # macOS does not implement useful RLIMIT_AS limits; Linux production does.
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        pass
    try:
        image = stitch_image(Path(sys.argv[1]).read_bytes(), sys.argv[3])
        image.save(sys.argv[2], "PNG")
    except Exception:
        # Keep parser internals and file contents out of HTTP errors/logs.
        sys.exit(1)


if __name__ == "__main__":
    main()
