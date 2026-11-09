"""Minimal CUPS raster (RaS3 / RaS2) reader.

The CUPS pipeline feeds application/vnd.cups-raster to our filter.  With a
PPD that requests CUPS_CSPACE_K and 1 bit per color, cups-filters' pdftoraster
emits uncompressed 1bpp pages, which is exactly what the P15 needs.
"""

import struct
from dataclasses import dataclass

# Page header offsets (cups_page_header2_t) and total size.
_HDR2_SIZE = 1796
_HDR1_SIZE = 420

_OFF_WIDTH = 372
_OFF_HEIGHT = 376
_OFF_BPC = 384
_OFF_BPP = 388
_OFF_BPL = 392
_OFF_CSPACE = 400
_OFF_COMPRESSION = 404
_OFF_NUM_COLORS = 420
_OFF_PAGE_SIZE = 428
_OFF_PAGE_NAME = 1732

_SYNCS = {
    b"RaS3": (">", 3), b"3SaR": ("<", 3),
    b"RaS2": (">", 2), b"2SaR": ("<", 2),
    b"RaSt": (">", 1), b"tSaR": ("<", 1),
}

CUPS_CSPACE_W = 0
CUPS_CSPACE_RGB = 1
CUPS_CSPACE_K = 3
CUPS_CSPACE_SRGB = 19
CUPS_CSPACE_ADOBERGB = 20


class RasterError(Exception):
    pass


@dataclass
class Page:
    width: int
    height: int
    bits_per_color: int
    bits_per_pixel: int
    bytes_per_line: int
    color_space: int
    compression: int
    num_colors: int
    page_size: tuple  # points (w, h)
    page_size_name: str
    data: bytes


def _read_exact(stream, n):
    chunks = []
    left = n
    while left > 0:
        b = stream.read(left)
        if not b:
            raise RasterError(f"unexpected EOF (wanted {n} bytes, got {n - left})")
        chunks.append(b)
        left -= len(b)
    return b"".join(chunks)


def read_pages(stream):
    """Yield Page objects until EOF.  Raises RasterError on bad input."""
    while True:
        sync = stream.read(4)
        if not sync:
            return
        if len(sync) < 4:
            raise RasterError("truncated raster sync word")
        if sync not in _SYNCS:
            raise RasterError(f"unknown raster sync word {sync!r}")
        endian, version = _SYNCS[sync]
        hdr_size = _HDR1_SIZE if version == 1 else _HDR2_SIZE
        hdr = _read_exact(stream, hdr_size)

        def u32(off):
            if off + 4 > len(hdr):
                return 0
            return struct.unpack_from(endian + "I", hdr, off)[0]

        def f32(off):
            if off + 4 > len(hdr):
                return 0.0
            return struct.unpack_from(endian + "f", hdr, off)[0]

        if version == 1:
            raise RasterError("CUPS raster v1 is not supported")

        width = u32(_OFF_WIDTH)
        height = u32(_OFF_HEIGHT)
        bpc = u32(_OFF_BPC)
        bpp = u32(_OFF_BPP)
        bpl = u32(_OFF_BPL)
        cspace = u32(_OFF_CSPACE)
        compression = u32(_OFF_COMPRESSION)
        ncolors = u32(_OFF_NUM_COLORS)
        page_size = (f32(_OFF_PAGE_SIZE), f32(_OFF_PAGE_SIZE + 4))
        name = hdr[_OFF_PAGE_NAME:_OFF_PAGE_NAME + 64].split(b"\0")[0].decode(
            "latin-1", "replace")

        if width <= 0 or height <= 0 or bpp <= 0 or bpl <= 0:
            raise RasterError(
                f"invalid page geometry {width}x{height} bpp={bpp} bpl={bpl}")
        if compression != 0:
            raise RasterError(f"unsupported raster compression {compression}")

        data = _read_exact(stream, bpl * height)
        yield Page(width=width, height=height, bits_per_color=bpc,
                   bits_per_pixel=bpp, bytes_per_line=bpl,
                   color_space=cspace, compression=compression,
                   num_colors=ncolors, page_size=page_size,
                   page_size_name=name, data=data)
