#!/usr/bin/env python3
"""Generate ppd/pristar-p15.ppd from the label size table."""

import os

# (display name, width mm along feed, height mm across head)
SIZES = [
    ("22x12 mm", 22, 12),
    ("22x14 mm", 22, 14),
    ("26x15 mm", 26, 15),
    ("30x12 mm", 30, 12),
    ("30x14 mm", 30, 14),
    ("30x15 mm", 30, 15),
    ("40x12 mm", 40, 12),
    ("40x14 mm", 40, 14),
    ("40x15 mm", 40, 15),
    ("50x15 mm", 50, 15),
]

def size_name(w, h):
    # Adobe PPD naming: short side x long side, rotated, full bleed.
    return f"{h}x{w}mmRotated.Fullbleed"

HEADER = '''*PPD-Adobe: "4.3"
*FormatVersion: "4.3"
*FileVersion: "0.1.0"
*LanguageVersion: English
*LanguageEncoding: ISOLatin1
*PCFileName: "PRISTAR15.PPD"
*Manufacturer: "Pristar"
*Product: "(P15)"
*ModelName: "Pristar P15"
*ShortNickName: "Pristar P15"
*NickName: "Pristar P15 Label Printer"
*PSVersion: "(3010.000) 0"
*LanguageLevel: "3"
*ColorDevice: True
*DefaultColorSpace: Gray
*FileSystem: False
*Throughput: "1"
*LandscapeOrientation: Plus90
*TTRasterizer: Type42
*1284DeviceID: "MFG:Pristar;MDL:P15;CMD:P15"
*cupsColorSpace: 3
*cupsFilter2: "application/vnd.cups-raster application/vnd.pristar.p15 0 p15-raster"
*OpenUI *Resolution/Output Resolution: PickOne
*DefaultResolution: 203dpi
*Resolution 203dpi/203 dpi: "<</HWResolution[203 203]>>setpagedevice"
*CloseUI: *Resolution
'''


def pt(mm):
    return round(mm / 25.4 * 72.0, 2)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, "..", "ppd", "pristar-p15.ppd")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    lines = [HEADER]
    lines.append("*OpenUI *PageSize/Page Size: PickOne")
    lines.append("*DefaultPageSize: " + size_name(40, 12))
    for disp, w, h in SIZES:
        name = size_name(w, h)
        lines.append(
            f'*PageSize {name}/{disp}: '
            f'"<</PageSize[{pt(w):g} {pt(h):g}]/ImagingBBox null>>setpagedevice"')
    lines.append("*CloseUI: *PageSize")
    lines.append("*OpenUI *PageRegion/Page Region: PickOne")
    lines.append("*DefaultPageRegion: " + size_name(40, 12))
    for disp, w, h in SIZES:
        name = size_name(w, h)
        lines.append(
            f'*PageRegion {name}/{disp}: '
            f'"<</PageSize[{pt(w):g} {pt(h):g}]/ImagingBBox null>>setpagedevice"')
    lines.append("*CloseUI: *PageRegion")
    lines.append("*DefaultImageableArea: " + size_name(40, 12))
    for disp, w, h in SIZES:
        name = size_name(w, h)
        lines.append(f'*ImageableArea {name}/{disp}: '
                     f'"0 0 {pt(w):g} {pt(h):g}"')
    lines.append("*DefaultPaperDimension: " + size_name(40, 12))
    for disp, w, h in SIZES:
        name = size_name(w, h)
        lines.append(f'*PaperDimension {name}/{disp}: "{pt(w):g} {pt(h):g}"')

    lines.append('''
*OpenUI *P15Density/Print Density: PickOne
*DefaultP15Density: 2
*P15Density 1/Light: ""
*P15Density 2/Normal: ""
*P15Density 3/Dark: ""
*CloseUI: *P15Density
*OpenUI *P15PaperType/Paper Type: PickOne
*DefaultP15PaperType: Gap
*P15PaperType Gap/Label with gap: ""
*P15PaperType Continuous/Continuous: ""
*CloseUI: *P15PaperType
*OpenUI *P15Dither/Image Dithering: PickOne
*DefaultP15Dither: Threshold
*P15Dither Threshold/Threshold (text, crisp): ""
*P15Dither FS/Floyd-Steinberg (photos): ""
*P15Dither None/None: ""
*CloseUI: *P15Dither
*OpenUI *P15FeedDots/Continuous Feed (dots): PickOne
*DefaultP15FeedDots: 100
*P15FeedDots 100/100: ""
*P15FeedDots 150/150: ""
*P15FeedDots 200/200: ""
*CloseUI: *P15FeedDots
''')

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", os.path.normpath(out_path))


if __name__ == "__main__":
    main()
