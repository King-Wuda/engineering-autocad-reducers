#!/usr/bin/env python3
"""Convert a vector P&ID PDF into a true-scale, layered DXF.

This does NOT produce intelligent Plant 3D P&ID objects - those live in the
project database and in AcPp custom objects inside the DWG, and cannot be
authored outside Plant 3D. What it produces is an exact geometric tracing base
at 1:1 in millimetres, with every entity sorted onto a layer by service, which
is what a Plant 3D operator needs underneath in order to place real components
on top.

Service layers are derived from stroke colour. The colour coding was verified
against the drawing by reading it: blue is suction, red is discharge and hot
gas, brown and rust are liquid, tan is oil, teal is cooling water, magenta is
instrument signal.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import ezdxf
import pymupdf
from ezdxf.math import Vec3

#: PDF points -> millimetres. A0 is 1189 x 841 mm = 3370 x 2384 pt.
PT_MM = 25.4 / 72.0

#: Stroke colour -> (layer, AutoCAD Color Index, description).
#: Keys are rounded RGB as PyMuPDF reports them.
COLOUR_LAYERS = {
    (0.0, 0.0, 0.0):       ("PID-EQUIPMENT",   7,   "Equipment, valve and instrument symbols"),
    (0.753, 0.753, 0.753): ("PID-AREA",        8,   "Area / package boundary"),
    (0.012, 0.012, 0.722): ("PID-TITLEBLOCK",  5,   "Title block and logo artwork"),
    (1.0, 0.0, 0.0):       ("PID-RD-DISCHARGE", 1,  "Refrigerant discharge and hot gas"),
    (0.6, 0.0, 0.0):       ("PID-RB-OIL-BAL",  14,  "Refrigerant / oil balance and drain"),
    (0.6, 0.447, 0.298):   ("PID-OL-OIL",      42,  "Lubricating oil"),
    (0.686, 0.502, 0.31):  ("PID-RL-LIQUID",   44,  "Refrigerant liquid"),
    (0.729, 0.282, 0.106): ("PID-RP-PUMPED",   30,  "Refrigerant pumped liquid"),
    (0.498, 0.749, 1.0):   ("PID-RS-SUCTION",  141, "Refrigerant suction and wet return"),
    (0.0, 0.8, 0.6):       ("PID-CS-WATER",    130, "Cooling / sea water"),
    (1.0, 0.0, 1.0):       ("PID-INSTR-SIGNAL", 6,  "Instrument signal"),
    (0.8, 0.0, 0.8):       ("PID-INSTR-BUBBLE", 216, "Instrument bubbles"),
    (0.0, 0.647, 0.867):   ("PID-NOTE",        4,   "Blue annotation text"),
    (1.0, 1.0, 1.0):       ("PID-WHITE-FILL",  255, "White symbol fills"),
}
FALLBACK = ("PID-MISC", 251, "Unclassified geometry")
TEXT_LAYER = ("PID-TEXT", 7, "Drawing text, tags and line numbers")


def layer_for(colour):
    if colour is None:
        return FALLBACK
    key = tuple(round(v, 3) for v in colour)
    if key in COLOUR_LAYERS:
        return COLOUR_LAYERS[key]
    # Nearest by squared distance, so a stray anti-aliased shade still lands
    # on the right service rather than in a junk layer.
    best, bestd = FALLBACK, 0.05
    for k, v in COLOUR_LAYERS.items():
        dist = sum((a - b) ** 2 for a, b in zip(k, key))
        if dist < bestd:
            best, bestd = v, dist
    return best


class Converter:
    def __init__(self, pdf: Path, page_no: int = 1):
        self.doc = pymupdf.open(pdf)
        self.page = self.doc[page_no - 1]
        self.h = self.page.rect.height
        self.stats = Counter()
        self.sheet = ""

    def xy(self, p) -> tuple[float, float]:
        """PDF point (y down) -> DXF millimetre (y up)."""
        return (p.x * PT_MM, (self.h - p.y) * PT_MM)

    def run(self, out: Path) -> None:
        dxf = ezdxf.new("R2018", setup=True)
        dxf.header["$INSUNITS"] = 4        # millimetres
        dxf.header["$MEASUREMENT"] = 1     # metric
        msp = dxf.modelspace()

        for name, aci, desc in list(COLOUR_LAYERS.values()) + [FALLBACK, TEXT_LAYER]:
            if name not in dxf.layers:
                layer = dxf.layers.add(name, color=aci)
                layer.description = desc

        self._geometry(msp)
        self._text(msp)
        self._sheet(msp, dxf)

        dxf.saveas(out)
        print(f"wrote {out}  ({self.sheet}, 1:1, millimetres)")
        for k, v in self.stats.most_common():
            print(f"  {k:22} {v}")

    # -- geometry ---------------------------------------------------------

    def _geometry(self, msp) -> None:
        for path in self.page.get_drawings():
            layer, _, _ = layer_for(path.get("color") or path.get("fill"))
            attrs = {"layer": layer}
            run: list[tuple[float, float]] = []

            def flush():
                nonlocal run
                if len(run) >= 2:
                    msp.add_lwpolyline(run, dxfattribs=attrs)
                    self.stats["polylines"] += 1
                run = []

            for item in path["items"]:
                kind = item[0]
                if kind == "l":
                    a, b = self.xy(item[1]), self.xy(item[2])
                    if run and _close(run[-1], a):
                        run.append(b)
                    else:
                        flush()
                        run = [a, b]
                elif kind == "c":
                    flush()
                    pts = _bezier([self.xy(item[i]) for i in (1, 2, 3, 4)])
                    msp.add_lwpolyline(pts, dxfattribs=attrs)
                    self.stats["curves"] += 1
                elif kind == "qu":
                    flush()
                    quad = item[1]
                    pts = [self.xy(p) for p in
                           (quad.ul, quad.ur, quad.lr, quad.ll)]
                    msp.add_lwpolyline(pts, close=True, dxfattribs=attrs)
                    self.stats["quads"] += 1
                elif kind == "re":
                    flush()
                    r = item[1]
                    x0, y0 = self.xy(pymupdf.Point(r.x0, r.y1))
                    x1, y1 = self.xy(pymupdf.Point(r.x1, r.y0))
                    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                                       close=True, dxfattribs=attrs)
                    self.stats["rectangles"] += 1
            flush()

    # -- text -------------------------------------------------------------

    def _text(self, msp) -> None:
        blocks = self.page.get_text("dict")["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1.0, 0.0))
                # PDF y grows downward; DXF y grows upward, so the sign of the
                # vertical component flips when we convert the angle.
                angle = _degrees(dx, -dy)
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if not text:
                        continue
                    x, y = self.xy(pymupdf.Point(span["origin"]))
                    msp.add_text(
                        text,
                        height=max(span["size"] * PT_MM, 0.4),
                        rotation=angle,
                        dxfattribs={"layer": TEXT_LAYER[0], "style": "Standard"},
                    ).set_placement((x, y))
                    self.stats["text"] += 1

    # -- sheet ------------------------------------------------------------

    def _sheet(self, msp, dxf) -> None:
        """Sheet outline, and an opening view that covers the whole sheet.

        ezdxf resets $EXTMIN/$EXTMAX to their "unset" sentinels on save and
        re-derives $LIMMIN/$LIMMAX, so setting those here would be a no-op -
        AutoCAD recomputes the extents on its first regen anyway. What does
        survive is the active viewport, so point it at the middle of the sheet.
        Without that, a converted DXF opens on whatever view the template had
        and looks empty until you Zoom Extents.
        """
        w, h = self.page.rect.width * PT_MM, self.h * PT_MM
        dxf.layers.add("PID-SHEET", color=251).description = "Sheet extents"
        msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)],
                           close=True, dxfattribs={"layer": "PID-SHEET"})

        active = dxf.viewports.get("*Active")
        if active:
            view = active[0]
            view.dxf.center = (w / 2.0, h / 2.0)
            view.dxf.height = h * 1.05
        self.sheet = f"{w:.0f} x {h:.0f} mm"


def _close(a, b, tol=1e-6) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _bezier(pts, segments: int = 12):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
    out = []
    for i in range(segments + 1):
        t = i / segments
        u = 1 - t
        out.append((
            u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
            u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
        ))
    return out


def _degrees(dx, dy) -> float:
    import math
    return round(math.degrees(math.atan2(dy, dx)), 3) % 360


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Nandi-TBC--A0.pdf")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("out") / f"{src.stem}.dxf"
    dst.parent.mkdir(parents=True, exist_ok=True)
    Converter(src).run(dst)
