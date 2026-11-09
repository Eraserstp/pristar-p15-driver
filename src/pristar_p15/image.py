"""Convert CUPS raster pages to the P15 1bpp bitmap orientation."""

from PIL import Image, ImageOps

from .raster import (CUPS_CSPACE_K, CUPS_CSPACE_RGB, CUPS_CSPACE_SRGB,
                     CUPS_CSPACE_W, Page, RasterError)

# The P15 head is 12 mm wide (96 dots at 203 dpi); the label runs along the
# feed.  Measured on hardware: the printer centre-crops wider images, so the
# page is rotated 90 degrees and a small blank border is kept to avoid the
# mechanical tolerance at the trailing edge.
HEAD_MARGIN = 2
FEED_START = 2
FEED_END = 6
ROTATION = 270


def page_to_image(page: Page) -> Image.Image:
    w, h, bpl = page.width, page.height, page.bytes_per_line
    if page.bits_per_pixel == 1 and page.color_space == CUPS_CSPACE_K:
        stride = (w + 7) // 8
        if bpl == stride:
            raw = page.data
        else:
            raw = b"".join(page.data[y * bpl:y * bpl + stride] for y in range(h))
        # CUPS K: 1 = black.  PIL "1": 0 = black, 1 = white.
        img = Image.frombytes("1", (w, h), raw)
        return ImageOps.invert(img).convert("L")

    if page.bits_per_pixel == 8 and page.color_space in (
            CUPS_CSPACE_K, CUPS_CSPACE_W):
        raw = b"".join(page.data[y * bpl:y * bpl + w] for y in range(h))
        img = Image.frombytes("L", (w, h), raw)
        return img if page.color_space == CUPS_CSPACE_K else ImageOps.invert(img)

    if page.bits_per_pixel in (24, 32) and page.color_space in (
            CUPS_CSPACE_RGB, CUPS_CSPACE_SRGB):
        channels = page.bits_per_pixel // 8
        mode = "RGB" if channels == 3 else "RGBA"
        raw = b"".join(page.data[y * bpl:y * bpl + w * channels]
                       for y in range(h))
        return Image.frombytes(mode, (w, h), raw).convert("L")

    raise RasterError(
        f"unsupported raster format: {page.bits_per_pixel} bpp, "
        f"colorspace {page.color_space}")


def dithered(canvas: Image.Image, dither="fs", threshold=128) -> Image.Image:
    if dither == "threshold":
        bw = canvas.point(lambda p: 0 if p < threshold else 255)
        return bw.convert("1", dither=Image.Dither.NONE)
    if dither == "none":
        return canvas.convert("1", dither=Image.Dither.NONE)
    return canvas.convert("1", dither=Image.Dither.FLOYDSTEINBERG)


def prepare_page(page: Page, head_margin=HEAD_MARGIN, feed_start=FEED_START,
                 feed_end=FEED_END, rotation=ROTATION, dither="fs",
                 threshold=128, x_shift=0):
    """Return (packed_bytes, width_dots, height_dots) ready for protocol.bitmap."""
    img = page_to_image(page)
    w, h = img.size
    bilevel = page.bits_per_pixel == 1

    inner_w = w - feed_start - feed_end
    inner_h = h - 2 * head_margin
    if inner_w < 8 or inner_h < 8:
        inner_w, inner_h = w, h
        feed_start = head_margin = 0

    canvas = Image.new("L", (w, h), 255)
    if bilevel:
        # The raster is already 1bpp.  Cropping the mechanical margins keeps
        # every pixel intact; resampling + dithering would add stray dots.
        cropped = img.crop((feed_start, head_margin,
                            w - feed_end, h - head_margin))
        canvas.paste(cropped, (feed_start, head_margin + x_shift))
        dither = "none"
    else:
        if (inner_w, inner_h) != (w, h):
            img = img.resize((inner_w, inner_h), Image.LANCZOS)
        canvas.paste(img, (feed_start, head_margin + x_shift))

    rotated = canvas.transpose(
        Image.Transpose.ROTATE_270 if rotation == 270
        else Image.Transpose.ROTATE_90)

    mono = dithered(rotated, dither, threshold)
    # PIL "1" has 0 = black; the printer wants 1 = black.
    packed = bytes(b ^ 0xFF for b in mono.tobytes())
    return packed, mono.width, mono.height
