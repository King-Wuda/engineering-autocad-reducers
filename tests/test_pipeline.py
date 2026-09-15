"""Pipeline tests that need no API access."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fake_scanner import FakeScanner  # noqa: E402

from pid_scan.merge import merge_page  # noqa: E402
from pid_scan.pdfdoc import PidDocument, _tile_starts  # noqa: E402
from pid_scan.report import render_html, render_json, render_markdown  # noqa: E402
from pid_scan.scan import ScanConfig, derive_loops, scan_pdf  # noqa: E402
from pid_scan.schema import (Box, Component, TileComponent,  # noqa: E402
                             TileConnection, TileResult)
from pid_scan.tags import (decode_instrument, find_component_tags,  # noqa: E402
                           find_line_numbers, find_tags_in_words, parse_tag)

FIXTURE = ROOT / "tests" / "fixtures" / "sample_pid.pdf"


REAL = ROOT / "Nandi-TBC--A0.pdf"


@pytest.fixture(scope="module")
def sample_real_pdf():
    """The uploaded drawing, when it is checked out."""
    return REAL if REAL.exists() else None


@pytest.fixture(scope="module")
def sample_pdf() -> Path:
    if not FIXTURE.exists():
        sys.path.insert(0, str(ROOT / "tools"))
        from make_sample_pid import build
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        build(str(FIXTURE))
    return FIXTURE


# --------------------------------------------------------------------------
# ISA tag decoding
# --------------------------------------------------------------------------

@pytest.mark.parametrize("letters,expected", [
    ("FIC", "Flow Indicating Controller"),
    ("PT", "Pressure/Vacuum Transmitter"),
    ("TIT", "Temperature Indicating Transmitter"),
    ("LG", "Level Gauge"),
    ("LSH", "Level Switch High"),
    ("LSHH", "Level Switch High High"),
    ("FSLL", "Flow Switch Low Low"),
    ("PDT", "Pressure/Vacuum Differential Transmitter"),
    ("PSV", "Pressure/Vacuum Safety Valve"),
    ("FQI", "Flow Totalized Indicator"),
])
def test_decode_instrument(letters, expected):
    assert decode_instrument(letters)["function"] == expected


def test_decode_rejects_non_isa():
    assert decode_instrument("P") is None          # too short to be a function
    assert decode_instrument("PJ") is None         # J is not a function letter
    assert decode_instrument("XQ7") is None        # not letters


@pytest.mark.parametrize("tag,kind", [
    ("P-101A", "pump"), ("K-201", "compressor"), ("E-301", "heat_exchanger"),
    ("V-101", "vessel"), ("TK-500", "vessel"), ("T-301", "vessel"),
    ("FIC-1010", "instrument"), ("FV-1010", "valve"), ("PSV-2201", "valve"),
    ("XV-7701", "valve"), ("HV-3", "valve"), ("AG-101", "equipment_other"),
])
def test_tag_kinds(tag, kind):
    assert parse_tag(tag).kind == kind


def test_loop_number_groups_a_loop():
    assert {parse_tag(t).loop for t in ("FT-1010", "FIC-1010", "FV-1010")} == {"F1010"}


def test_tag_suffix_does_not_swallow_following_word():
    tags = {t.normalized for t in find_component_tags("V-200 via FV-1010")}
    assert "V-200" in tags and "V-200VIA" not in tags


def test_line_numbers_parse_mixed_fractions():
    found = find_line_numbers('6"-P-1201-A1A-HC and 1-1/2"-CWS-3004-B2B')
    assert found == ['6"-P-1201-A1A-HC', '1-1/2"-CWS-3004-B2B']


def test_dates_are_not_line_numbers():
    assert find_line_numbers("DATE: 26-09-15") == []


# --------------------------------------------------------------------------
# Tiling
# --------------------------------------------------------------------------

def test_tiles_cover_the_page_with_overlap():
    spans = _tile_starts(3000, 1400, 0.18)
    assert spans[0][0] == 0
    assert spans[-1][1] == 3000
    for a, b in zip(spans, spans[1:]):
        assert b[0] < a[1], "consecutive tiles must overlap"


def test_small_page_is_one_tile():
    assert _tile_starts(900, 1400, 0.18) == [(0.0, 900)]


def test_load_page_reads_text_layer(sample_pdf):
    with PidDocument(sample_pdf) as doc:
        page = doc.load_page(1, dpi=110, tile_px=1200)
        assert page.has_text_layer
        assert len(page.tiles) > 1
        assert all(t.png[:4] == b"\x89PNG" for t in page.tiles)
        assert any(w.text == "V-101" for w in page.words)


def test_tile_coordinates_map_back_to_the_page(sample_pdf):
    with PidDocument(sample_pdf) as doc:
        page = doc.load_page(1, dpi=110, tile_px=1200)
        tile = page.tiles[-1]
        # The tile's own bottom-right corner must land at the page's.
        x, y = tile.to_page_units(1000, 1000, page.width_pt, page.height_pt)
        assert x == pytest.approx(1000, abs=1)
        assert y == pytest.approx(1000, abs=1)


def test_expected_tags_are_all_in_the_text_layer(sample_pdf):
    """The fixture's known answer - guards the tag filters against regressions."""
    with PidDocument(sample_pdf) as doc:
        page = doc.load_page(1, dpi=110, tile_px=1200)
    found = {t.normalized for t in find_tags_in_words(page.words)}
    expected = {
        "V-101", "V-302", "P-101A", "P-101B", "P-301A", "T-301", "E-201",
        "E-301", "C-401", "PSV-101", "PSV-302", "FIC-1010", "FT-1010",
        "FE-1010", "FV-1010", "LT-101", "LIC-101", "LT-301", "LT-302",
        "LIC-302", "LV-302", "TIC-301", "TT-301", "TI-201", "PI-102",
        "PI-301", "PT-401", "PSHH-401",
    }
    assert found == expected


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------

def _tile_comp(local_id, kind, tag, box, conf=0.9):
    return TileComponent(
        local_id=local_id, kind=kind, subtype="", tag=tag, label="",
        box=Box(x0=box[0], y0=box[1], x1=box[2], y1=box[3]),
        actuator="none", fail_position="", notes="", confidence=conf,
    )


class _FakeTile:
    """Minimal stand-in for pdfdoc.Tile with an identity coordinate mapping."""

    def __init__(self, index):
        self.index = index

    def to_page_units(self, x, y, page_w, page_h):
        return x, y


class _FakePage:
    number = 1
    width_pt = 1000.0
    height_pt = 1000.0
    words = []


def test_same_tag_in_two_tiles_becomes_one_component():
    tiles = [
        (_FakeTile(0), TileResult(components=[_tile_comp("c1", "pump", "P-101A", (100, 100, 140, 140))],
                                  connections=[])),
        (_FakeTile(1), TileResult(components=[_tile_comp("c1", "pump", "P-101A", (102, 101, 142, 141))],
                                  connections=[])),
    ]
    merged, _, _ = merge_page(_FakePage(), tiles)
    assert len(merged) == 1
    assert merged[0].tag == "P-101A"
    assert merged[0].detections == 2


def test_distinct_untagged_valves_stay_separate():
    tiles = [(_FakeTile(0), TileResult(components=[
        _tile_comp("c1", "valve", "", (100, 100, 120, 120)),
        _tile_comp("c2", "valve", "", (600, 600, 620, 620)),
    ], connections=[]))]
    merged, _, _ = merge_page(_FakePage(), tiles)
    assert len(merged) == 2


def test_overlapping_untagged_valves_merge():
    tiles = [
        (_FakeTile(0), TileResult(components=[_tile_comp("c1", "valve", "", (100, 100, 130, 130))],
                                  connections=[])),
        (_FakeTile(1), TileResult(components=[_tile_comp("c1", "valve", "", (104, 103, 134, 133))],
                                  connections=[])),
    ]
    merged, _, _ = merge_page(_FakePage(), tiles)
    assert len(merged) == 1
    assert merged[0].detections == 2


def test_bubble_does_not_absorb_the_valve_beneath_it():
    """An instrument and a valve at the same spot are two different things."""
    tiles = [(_FakeTile(0), TileResult(components=[
        _tile_comp("c1", "instrument", "FIC-1010", (100, 100, 130, 130)),
        _tile_comp("c2", "valve", "FV-1010", (102, 102, 132, 132)),
    ], connections=[]))]
    merged, _, _ = merge_page(_FakePage(), tiles)
    assert len(merged) == 2
    assert {c.kind for c in merged} == {"instrument", "valve"}


def test_equipment_tag_overrides_a_mislabelled_symbol():
    """A bubble is never tagged P-101A, so the tag wins."""
    tiles = [(_FakeTile(0), TileResult(
        components=[_tile_comp("c1", "instrument", "P-101A", (100, 100, 130, 130))],
        connections=[]))]
    merged, _, _ = merge_page(_FakePage(), tiles)
    assert merged[0].kind == "pump"


def test_repeated_tag_far_away_is_not_merged():
    """The same tag at opposite corners is a cross-reference, not one item."""
    tiles = [(_FakeTile(0), TileResult(components=[
        _tile_comp("c1", "vessel", "V-101", (50, 50, 90, 90)),
        _tile_comp("c2", "vessel", "V-101", (900, 900, 940, 940)),
    ], connections=[]))]
    merged, _, _ = merge_page(_FakePage(), tiles)
    assert len(merged) == 2


def test_connections_are_remapped_to_merged_ids():
    tiles = [(_FakeTile(0), TileResult(
        components=[_tile_comp("c1", "pump", "P-101A", (100, 100, 140, 140)),
                    _tile_comp("c2", "vessel", "V-101", (400, 100, 460, 160))],
        connections=[TileConnection(from_id="c1", to_id="c2", signal="process",
                                    line_number='6"-P-1102-A1A', edge="")]))]
    merged, connections, _ = merge_page(_FakePage(), tiles)
    ids = {c.id for c in merged}
    assert len(connections) == 1
    assert connections[0].from_id in ids and connections[0].to_id in ids
    assert connections[0].from_tag == "P-101A"
    assert connections[0].to_tag == "V-101"
    assert connections[0].line_number == '6"-P-1102-A1A'


def test_min_confidence_filters_detections():
    tiles = [(_FakeTile(0), TileResult(components=[
        _tile_comp("c1", "valve", "", (100, 100, 120, 120), conf=0.2),
        _tile_comp("c2", "valve", "", (600, 600, 620, 620), conf=0.9),
    ], connections=[]))]
    merged, _, _ = merge_page(_FakePage(), tiles, min_confidence=0.5)
    assert len(merged) == 1


# --------------------------------------------------------------------------
# Loops
# --------------------------------------------------------------------------

def test_derive_loops_groups_by_loop_number():
    comps = [
        Component(id="1", kind="instrument", tag="FT-1010", loop="F1010",
                  isa_function="Flow Transmitter", box=Box(x0=0, y0=0, x1=1, y1=1)),
        Component(id="2", kind="instrument", tag="FIC-1010", loop="F1010",
                  isa_function="Flow Indicating Controller", box=Box(x0=0, y0=0, x1=1, y1=1)),
        Component(id="3", kind="valve", tag="FV-1010", loop="F1010",
                  isa_function="Flow Valve", box=Box(x0=0, y0=0, x1=1, y1=1)),
        Component(id="4", kind="instrument", tag="PI-500", loop="P500",
                  isa_function="Pressure Indicator", box=Box(x0=0, y0=0, x1=1, y1=1)),
    ]
    loops = derive_loops(comps)
    assert len(loops) == 1, "a lone indicator is not a loop"
    assert loops[0].loop_id == "F1010"
    assert loops[0].final_element == "FV-1010"
    assert loops[0].members == ["FIC-1010", "FT-1010", "FV-1010"]


# --------------------------------------------------------------------------
# End to end, offline
# --------------------------------------------------------------------------

def test_end_to_end_offline(sample_pdf, tmp_path):
    scanner = FakeScanner()
    config = ScanConfig.preset("fast")
    images = {}
    drawing = scan_pdf(sample_pdf, scanner, config, images=images)

    assert scanner.tile_calls > 0
    assert len(drawing.pages) == 1
    page = drawing.pages[0]
    assert page.components, "the offline scanner should find tagged components"

    tags = {c.tag for c in page.components}
    for expected in ("V-101", "P-101A", "T-301", "E-201", "C-401", "PSV-101"):
        assert expected in tags, f"{expected} missing from {sorted(tags)}"

    # Tile overlap must not produce duplicates: each real tag exactly once.
    tagged = [c.tag for c in page.components if c.tag]
    # Tile overlap must not produce duplicates. Scope the check to tags the
    # sheet prints exactly once: the fixture's notes also name PSV-101, PSV-302
    # and P-101B in prose, and a tag named in a note is correctly kept separate
    # from the equipment rather than merged across the sheet.
    with PidDocument(sample_pdf) as doc:
        words = [w.text for w in doc.load_page(1, dpi=110, tile_px=1200).words]
    tagged = [c.tag for c in page.components if c.tag]
    printed_once = [t for t in set(tagged) if words.count(t) == 1]
    assert len(printed_once) >= 8, "expected a meaningful set of once-printed tags"
    for tag in printed_once:
        assert tagged.count(tag) == 1, (
            f"{tag} is printed once but appears {tagged.count(tag)} times after merging")

    # Tags confirmed against the PDF text layer are marked as such.
    assert any(c.source == "both" for c in page.components)

    assert images and images[1][:4] == b"\x89PNG"
    assert drawing.stats["components"] == len(page.components)
    assert drawing.stats["line_numbers"]

    html = render_html(drawing, images)
    assert "V-101" in html and "data:image/png;base64," in html
    assert html.count('class="box"') == len(page.components)

    md = render_markdown(drawing)
    assert "# P&ID scan" in md and "P-101A" in md

    js = render_json(drawing)
    assert '"tag"' in js

    (tmp_path / "r.html").write_text(html)
    assert (tmp_path / "r.html").stat().st_size > 10_000


# --------------------------------------------------------------------------
# Non-ISA drawings (IEC 81346 reference designations, metric line numbers)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tag", ["=Q1", "=A2A5", "=P1P1", "=K10", "=V2", "=C1C2"])
def test_reference_designations_survive_verbatim(tag):
    """The killer bug: "=A2A5" must never be rewritten to "A-2"."""
    info = parse_tag(tag)
    assert info.normalized == tag
    assert info.category == "reference_designation"
    assert info.kind == "", "a reference designation must not imply a component type"


@pytest.mark.parametrize("label,function", [
    ("PI", "Pressure/Vacuum Indicator"),
    ("TT", "Temperature Transmitter"),
    ("LSAH", "Level Switch Alarm High"),
    ("PdI", "Pressure/Vacuum Differential Indicator"),
    ("TC", "Temperature Controller"),
])
def test_bare_function_letters_decode(label, function):
    """Drawings that print "PI" next to "=P1" still tell us what it does."""
    info = parse_tag(label)
    assert info.isa_function == function
    assert info.kind == "instrument"


@pytest.mark.parametrize("line", [
    "RR-125-A14.510-002", "RS-40-A1605-003", "OL-40-A2506-006",
    "CS-200-A1010-032", "RB-12-A2505-012", 'OL-1/2"-D25CS-005',
    "OL-28-D25CS-007", "RD-80-A2505-001",
])
def test_metric_service_first_line_numbers(line):
    assert find_line_numbers(line) == [line]


def test_bubble_tags_are_assembled_from_geometry(sample_pdf):
    """Bubbles print the letters and the loop number on separate lines."""
    with PidDocument(sample_pdf) as doc:
        page = doc.load_page(1, dpi=110, tile_px=1200)
    found = {t.normalized for t in find_tags_in_words(page.words)}
    # These exist in the text layer only as "FIC" + "1010" on two lines.
    for tag in ("FIC-1010", "FT-1010", "LT-101", "TIC-301", "PSHH-401"):
        assert tag in found, f"{tag} not assembled from its bubble"
    # Stacked prose must not be mistaken for a bubble.
    assert not any(t.startswith("ACME") for t in found)


def test_real_drawing_reference_designations(sample_real_pdf):
    """The uploaded sheet is tagged per IEC 81346, not ISA."""
    if sample_real_pdf is None:
        pytest.skip("real drawing not present")
    with PidDocument(sample_real_pdf) as doc:
        page = doc.load_page(1, dpi=110, tile_px=1400)
    tags = find_tags_in_words(page.words)
    rds = {t.normalized for t in tags if t.category == "reference_designation"}
    assert len(rds) > 60, f"expected most tags to be designations, got {len(rds)}"
    for expected in ("=Q1", "=A2A5", "=P1P1", "=K10", "=V2", "=C1C2"):
        assert expected in rds
    # Nothing else should be picked up: sizes (DN15), product codes (CPI-40)
    # and prose ("120 TRAYS 2400 KG") are not tags.
    others = {t.normalized for t in tags if t.category != "reference_designation"}
    assert others == set(), f"false positives on the real drawing: {sorted(others)}"


def test_real_drawing_text_layer(sample_real_pdf):
    """Against the actual uploaded A0 sheet, not a synthetic one."""
    if sample_real_pdf is None:
        pytest.skip("real drawing not present")
    with PidDocument(sample_real_pdf) as doc:
        page = doc.load_page(1, dpi=110, tile_px=1400)
    assert page.has_text_layer
    text = page.full_text
    lines = set(find_line_numbers(text))
    for expected in ("RR-125-A14.510-002", "RS-50-A1605-025", "OL-40-A2506-006",
                     "CS-200-A1010-032", "RD-80-A2505-001"):
        assert expected in lines, f"{expected} not extracted"
    assert len(lines) >= 30


def test_cli_scan_reports_missing_file(capsys):
    from pid_scan.cli import main
    assert main(["scan", "/nonexistent/nope.pdf"]) == 2
    assert "not found" in capsys.readouterr().err
