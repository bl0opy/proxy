import math
import subprocess
import sys
import tempfile
from pathlib import Path

import AppKit
from Foundation import NSMakeRect

SIZES = [16, 32, 64, 128, 256, 512, 1024]
LEVELS = [0.25, 0.5, 0.8, 1.0, 0.65, 0.9, 0.45, 0.25]


def render(px: int) -> AppKit.NSBitmapImageRep:
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    s = px / 1024
    inset = 100 * s
    body = NSMakeRect(inset, inset, px - 2 * inset, px - 2 * inset)
    AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.045, 0.045, 0.05, 1).setFill()
    AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body, 185 * s, 185 * s).fill()

    dot, gap = 34 * s, 22 * s
    x0 = 512 * s - (len(LEVELS) * (dot + gap) - gap) / 2 + 70 * s
    for i, level in enumerate(LEVELS):
        rows = max(1, round(level * 9))
        top = 512 * s - (rows * (dot + gap) - gap) / 2
        for r in range(rows):
            AppKit.NSColor.colorWithWhite_alpha_(0.94, 1).setFill()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(x0 + i * (dot + gap), top + r * (dot + gap), dot, dot)).fill()
    AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(1, 0.23, 0.19, 1).setFill()
    r = 46 * s
    AppKit.NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(262 * s - r, 512 * s - r, 2 * r, 2 * r)).fill()
    AppKit.NSGraphicsContext.restoreGraphicsState()
    return rep


def main(out: Path):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Proxy.iconset"
        iconset.mkdir()
        for size in SIZES[:-1]:
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                data = render(px).representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
                data.writeToFile_atomically_(str(iconset / name), True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
