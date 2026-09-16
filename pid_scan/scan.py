"""Top-level scan pipeline: PDF in, :class:`Drawing` out."""

from __future__ import annotations

import datetime as _dt
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .merge import merge_page
from .pdfdoc import PidDocument
from .schema import Component, ControlLoop, Drawing, Page
from .tags import find_line_numbers, find_tags_in_words, parse_tag
from .vision import Scanner

log = logging.getLogger("pid_scan.scan")

ProgressFn = Callable[[str], None]


@dataclass
class ScanConfig:
    """Everything that changes how a sheet is read."""

    dpi: int = 150
    tile_px: int = 1400
    overlap: float = 0.18
    max_tiles: int = 80
    concurrency: int = 4
    min_confidence: float = 0.0
    synthesize: bool = True
    pages: Optional[List[int]] = None
    conventions: Dict = field(default_factory=dict)

    #: Presets, because "how carefully should I read this" is the only knob
    #: most users actually want.
    @classmethod
    def preset(cls, name: str, **overrides) -> "ScanConfig":
        presets = {
            # One pass at modest resolution. Good for a quick inventory or a
            # simple utility sheet.
            "fast":     dict(dpi=110, tile_px=1200, overlap=0.12, max_tiles=24, concurrency=6),
            # The default. Reads a D/E size sheet at a resolution where 3 mm
            # symbols and 2 mm tag text are both legible.
            "balanced": dict(dpi=150, tile_px=1400, overlap=0.18, max_tiles=80, concurrency=4),
            # Dense sheets, small text, or when a first pass missed things.
            "thorough": dict(dpi=220, tile_px=1500, overlap=0.28, max_tiles=200, concurrency=4),
        }
        if name not in presets:
            raise ValueError(f"unknown preset {name!r}; choose from {sorted(presets)}")
        return cls(**{**presets[name], **overrides})


def derive_loops(components: List[Component]) -> List[ControlLoop]:
    """Group instruments and final elements into control loops by loop number.

    Deterministic: ``FT-1010``, ``FIC-1010`` and ``FV-1010`` belong to loop
    ``F1010`` because ISA says so, not because a model inferred it.
    """
    buckets: Dict[str, List[Component]] = defaultdict(list)
    for c in components:
        if c.loop and c.kind in ("instrument", "valve") and c.tag:
            buckets[c.loop].append(c)

    loops: List[ControlLoop] = []
    for loop_id, members in sorted(buckets.items()):
        if len(members) < 2:
            continue  # a lone indicator is not a loop
        tags = sorted({m.tag for m in members})
        final = next((m.tag for m in members if m.kind == "valve"), "")
        variable = next((m.isa_function.split()[0] for m in members if m.isa_function), "")
        loops.append(ControlLoop(
            loop_id=loop_id,
            measured_variable=variable,
            members=tags,
            final_element=final,
        ))
    return loops


def _merge_loops(derived: List[ControlLoop], modelled: List[ControlLoop]) -> List[ControlLoop]:
    """Keep deterministic membership, take descriptions from the model."""
    described = {l.loop_id: l for l in modelled}
    out = []
    for loop in derived:
        match = described.get(loop.loop_id)
        if match and match.description:
            loop.description = match.description
        out.append(loop)
    known = {l.loop_id for l in out}
    out.extend(l for l in modelled if l.loop_id not in known)
    return out


def scan_pdf(
    path: str | Path,
    scanner: Scanner,
    config: Optional[ScanConfig] = None,
    progress: Optional[ProgressFn] = None,
    images: Optional[Dict[int, bytes]] = None,
) -> Drawing:
    """Scan every requested page of ``path`` and return the merged result.

    Pass a dict as ``images`` to also receive each page's overview PNG, keyed by
    page number - the HTML report needs them to draw the detection overlay.
    """
    config = config or ScanConfig()
    path = Path(path)
    say = progress or (lambda msg: None)

    drawing = Drawing(
        source=path.name,
        model=scanner.model,
        scanned_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    )

    with PidDocument(path) as doc:
        targets = config.pages or list(range(1, doc.page_count + 1))
        targets = [n for n in targets if 1 <= n <= doc.page_count]
        say(f"{path.name}: {doc.page_count} page(s), scanning {len(targets)}")

        for number in targets:
            view = doc.load_page(
                number,
                dpi=config.dpi,
                tile_px=config.tile_px,
                overlap=config.overlap,
                max_tiles=config.max_tiles,
            )
            if images is not None:
                images[number] = view.overview_png
            layer = "text layer present" if view.has_text_layer else \
                    "NO text layer (scanned image - tags read by vision only)"
            say(f"page {number}: {len(view.tiles)} tiles, {layer}")

            def tile_progress(done: int, total: int, _n=number) -> None:
                say(f"page {_n}: tile {done}/{total}")

            tile_results = scanner.scan_page_tiles(view, progress=tile_progress)
            components, connections, texts = merge_page(
                view, tile_results,
                conventions=config.conventions,
                min_confidence=config.min_confidence,
            )
            say(f"page {number}: {len(components)} components, {len(connections)} connections")

            # Line numbers come from the text layer first - that is exact -
            # topped up with anything the vision pass read off the image, which
            # matters on sheets with no text layer at all.
            line_numbers = find_line_numbers(
                view.full_text + " " + " ".join(texts) + " "
                + " ".join(c.label for c in components)
            )

            text_tags = sorted({
                t.normalized
                for t in find_tags_in_words(view.words, config.conventions)
            })

            page = Page(
                number=number,
                width_pt=view.width_pt,
                height_pt=view.height_pt,
                has_text_layer=view.has_text_layer,
                tiles=len(view.tiles),
                components=components,
                connections=connections,
                texts=texts,
                line_numbers=line_numbers,
                text_tags=text_tags,
            )

            if config.synthesize:
                say(f"page {number}: writing process narrative")
                page.analysis = scanner.synthesize(view, components, connections, path.name)

            page.analysis.loops = _merge_loops(derive_loops(components), page.analysis.loops)
            drawing.pages.append(page)

    drawing.stats = summarize(drawing)
    drawing.stats["usage"] = scanner.usage.as_dict(scanner.model)
    return drawing


def summarize(drawing: Drawing) -> dict:
    """Counts an engineer would want at the top of the report."""
    comps = drawing.all_components()
    kinds = Counter(c.kind for c in comps)
    valves = Counter(c.subtype or "unknown" for c in comps if c.kind == "valve")

    tagged = [c for c in comps if c.tag]
    line_numbers = sorted({ln for p in drawing.pages for ln in p.line_numbers})

    return {
        "pages": len(drawing.pages),
        "components": len(comps),
        "tagged": len(tagged),
        "untagged": len(comps) - len(tagged),
        "by_kind": dict(kinds.most_common()),
        "valves_by_type": dict(valves.most_common()),
        "control_loops": sum(len(p.analysis.loops) for p in drawing.pages),
        "connections": sum(len(p.connections) for p in drawing.pages),
        "line_numbers": line_numbers,
        "text_layer_tags": sum(len(p.text_tags) for p in drawing.pages),
        "low_confidence": sum(1 for c in comps if c.confidence < 0.5),
        "single_detection": sum(1 for c in comps if c.detections == 1),
    }
