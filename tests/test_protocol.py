import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pristar_p15 import protocol  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_bitmap_header(self):
        data = protocol.bitmap(96, 320, b"\x00" * (12 * 320))
        self.assertEqual(data[:8],
                         bytes([0x1D, 0x76, 0x30, 0x00, 12, 0, 0x40, 0x01]))
        self.assertEqual(len(data), 8 + 12 * 320)

    def test_bitmap_header_wide(self):
        data = protocol.bitmap(320, 96, b"\x00" * (40 * 96))
        self.assertEqual(data[:8],
                         bytes([0x1D, 0x76, 0x30, 0x00, 40, 0, 96, 0]))

    def test_page_sequence(self):
        payload = b"\x00" * (12 * 320)
        p = protocol.page(payload, 96, 320, density=3, paper_type="gap")
        self.assertTrue(p.startswith(bytes([0x1F, 0x70, 0x02, 3])))
        self.assertTrue(p.startswith(bytes([0x1F, 0x70, 0x02, 3]) +
                                    bytes([0x10, 0xFF, 0x10, 0x00, 3])))
        self.assertIn(protocol.WAKEUP, p)
        self.assertIn(protocol.ENABLE, p)
        self.assertTrue(p.endswith(bytes([0x1D, 0x0C]) + protocol.STOP))

    def test_page_continuous(self):
        p = protocol.page(b"\x00" * 10, 8, 10, paper_type="continuous", feed=150)
        self.assertTrue(p.endswith(bytes([0x1B, 0x4A, 150]) + protocol.STOP))


if __name__ == "__main__":
    unittest.main()
