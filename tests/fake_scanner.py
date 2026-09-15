"""An offline stand-in for :class:`pid_scan.vision.Scanner`.

It fabricates tile results from the PDF's own text layer instead of calling the
API: every tag-shaped word becomes a component with a box around it. That is
not symbol recognition, but it drives every other stage of the pipeline -
tile-to-page coordinate mapping, overlap de-duplication, tag reconciliation,
loop derivation and report rendering - so those can be tested without
credentials or spend.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from pid_scan.pdfdoc import PageView, Tile
from pid_scan.schema import (Component, Connection, ControlLoop, Finding,
                             PageAnalysis, TileComponent, TileConnection,
                             TileResult)
from pid_scan.tags import find_component_tags, parse_tag
from pid_scan.vision import Usage

_SUBTYPE = {
    "pump": "centrifugal", "vessel": "horizontal_drum",
    "heat_exchanger": "shell_and_tube", "compressor": "centrifugal",
    "valve": "gate", "instrument": "", "inline_device": "filter",
}


class FakeScanner:
    """Duck-types the parts of ``Scanner`` that :func:`scan_pdf` uses."""

    def __init__(self, model: str = "fake-model", concurrency: int = 1):
        self.model = model
        self.concurrency = concurrency
        self.usage = Usage()
        self.tile_calls = 0

    def scan_page_tiles(self, page: PageView, progress=None) -> List[Tuple[Tile, TileResult]]:
        out = []
        for tile in page.tiles:
            out.append((tile, self._fake_tile(tile)))
            self.tile_calls += 1
            if progress:
                progress(len(out), len(page.tiles))
        return out

    def _fake_tile(self, tile: Tile) -> TileResult:
        components: List[TileComponent] = []
        x0, y0, x1, y1 = tile.rect
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)

        # Only words that survive the same filtering the real pipeline uses:
        # line-number fragments and drawing references are not components.
        allowed = {t.normalized for t in
                   find_component_tags(" ".join(w.text for w in tile.words))}

        for i, word in enumerate(tile.words):
            info = parse_tag(word.text)
            if not info or info.category == "unknown" or not info.kind:
                continue
            if info.normalized not in allowed:
                continue
            # Box the word, in tile-relative 0-1000 units.
            bx0 = round((word.x0 - x0) / w * 1000)
            by0 = round((word.y0 - y0) / h * 1000)
            bx1 = round((word.x1 - x0) / w * 1000)
            by1 = round((word.y1 - y0) / h * 1000)
            components.append(TileComponent(
                local_id=f"c{i}",
                kind=info.kind,
                subtype=_SUBTYPE.get(info.kind, ""),
                tag=info.raw,
                label="",
                box={"x0": bx0, "y0": by0, "x1": bx1, "y1": by1},
                actuator="diaphragm" if info.kind == "valve" and info.prefix.endswith("V") else "none",
                fail_position="",
                notes="",
                confidence=0.9,
            ))

        connections: List[TileConnection] = []
        for a, b in zip(components, components[1:]):
            connections.append(TileConnection(
                from_id=a.local_id, to_id=b.local_id,
                signal="process", line_number="", edge="",
            ))
        return TileResult(components=components, connections=connections, texts=[])

    def synthesize(self, page: PageView, components: List[Component],
                   connections: List[Connection], source: str) -> PageAnalysis:
        return PageAnalysis(
            title="Unit 1300 Fractionation",
            drawing_number="D-1301",
            revision="3",
            summary=f"Offline synthesis stub over {len(components)} components.",
            process_description="Feed is surged, pumped, preheated and fractionated.",
            major_streams=["Feed -> V-101 -> P-101A/B -> E-201 -> T-301"],
            control_narrative="Flow, level and temperature loops.",
            safety_narrative="Two relief valves route to flare.",
            utilities=["Cooling water"],
            loops=[ControlLoop(loop_id="F1010", description="Feed flow control")],
            findings=[Finding(severity="note", category="offline",
                              message="Generated without the vision pass.")],
        )
