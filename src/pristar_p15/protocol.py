"""L11 command builder for the Pristar/Marklife P15."""

WAKEUP = b"\x00" * 15
ENABLE = bytes.fromhex("10FFF102")
STOP = bytes.fromhex("10FFF145")
POSITION_GAP = bytes.fromhex("1D0C")


def set_density(value):
    return bytes([0x1F, 0x70, 0x02, value & 0xFF])


def set_thickness(value):
    return bytes([0x10, 0xFF, 0x10, 0x00, value & 0xFF])


def feed_dots(dots):
    return bytes([0x1B, 0x4A, dots & 0xFF])


def feed_lines(lines):
    return bytes([0x1B, 0x64, lines & 0xFF])


def bitmap(width_dots, height_dots, packed):
    """GS v 0 raster header followed by 1bpp MSB-first rows (1 = black)."""
    bytes_per_row = (width_dots + 7) // 8
    header = bytes([
        0x1D, 0x76, 0x30, 0x00,
        bytes_per_row & 0xFF, (bytes_per_row >> 8) & 0xFF,
        height_dots & 0xFF, (height_dots >> 8) & 0xFF,
    ])
    return header + packed


def page(packed, width_dots, height_dots, density=2, paper_type="gap",
         feed=100, send_density=True):
    """Complete print sequence for one label/page."""
    out = bytearray()
    if send_density:
        out += set_density(density)
    out += set_thickness(density)
    out += WAKEUP
    out += ENABLE
    out += bitmap(width_dots, height_dots, packed)
    if paper_type == "continuous":
        out += feed_dots(feed)
    else:
        out += POSITION_GAP
    out += STOP
    return bytes(out)
