"""Reconcile per-tile results into one page inventory.

Tiles overlap on purpose, so the same valve is commonly reported two or four
times. Merging has to be geometric *and* tag-aware: geometry alone splits a
vessel whose two halves landed in different tiles, and tags alone collapse the
twelve untagged hand valves on a sheet into one.

The result is a component list where each physical item appears exactly once,
carrying how many tiles independently saw it - which turns out to be the most
useful confidence signal in the whole pipeline.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .pdfdoc import PageView, Tile
from .schema import Box, Component, Connection, TileResult
from .tags import TagInfo, parse_tag

#: Two boxes are the same item if they overlap by at least this fraction.
IOU_SAME = 0.30
#: ...or if their centres are this close, in page units (0-1000). A symbol
#: clipped differently by two tiles can have a low IoU but a near-identical
#: centre.
CENTRE_SAME = 12.0
#: A tagged component may be merged across this distance, since a large vessel
#: legitimately spans tiles. Beyond it, a repeated tag is treated as a separate
#: mention (usually a cross-reference note, not the equipment itself).
TAG_MERGE_RADIUS = 220.0


class _Union:
    """Minimal union-find over component indices."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _centre_distance(a: Box, b: Box) -> float:
    return ((a.cx - b.cx) ** 2 + (a.cy - b.cy) ** 2) ** 0.5


def _resolve_kind(vision_kind: str, tag: Optional[TagInfo]) -> str:
    """Decide the component family when the symbol and the tag disagree.

    The symbol is normally authoritative - it is what is actually drawn. Two
    exceptions, both cases where the tag carries information the symbol does
    not: an equipment tag (``P-101A``) is never attached to an instrument
    bubble, and a final-element tag (``FV-``, ``PSV-``, ``XV-``) names the
    valve on the line rather than the bubble above it.
    """
    if tag is None:
        return vision_kind
    if tag.category == "equipment" and vision_kind in ("instrument", "valve", "equipment_other"):
        return tag.kind
    if tag.is_valve and vision_kind == "instrument":
        return "valve"
    return vision_kind


def merge_page(
    page: PageView,
    tile_results: List[Tuple[Tile, TileResult]],
    conventions: Optional[Dict] = None,
    min_confidence: float = 0.0,
) -> Tuple[List[Component], List[Connection], List[str]]:
    """Merge tile results into page-level components, connections and texts."""
    conventions = conventions or {}
    page_w, page_h = page.width_pt, page.height_pt

    # ---- 1. Lift every tile detection into page coordinates --------------
    raw: List[Component] = []
    #: (tile_index, local_id) -> index into ``raw``
    local_index: Dict[Tuple[int, str], int] = {}
    texts: List[str] = []

    for tile, result in tile_results:
        texts.extend(result.texts)
        for tc in result.components:
            if tc.confidence < min_confidence:
                continue
            x0, y0 = tile.to_page_units(tc.box.x0, tc.box.y0, page_w, page_h)
            x1, y1 = tile.to_page_units(tc.box.x1, tc.box.y1, page_w, page_h)
            box = Box(x0=round(x0), y0=round(y0), x1=round(x1), y1=round(y1))

            tag_info = parse_tag(tc.tag, conventions) if tc.tag.strip() else None
            local_index[(tile.index, tc.local_id)] = len(raw)
            raw.append(Component(
                id=f"t{tile.index}_{tc.local_id}",
                kind=_resolve_kind(tc.kind, tag_info),
                subtype=tc.subtype,
                # ``normalized`` returns the verbatim text for anything it
                # cannot safely canonicalise, so a reference designation such
                # as "=A2A5" survives intact.
                tag=tag_info.normalized if tag_info else tc.tag.strip(),
                label=tc.label,
                page=page.number,
                box=box,
                actuator=tc.actuator,
                fail_position=tc.fail_position,
                notes=tc.notes,
                confidence=tc.confidence,
                isa_function=tag_info.isa_function if tag_info else "",
                loop=tag_info.loop if tag_info else "",
            ))

    if not raw:
        return [], [], _dedupe_texts(texts)

    # ---- 2. Group duplicate detections -----------------------------------
    union = _Union(len(raw))
    by_tag: Dict[str, List[int]] = {}
    for i, comp in enumerate(raw):
        if comp.tag:
            by_tag.setdefault(comp.tag, []).append(i)

    # Same tag, and close enough to plausibly be one piece of equipment.
    for indices in by_tag.values():
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                ia, ib = indices[a], indices[b]
                if _centre_distance(raw[ia].box, raw[ib].box) <= TAG_MERGE_RADIUS:
                    union.union(ia, ib)

    # Untagged (or differently tagged) items that are geometrically the same
    # symbol. Restricted to matching families so a bubble sitting on top of a
    # valve does not absorb it.
    for i in range(len(raw)):
        for j in range(i + 1, len(raw)):
            if union.find(i) == union.find(j):
                continue
            ci, cj = raw[i], raw[j]
            if ci.kind != cj.kind:
                continue
            if ci.tag and cj.tag and ci.tag != cj.tag:
                continue
            if ci.box.iou(cj.box) >= IOU_SAME or _centre_distance(ci.box, cj.box) <= CENTRE_SAME:
                union.union(i, j)

    # ---- 3. Collapse each group into one component -----------------------
    groups: Dict[int, List[int]] = {}
    for i in range(len(raw)):
        groups.setdefault(union.find(i), []).append(i)

    text_tokens = {w.text.upper().strip(" .,:;()") for w in page.words}

    merged: List[Component] = []
    #: raw index -> merged component id, so connections can be remapped
    remap: Dict[int, str] = {}

    for order, (root, members) in enumerate(sorted(groups.items()), start=1):
        parts = [raw[i] for i in members]
        best = max(parts, key=lambda c: (bool(c.tag), c.confidence))

        box = parts[0].box
        for p in parts[1:]:
            box = box.union(p.box)

        tag = best.tag
        comp = Component(
            id=f"p{page.number}-c{order:04d}",
            kind=best.kind,
            subtype=_pick(p.subtype for p in parts),
            tag=tag,
            label=_pick(p.label for p in parts),
            page=page.number,
            box=box,
            actuator=_pick((p.actuator for p in parts), skip={"none", "unknown", ""}) or "none",
            fail_position=_pick(p.fail_position for p in parts),
            notes=_join(p.notes for p in parts),
            confidence=max(p.confidence for p in parts),
            detections=len(parts),
            isa_function=best.isa_function,
            loop=best.loop,
        )
        # A tag that also appears in the PDF's own text layer is confirmed by
        # two independent sources; one that does not is vision-only and worth
        # treating with more suspicion.
        if tag:
            confirmed = any(tag.replace("-", "") in t.replace("-", "") for t in text_tokens)
            comp.source = "both" if confirmed else "vision"
        else:
            comp.source = "vision"

        merged.append(comp)
        for i in members:
            remap[i] = comp.id

    # ---- 4. Remap connections onto merged ids ----------------------------
    by_id = {c.id: c for c in merged}
    seen: set = set()
    connections: List[Connection] = []

    for tile, result in tile_results:
        for tc in result.connections:
            fi = local_index.get((tile.index, tc.from_id))
            ti = local_index.get((tile.index, tc.to_id))
            from_id = remap.get(fi, "") if fi is not None else ""
            to_id = remap.get(ti, "") if ti is not None else ""
            if not from_id and not to_id:
                continue
            if from_id and from_id == to_id:
                continue
            key = (from_id, to_id, tc.line_number, tc.signal)
            if key in seen:
                continue
            seen.add(key)
            connections.append(Connection(
                from_id=from_id,
                to_id=to_id,
                from_tag=by_id[from_id].tag if from_id in by_id else "",
                to_tag=by_id[to_id].tag if to_id in by_id else "",
                signal=tc.signal,
                line_number=tc.line_number,
                page=page.number,
            ))

    return merged, connections, _dedupe_texts(texts)


def _pick(values, skip: Optional[set] = None) -> str:
    """First non-empty value, preferring the most specific one."""
    skip = skip or {""}
    candidates = [v for v in values if v and v not in skip and v != "unknown"]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _join(values) -> str:
    seen, out = set(), []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return "; ".join(out)


def _dedupe_texts(texts: List[str]) -> List[str]:
    seen, out = set(), []
    for t in texts:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
