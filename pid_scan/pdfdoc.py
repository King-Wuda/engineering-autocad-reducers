"""PDF loading, tiling and text-layer extraction.

A P&ID is typically a D or E size sheet. Handed to a vision model whole, it is
downsampled until a 3 mm valve symbol is a few pixels across and the tag text
is gone. So we cut the sheet into overlapping tiles sized to land just under
the API's internal image resize threshold, and read each tile at full
resolution.

The other half of the job is the text layer. A P&ID exported from AutoCAD
carries every tag as real text with exact coordinates. Extracting it costs
nothing and removes OCR guesswork from the model's work entirely - it only has
to decide which symbol a given tag belongs to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import pymupdf

#: Claude resizes any image whose long edge exceeds this, so rendering tiles
#: larger than it wastes upload bytes and buys no detail.
MAX_USEFUL_EDGE_PX = 1500


@dataclass
class Word:
    """A word from the PDF text layer, in PDF points."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Tile:
    """One rendered image tile plus the text that falls inside it."""

    index: int
    row: int
    col: int
    #: Tile rectangle in PDF points.
    rect: Tuple[float, float, float, float]
    png: bytes
    width_px: int
    height_px: int
    words: List[Word] = field(default_factory=list)

    def to_page_units(self, x: float, y: float, page_w: float, page_h: float) -> Tuple[float, float]:
        """Map a 0-1000 tile-relative coordinate onto 0-1000 page units."""
        x0, y0, x1, y1 = self.rect
        px = x0 + (x / 1000.0) * (x1 - x0)
        py = y0 + (y / 1000.0) * (y1 - y0)
        return (px / page_w) * 1000.0, (py / page_h) * 1000.0

    def word_hints(self, limit: int = 400) -> List[Dict]:
        """Text-layer words as tile-relative 0-1000 coordinates, for the prompt."""
        x0, y0, x1, y1 = self.rect
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        hints = []
        for word in self.words[:limit]:
            hints.append({
                "t": word.text,
                "x": round((word.cx - x0) / w * 1000),
                "y": round((word.cy - y0) / h * 1000),
            })
        return hints


@dataclass
class PageView:
    number: int
    width_pt: float
    height_pt: float
    has_text_layer: bool
    words: List[Word]
    tiles: List[Tile]
    overview_png: bytes
    overview_size: Tuple[int, int]

    @property
    def full_text(self) -> str:
        return " ".join(w.text for w in self.words)


def _tile_starts(total_px: float, tile_px: float, overlap: float) -> List[Tuple[float, float]]:
    """Return (start, end) pixel spans covering ``total_px`` with overlap.

    Tiles are distributed evenly rather than laid left-to-right with a ragged
    remainder, so no tile is a thin sliver and the overlap stays uniform.
    """
    if total_px <= tile_px:
        return [(0.0, total_px)]

    step = tile_px * (1.0 - overlap)
    count = max(2, math.ceil((total_px - tile_px) / step) + 1)
    if count == 1:
        return [(0.0, total_px)]

    stride = (total_px - tile_px) / (count - 1)
    return [(i * stride, i * stride + tile_px) for i in range(count)]


class PidDocument:
    """A PDF opened for P&ID scanning."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.doc = pymupdf.open(self.path)
        if self.doc.needs_pass:
            raise ValueError(f"{self.path.name} is password protected")

    def __enter__(self) -> "PidDocument":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.doc.close()

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page_words(self, page: pymupdf.Page) -> List[Word]:
        out: List[Word] = []
        for x0, y0, x1, y1, text, *_ in page.get_text("words"):
            text = text.strip()
            if text:
                out.append(Word(text=text, x0=x0, y0=y0, x1=x1, y1=y1))
        return out

    def load_page(
        self,
        number: int,
        dpi: int = 150,
        tile_px: int = 1400,
        overlap: float = 0.18,
        max_tiles: int = 80,
        overview_px: int = 1400,
    ) -> PageView:
        """Render page ``number`` (1-based) into overlapping tiles."""
        page = self.doc[number - 1]
        rect = page.rect
        page_w, page_h = rect.width, rect.height
        words = self.page_words(page)

        tile_px = min(tile_px, MAX_USEFUL_EDGE_PX)
        zoom = dpi / 72.0
        page_px_w, page_px_h = page_w * zoom, page_h * zoom

        cols = _tile_starts(page_px_w, tile_px, overlap)
        rows = _tile_starts(page_px_h, tile_px, overlap)

        # If the grid would blow past max_tiles, back the DPI off rather than
        # silently dropping regions of the drawing - losing resolution
        # everywhere is far better than losing a corner completely.
        while len(cols) * len(rows) > max_tiles and zoom > 0.5:
            zoom *= 0.85
            page_px_w, page_px_h = page_w * zoom, page_h * zoom
            cols = _tile_starts(page_px_w, tile_px, overlap)
            rows = _tile_starts(page_px_h, tile_px, overlap)

        tiles: List[Tile] = []
        index = 0
        for r, (ty0, ty1) in enumerate(rows):
            for c, (tx0, tx1) in enumerate(cols):
                clip = pymupdf.Rect(tx0 / zoom, ty0 / zoom, tx1 / zoom, ty1 / zoom)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
                tile_words = [
                    w for w in words
                    if w.cx >= clip.x0 and w.cx <= clip.x1 and w.cy >= clip.y0 and w.cy <= clip.y1
                ]
                tiles.append(Tile(
                    index=index, row=r, col=c,
                    rect=(clip.x0, clip.y0, clip.x1, clip.y1),
                    png=pix.tobytes("png"),
                    width_px=pix.width, height_px=pix.height,
                    words=tile_words,
                ))
                index += 1

        ov_zoom = min(overview_px / max(page_w, 1e-6), overview_px / max(page_h, 1e-6))
        ov = page.get_pixmap(matrix=pymupdf.Matrix(ov_zoom, ov_zoom), alpha=False)

        return PageView(
            number=number,
            width_pt=page_w,
            height_pt=page_h,
            has_text_layer=bool(words),
            words=words,
            tiles=tiles,
            overview_png=ov.tobytes("png"),
            overview_size=(ov.width, ov.height),
        )

    def iter_pages(self, pages: Optional[List[int]] = None, **kwargs) -> Iterator[PageView]:
        targets = pages or list(range(1, self.page_count + 1))
        for n in targets:
            if 1 <= n <= self.page_count:
                yield self.load_page(n, **kwargs)
