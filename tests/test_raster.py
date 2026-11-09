import io
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pristar_p15 import raster  # noqa: E402


def make_raster_page(width=320, height=96, bpl=40, bpp=1, cspace=3,
                     payload=None, sync=b"3SaR"):
    hdr = bytearray(1796)
    for off, value in ((372, width), (376, height), (384, 8), (388, bpp),
                       (392, bpl), (400, cspace), (404, 0), (420, 1)):
        struct.pack_into("<I", hdr, off, value)
    struct.pack_into("<f", hdr, 428, 113.39)
    struct.pack_into("<f", hdr, 432, 34.02)
    if payload is None:
        payload = b"\x00" * (bpl * height)
    return sync + bytes(hdr) + payload


class RasterTests(unittest.TestCase):
    def test_single_page(self):
        buf = io.BytesIO(make_raster_page())
        pages = list(raster.read_pages(buf))
        self.assertEqual(len(pages), 1)
        p = pages[0]
        self.assertEqual((p.width, p.height), (320, 96))
        self.assertEqual((p.bits_per_color, p.bits_per_pixel), (8, 1))
        self.assertEqual(p.bytes_per_line, 40)
        self.assertEqual(p.color_space, 3)
        self.assertEqual(p.compression, 0)
        self.assertEqual(len(p.data), 40 * 96)
        self.assertAlmostEqual(p.page_size[0], 113.39, places=2)

    def test_two_pages(self):
        buf = io.BytesIO(make_raster_page() + make_raster_page())
        pages = list(raster.read_pages(buf))
        self.assertEqual(len(pages), 2)

    def test_bad_sync(self):
        with self.assertRaises(raster.RasterError):
            list(raster.read_pages(io.BytesIO(b"NOPE")))

    def test_truncated(self):
        with self.assertRaises(raster.RasterError):
            list(raster.read_pages(io.BytesIO(make_raster_page()[:-10])))


if __name__ == "__main__":
    unittest.main()
