import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pristar_p15 import image  # noqa: E402
from pristar_p15.raster import Page  # noqa: E402


def make_page(fill_byte, width=320, height=96):
    bpl = (width + 7) // 8
    data = bytes([fill_byte]) * (bpl * height)
    return Page(width=width, height=height, bits_per_color=8,
                bits_per_pixel=1, bytes_per_line=bpl, color_space=3,
                compression=0, num_colors=1, page_size=(113.39, 34.02),
                page_size_name="12x40mmRotated.Fullbleed", data=data)


class ImageTests(unittest.TestCase):
    def test_dimensions_and_rotation(self):
        packed, w, h = image.prepare_page(make_page(0x00))
        self.assertEqual((w, h), (96, 320))
        self.assertEqual(len(packed), 12 * 320)

    def test_white_is_zero(self):
        packed, _w, _h = image.prepare_page(make_page(0x00))
        self.assertEqual(set(packed), {0x00})

    def test_black_is_one(self):
        # No margins: a fully black page must pack to 0xFF (1 = black).
        packed, _w, _h = image.prepare_page(
            make_page(0xFF), head_margin=0, feed_start=0, feed_end=0)
        self.assertEqual(set(packed), {0xFF})

    def test_rotation_90(self):
        _packed, w, h = image.prepare_page(make_page(0x00), rotation=90)
        self.assertEqual((w, h), (96, 320))

    def test_small_page_falls_back(self):
        # A page smaller than the margins must not crash.
        page = make_page(0x00, width=8, height=8)
        packed, w, h = image.prepare_page(page)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertEqual(len(packed), ((w + 7) // 8) * h)


if __name__ == "__main__":
    unittest.main()
