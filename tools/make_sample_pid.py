#!/usr/bin/env python3
"""Generate a synthetic but realistic P&ID as a vector PDF.

Used as a test fixture: it exercises the full pipeline (tiling, text-layer
extraction, tag parsing, merging, reporting) on a sheet whose correct answer is
known, without needing a real drawing or an API key.

    python tools/make_sample_pid.py out.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

# D-size sheet, landscape, in points (72 pt = 1 inch).
W, H = 34 * 72, 22 * 72

BLACK = (0, 0, 0)
LW = 1.0          # instrument / signal line weight
PW = 2.0          # process line weight


def text(page, x, y, s, size=9, bold=False):
    page.insert_text((x, y), s, fontsize=size,
                     fontname="hebo" if bold else "helv", color=BLACK)


def pipe(shape, pts, width=PW):
    shape.draw_polyline([pymupdf.Point(*p) for p in pts])
    shape.finish(color=BLACK, width=width, closePath=False)


def signal(shape, pts):
    """Dashed line = electrical signal."""
    shape.draw_polyline([pymupdf.Point(*p) for p in pts])
    shape.finish(color=BLACK, width=LW, dashes="[4 3] 0", closePath=False)


def bubble(page, shape, x, y, letters, number, panel=False, r=17):
    shape.draw_circle(pymupdf.Point(x, y), r)
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))
    if panel:
        shape.draw_line(pymupdf.Point(x - r, y), pymupdf.Point(x + r, y))
        shape.finish(color=BLACK, width=LW)
    text(page, x - len(letters) * 3.0, y - 3, letters, 9)
    text(page, x - len(number) * 2.6, y + 10, number, 8)


def gate_valve(shape, x, y, s=9):
    """Bow-tie: two triangles apex to apex."""
    shape.draw_polyline([pymupdf.Point(x - s, y - s), pymupdf.Point(x - s, y + s),
                         pymupdf.Point(x, y), pymupdf.Point(x - s, y - s)])
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))
    shape.draw_polyline([pymupdf.Point(x + s, y - s), pymupdf.Point(x + s, y + s),
                         pymupdf.Point(x, y), pymupdf.Point(x + s, y - s)])
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))


def globe_valve(shape, x, y, s=9):
    gate_valve(shape, x, y, s)
    shape.draw_circle(pymupdf.Point(x, y), s * 0.42)
    shape.finish(color=BLACK, width=LW, fill=BLACK)


def check_valve(shape, x, y, s=9):
    gate_valve(shape, x, y, s)
    shape.draw_line(pymupdf.Point(x + s * 0.2, y - s), pymupdf.Point(x + s * 0.2, y + s))
    shape.finish(color=BLACK, width=LW * 1.6)


def control_valve(page, shape, x, y, tag, fail="FC", s=10):
    """Bow-tie body with a diaphragm actuator dome on top."""
    gate_valve(shape, x, y, s)
    shape.draw_line(pymupdf.Point(x, y - s), pymupdf.Point(x, y - s - 9))
    shape.finish(color=BLACK, width=LW)
    shape.draw_sector(pymupdf.Point(x, y - s - 9), pymupdf.Point(x - 11, y - s - 9), 180)
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))
    text(page, x + s + 3, y + 3, tag, 8)
    text(page, x + s + 3, y + 13, fail, 7)


def relief_valve(page, shape, x, y, tag, set_p, s=9):
    """Angle body with a spring bonnet."""
    shape.draw_polyline([pymupdf.Point(x - s, y + s), pymupdf.Point(x - s, y - s),
                         pymupdf.Point(x, y), pymupdf.Point(x - s, y + s)])
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))
    shape.draw_polyline([pymupdf.Point(x + s, y - s * 2), pymupdf.Point(x - s * 0.2, y - s * 2),
                         pymupdf.Point(x, y), pymupdf.Point(x + s, y - s * 2)])
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))
    shape.draw_line(pymupdf.Point(x, y - s * 2), pymupdf.Point(x, y - s * 3.2))
    shape.finish(color=BLACK, width=LW)
    shape.draw_rect(pymupdf.Rect(x - 6, y - s * 4.2, x + 6, y - s * 3.2))
    shape.finish(color=BLACK, width=LW, fill=(1, 1, 1))
    text(page, x + 12, y - s * 3, tag, 8)
    text(page, x + 12, y - s * 3 + 10, f"SET {set_p}", 7)


def pump(page, shape, x, y, tag, service, r=22):
    shape.draw_circle(pymupdf.Point(x, y), r)
    shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
    shape.draw_polyline([pymupdf.Point(x, y - r), pymupdf.Point(x + r * 1.5, y - r * 1.2),
                         pymupdf.Point(x + r * 1.5, y + r * 1.2), pymupdf.Point(x, y + r)])
    shape.finish(color=BLACK, width=PW, closePath=False)
    shape.draw_line(pymupdf.Point(x - r * 1.6, y + r + 6), pymupdf.Point(x + r * 1.8, y + r + 6))
    shape.finish(color=BLACK, width=PW)
    text(page, x - 24, y + r + 20, tag, 10, bold=True)
    text(page, x - 30, y + r + 32, service, 7)


def vessel(page, shape, x, y, w, h, tag, service, horizontal=True):
    """Capsule with elliptical heads."""
    if horizontal:
        shape.draw_rect(pymupdf.Rect(x, y, x + w, y + h))
        shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
        for cx in (x, x + w):
            shape.draw_sector(pymupdf.Point(cx, y + h / 2), pymupdf.Point(cx, y), 180,
                              fullSector=False)
            shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
    else:
        shape.draw_rect(pymupdf.Rect(x, y, x + w, y + h))
        shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
    text(page, x + 6, y - 8, tag, 11, bold=True)
    text(page, x + 6, y + h + 14, service, 7)


def column(page, shape, x, y, w, h, tag, service, trays=8):
    vessel(page, shape, x, y, w, h, tag, service, horizontal=False)
    for i in range(1, trays + 1):
        ty = y + h * i / (trays + 1)
        shape.draw_line(pymupdf.Point(x + 4, ty), pymupdf.Point(x + w - 4, ty))
        shape.finish(color=BLACK, width=LW)


def exchanger(page, shape, x, y, w, h, tag, service):
    """Shell and tube: rectangle with tube bundle passes."""
    shape.draw_rect(pymupdf.Rect(x, y, x + w, y + h))
    shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
    for frac in (0.3, 0.5, 0.7):
        ty = y + h * frac
        shape.draw_polyline([pymupdf.Point(x, ty), pymupdf.Point(x + w * 0.82, ty),
                             pymupdf.Point(x + w * 0.82, ty + h * 0.1),
                             pymupdf.Point(x, ty + h * 0.1)])
        shape.finish(color=BLACK, width=LW, closePath=False)
    text(page, x + 6, y - 8, tag, 11, bold=True)
    text(page, x + 6, y + h + 14, service, 7)


def air_cooler(page, shape, x, y, w, h, tag, service):
    shape.draw_rect(pymupdf.Rect(x, y, x + w, y + h))
    shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
    shape.draw_circle(pymupdf.Point(x + w / 2, y + h + 18), 15)
    shape.finish(color=BLACK, width=LW)
    shape.draw_line(pymupdf.Point(x + w / 2 - 15, y + h + 18), pymupdf.Point(x + w / 2 + 15, y + h + 18))
    shape.finish(color=BLACK, width=LW)
    text(page, x + 6, y - 8, tag, 11, bold=True)
    text(page, x + 6, y + h + 40, service, 7)


def compressor(page, shape, x, y, tag, service, r=24):
    shape.draw_circle(pymupdf.Point(x, y), r)
    shape.finish(color=BLACK, width=PW, fill=(1, 1, 1))
    shape.draw_polyline([pymupdf.Point(x - r * 1.4, y - r * 0.9), pymupdf.Point(x + r * 1.4, y - r * 0.5),
                         pymupdf.Point(x + r * 1.4, y + r * 0.5), pymupdf.Point(x - r * 1.4, y + r * 0.9)])
    shape.finish(color=BLACK, width=PW, closePath=True, fill=None)
    text(page, x - 24, y + r + 24, tag, 10, bold=True)
    text(page, x - 30, y + r + 36, service, 7)


def offpage(page, shape, x, y, label, ref, to_right=True):
    d = 1 if to_right else -1
    pts = [(x, y - 10), (x + 40 * d, y - 10), (x + 58 * d, y), (x + 40 * d, y + 10), (x, y + 10)]
    shape.draw_polyline([pymupdf.Point(*p) for p in pts])
    shape.finish(color=BLACK, width=LW, closePath=True, fill=(1, 1, 1))
    text(page, x + (6 if to_right else -52), y - 1, label, 7)
    text(page, x + (6 if to_right else -52), y + 8, ref, 6)


def build(path: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    shape = page.new_shape()

    # --- sheet border and title block ---------------------------------
    shape.draw_rect(pymupdf.Rect(20, 20, W - 20, H - 20))
    shape.finish(color=BLACK, width=2.0)
    tb = pymupdf.Rect(W - 520, H - 150, W - 25, H - 25)
    shape.draw_rect(tb)
    shape.finish(color=BLACK, width=1.5)

    # --- V-101 feed surge drum ----------------------------------------
    vessel(page, shape, 200, 300, 230, 120, "V-101", "FEED SURGE DRUM", horizontal=True)
    relief_valve(page, shape, 380, 250, "PSV-101", "150 PSIG")
    pipe(shape, [(380, 250 - 38), (380, 180), (520, 180)])
    text(page, 430, 172, '3"-FL-1150-A1A  TO FLARE', 7)
    offpage(page, shape, 520, 180, "TO FLARE HDR", "DWG D-1002")

    bubble(page, shape, 150, 250, "LT", "101")
    bubble(page, shape, 150, 190, "LIC", "101", panel=True)
    signal(shape, [(150, 233), (150, 207)])
    pipe(shape, [(200, 330), (150, 330), (150, 267)], width=LW)

    # feed in
    offpage(page, shape, 60, 360, "FEED FROM U-100", "DWG D-1000", to_right=True)
    pipe(shape, [(118, 360), (200, 360)])
    text(page, 120, 352, '8"-P-1101-A1A-HC', 7)
    gate_valve(shape, 165, 360)

    # --- P-101A/B feed pumps ------------------------------------------
    pipe(shape, [(315, 420), (315, 500), (250, 500)])
    text(page, 320, 465, '6"-P-1102-A1A', 7)
    for i, (px, tag) in enumerate(((190, "P-101A"), (190, "P-101B"))):
        py = 500 + i * 130
        pump(page, shape, px, py, tag, "FEED PUMP" + (" (SPARE)" if i else ""))
        gate_valve(shape, 250, py)
        pipe(shape, [(240, py), (212, py)])
        pipe(shape, [(168, py), (120, py), (120, py + 0)], width=PW)
        check_valve(shape, 120, py - 30)
        pipe(shape, [(120, py - 12), (120, py)])
        pipe(shape, [(120, py - 48), (120, py - 70), (560, py - 70)])
    pipe(shape, [(250, 500), (250, 630)])
    bubble(page, shape, 95, 445, "PI", "102")
    pipe(shape, [(95, 462), (95, 470), (120, 470)], width=LW)

    # --- FIC-1010 flow control loop -----------------------------------
    pipe(shape, [(560, 430), (560, 560), (760, 560)])
    text(page, 570, 425, '6"-P-1103-A1A-HC', 7)
    shape.draw_line(pymupdf.Point(640, 552), pymupdf.Point(640, 568))
    shape.finish(color=BLACK, width=LW)
    shape.draw_line(pymupdf.Point(652, 552), pymupdf.Point(652, 568))
    shape.finish(color=BLACK, width=LW)
    text(page, 620, 585, "FE-1010", 7)
    bubble(page, shape, 646, 500, "FT", "1010")
    signal(shape, [(646, 552), (646, 517)])
    bubble(page, shape, 646, 440, "FIC", "1010", panel=True)
    signal(shape, [(646, 483), (646, 457)])
    control_valve(page, shape, 720, 560, "FV-1010", "FC")
    signal(shape, [(663, 440), (720, 440), (720, 535)])

    # --- E-201 feed/effluent exchanger --------------------------------
    exchanger(page, shape, 800, 500, 180, 130, "E-201", "FEED / EFFLUENT EXCHANGER")
    pipe(shape, [(760, 560), (800, 560)])
    pipe(shape, [(980, 560), (1060, 560), (1060, 400)])
    text(page, 990, 552, '6"-P-1104-A1A-HC', 7)
    bubble(page, shape, 1020, 480, "TI", "201")

    # --- T-301 fractionator -------------------------------------------
    column(page, shape, 1200, 230, 130, 480, "T-301", "FRACTIONATOR", trays=10)
    pipe(shape, [(1060, 400), (1200, 400)])
    gate_valve(shape, 1140, 400)
    bubble(page, shape, 1160, 300, "PI", "301")
    pipe(shape, [(1160, 317), (1160, 340), (1200, 340)], width=LW)

    bubble(page, shape, 1380, 300, "TIC", "301", panel=True)
    bubble(page, shape, 1380, 370, "TT", "301")
    signal(shape, [(1380, 353), (1380, 317)])
    pipe(shape, [(1330, 380), (1363, 375)], width=LW)

    bubble(page, shape, 1160, 660, "LT", "301")
    pipe(shape, [(1200, 660), (1177, 660)], width=LW)

    # overhead
    pipe(shape, [(1265, 230), (1265, 160), (1560, 160)])
    text(page, 1290, 152, '10"-V-1301-A1A-HC  OVERHEAD VAPOUR', 7)

    # --- E-301 overhead air cooler ------------------------------------
    air_cooler(page, shape, 1560, 120, 200, 90, "E-301", "OVERHEAD CONDENSER")
    pipe(shape, [(1760, 160), (1860, 160), (1860, 300)])

    # --- V-302 reflux drum --------------------------------------------
    vessel(page, shape, 1800, 300, 220, 110, "V-302", "REFLUX DRUM", horizontal=True)
    relief_valve(page, shape, 1960, 255, "PSV-302", "75 PSIG")
    bubble(page, shape, 1760, 340, "LT", "302")
    bubble(page, shape, 1760, 275, "LIC", "302", panel=True)
    signal(shape, [(1760, 323), (1760, 292)])

    # --- P-301A/B reflux pumps ----------------------------------------
    pipe(shape, [(1910, 410), (1910, 500)])
    pump(page, shape, 1910, 540, "P-301A", "REFLUX PUMP")
    pipe(shape, [(1885, 565), (1885, 640), (1400, 640)])
    control_valve(page, shape, 1600, 640, "LV-302", "FO")
    signal(shape, [(1760, 258), (1600, 258), (1600, 615)])
    text(page, 1420, 632, '4"-P-1302-A1A', 7)
    pipe(shape, [(1400, 640), (1330, 640)])

    # --- C-401 off-gas compressor -------------------------------------
    compressor(page, shape, 2150, 540, "C-401", "OFF-GAS COMPRESSOR")
    pipe(shape, [(2020, 360), (2100, 360), (2100, 540), (2115, 540)])
    globe_valve(shape, 2100, 450)
    pipe(shape, [(2185, 540), (2280, 540)])
    bubble(page, shape, 2240, 470, "PT", "401")
    pipe(shape, [(2240, 487), (2240, 540)], width=LW)
    bubble(page, shape, 2240, 410, "PSHH", "401", panel=True)
    signal(shape, [(2240, 453), (2240, 427)])
    offpage(page, shape, 2280, 540, "TO FUEL GAS", "DWG D-1005")

    # --- bottoms --------------------------------------------------------
    pipe(shape, [(1265, 710), (1265, 790), (1700, 790)])
    gate_valve(shape, 1400, 790)
    text(page, 1300, 782, '6"-P-1303-A1A-HT  BOTTOMS', 7)
    offpage(page, shape, 1700, 790, "TO STORAGE", "DWG D-1004")

    # --- cooling water utility -----------------------------------------
    offpage(page, shape, 700, 950, "CWS", "DWG D-2001", to_right=True)
    pipe(shape, [(758, 950), (890, 950), (890, 630)])
    text(page, 770, 942, '8"-CWS-2101-B1A', 7)
    gate_valve(shape, 890, 720)
    offpage(page, shape, 700, 1010, "CWR", "DWG D-2001", to_right=True)
    pipe(shape, [(758, 1010), (950, 1010), (950, 630)])
    text(page, 770, 1002, '8"-CWR-2102-B1A', 7)

    shape.commit()

    # --- notes and title block text -------------------------------------
    notes = [
        "NOTES:",
        "1. ALL VALVES 6\" AND LARGER TO BE GATE UNLESS NOTED OTHERWISE.",
        "2. INSTRUMENT AIR SUPPLY TO ALL CONTROL VALVES PER DWG D-3001.",
        "3. PSV-101 AND PSV-302 DISCHARGE TO FLARE HEADER, DWG D-1002.",
        "4. P-101B IS AN INSTALLED SPARE, AUTO-START ON LOW DISCHARGE PRESSURE.",
        "5. LINE CLASS A1A = CARBON STEEL 150#, B1A = CARBON STEEL 150# UTILITY.",
    ]
    for i, line in enumerate(notes):
        text(page, 90, 1150 + i * 16, line, 9, bold=(i == 0))

    text(page, W - 505, H - 125, "ACME CHEMICALS - GULF COAST PLANT", 12, bold=True)
    text(page, W - 505, H - 105, "UNIT 1300 - FRACTIONATION", 10)
    text(page, W - 505, H - 85, "PIPING & INSTRUMENTATION DIAGRAM", 10)
    text(page, W - 505, H - 60, "DWG No. D-1301", 11, bold=True)
    text(page, W - 250, H - 60, "REV. 3", 11, bold=True)
    text(page, W - 505, H - 40, "SCALE: NTS        DATE: 2026-09-15", 8)

    doc.save(path)
    doc.close()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sample_pid.pdf"
    build(out)
    print(f"wrote {out}")
