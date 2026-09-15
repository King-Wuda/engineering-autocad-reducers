#!/usr/bin/env python3
"""Run the pipeline over a manually recorded vision reading.

Stands in for :class:`pid_scan.vision.Scanner` using readings taken by eye from
the rendered tiles. Everything downstream - coordinate mapping, overlap
merging, tag decoding, loop derivation, reporting - is the real code.

    python tools/replay_reading.py Nandi-TBC--A0.pdf readings/nandi_tbc_a0.py out/
"""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pid_scan.report import render_html, render_json, render_markdown  # noqa: E402
from pid_scan.scan import ScanConfig, scan_pdf  # noqa: E402
from pid_scan.schema import (Box, Finding, PageAnalysis,  # noqa: E402
                             TileComponent, TileResult)
from pid_scan.vision import Usage  # noqa: E402


class ReplayScanner:
    """Duck-types Scanner, serving recorded readings instead of API calls."""

    def __init__(self, readings, analysis: PageAnalysis, model: str = "manual-reading"):
        self.model = model
        self.concurrency = 1
        self.usage = Usage()
        self.analysis = analysis
        self.by_tile = defaultdict(list)
        for i, entry in enumerate(readings):
            tile, x, y, kind, subtype, tag, label, notes, conf, basis = entry
            self.by_tile[tile].append((i, x, y, kind, subtype, tag, label, notes, conf, basis))

    def scan_page_tiles(self, page, progress=None):
        out = []
        for tile in page.tiles:
            comps = []
            for (i, x, y, kind, subtype, tag, label, notes, conf, basis) in self.by_tile.get(tile.index, []):
                half = 14
                comps.append(TileComponent(
                    local_id=f"c{i}", kind=kind, subtype=subtype, tag=tag,
                    label=label,
                    box=Box(x0=max(0, x - half), y0=max(0, y - half),
                            x1=min(1000, x + half), y1=min(1000, y + half)),
                    actuator="none", fail_position="",
                    notes=(notes + ("" if basis == "read" else
                                    " [repeat of a unit read at full resolution]")).strip(),
                    confidence=conf,
                ))
            out.append((tile, TileResult(components=comps, connections=[], texts=[])))
            if progress:
                progress(len(out), len(page.tiles))
        return out

    def synthesize(self, page, components, connections, source):
        return self.analysis


def load_readings(path: Path):
    spec = importlib.util.spec_from_file_location("reading", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.R


ANALYSIS = PageAnalysis(
    title="Nandi Harvest Frozen Fish Plant - Plantroom P&ID",
    drawing_number="51938-003-1-01",
    revision="G",
    summary=(
        "A two-stage-capable ammonia (R717) pumped-recirculation refrigeration "
        "plantroom for a frozen fish plant, drawn by GEA Refrigeration "
        "Netherlands. Two screw compressor packages (=K1, =K2) discharge to two "
        "sea-water-cooled plate condensers (=C1C1, =C1C2) and a horizontal "
        "liquid receiver (=R1). Liquid is sub-cooled in an economiser (=H1) and "
        "collected in a pump separator (=S1), from which duty/standby ammonia "
        "pumps (=P1) recirculate liquid to five blast-freeze chambers (=A1A1 to "
        "=A1A5) and a tie-in to an existing serpentine freezer (=A3A1). Sea "
        "water for condensing is pumped by a duty/standby set (=P2) from a "
        "client supply at 0.7 bar, 25 DegC."
    ),
    process_description=(
        "Low-pressure ammonia vapour returns from the freezers through a DN125 "
        "wet return header (RR-125-A14.510-002, raised from DN150 at revision E) "
        "into the pump separator =S1, a 1200 x 2500 vertical vessel. Vapour is "
        "drawn off to the two screw compressors, passing the =H1 economiser "
        "where it picks up superheat: suction leaves at about -8 DegC with 10 K "
        "of superheat against an evaporating temperature of roughly -18 DegC. "
        "Each compressor discharges through its own oil separator into the "
        "RD-80/RD-50 discharge lines to the =C1 plate condensers, which reject "
        "heat to sea water on the CS-200/CS-80 circuit. Condensed liquid "
        "collects in the =R1 receiver (800 x 2500 horizontal), then passes the "
        "=H1 sub-cooler where it drops from +35 DegC to -3 DegC before feeding "
        "the =S1 separator through a make-up station sized for 340 kW. The =P1 "
        "pumps recirculate liquid from =S1 to the blast freezer coils; wet "
        "return comes back to =S1, closing the loop. Hot gas (RH-20 lines) is "
        "distributed to each cooler station for defrost."
    ),
    major_streams=[
        "Wet return: =A1Ax coolers -> RR-50 branches -> RR-125-A14.510-002 -> =S1 separator N12",
        "Suction: =S1 -> =H1 economiser (-8 DegC, 10 K superheat) -> =K1 / =K2 compressors",
        "Discharge: =K1 / =K2 -> oil separators -> RD-80-A2505-001 / RD-50-A2505-034 / -035 -> =C1C1 / =C1C2",
        "Condensate: =C1 condensers -> RL-32-A2506-029 / -030 -> =R1 receiver",
        "HP liquid: =R1 -> RL-40-A2506-039 -> =H1 sub-cooler (+35 DegC to -3 DegC) -> make-up station -> =S1",
        "Pumped liquid: =S1 -> =P1 duty/standby pumps -> RP-15/RP-40 -> =A1Ax cooler coils and =A3A1",
        "Hot gas defrost: compressor discharge -> RH-20-A2506-009 to -014 -> each =A2Ax station",
        "Sea water: client supply 0.7 bar 25 DegC -> =P2 duty/standby -> CS-200-A1010-032 -> =C1 condensers and oil coolers",
    ],
    control_narrative=(
        "Compressor capacity is set by a slide valve on each screw machine: a "
        "GIT position transmitter reports slide position and a block of four "
        "solenoid valves (=Q12, =Q13, =Q14, =Q15) drives load and unload. Each "
        "package carries suction and discharge pressure transmitters (PT =K2, "
        "=K4, =K9, =K10) and temperature transmitters (TT =K3, =K5, =K6, =K8), "
        "so protection and capacity control are done by the plant PLC rather "
        "than by local loops - there are no ISA-style controller bubbles on this "
        "sheet. Oil temperature is held by a three-way thermostatic valve (=V2) "
        "marked 65/70/90/135, with sea-water oil coolers. Separator level is the "
        "other live control: Gauge Panel 2 on =S1 carries LZHH (high-high trip, "
        "NC), LSAH (high alarm, NC) and LSAL (low alarm, NO) at HHL 1412 mm, HL "
        "1200 mm and LL 395 mm, and liquid make-up is admitted through solenoid "
        "valves in the duty and standby legs of the make-up station. The =H1 "
        "economiser has the one classical loop on the drawing: a TC temperature "
        "controller driving expansion valve =Q4."
    ),
    safety_narrative=(
        "Every pressure-containing item carries relief protection, and the two "
        "main vessels use paired reliefs on a changeover valve so one can be "
        "removed for test while the other stays in service. The =R1 receiver has "
        "twin DN25/40 reliefs set at 21 bar on changeover =Q5, discharging to a "
        "marked Blow Off. The =S1 separator has twin DN25/40 reliefs set at 14 "
        "bar on changeover =Q2. Cooler stations each carry a DN15/15 14 bar "
        "relief, the condensers DN20/32 at 20 bar, the economiser and receiver "
        "outlets DN15/15 at 20 bar, and the =P1 pumps DN15 at 14 bar. The "
        "compressor packages carry four reliefs each, on the oil separator and "
        "on discharge. A GFG ammonia gas detector (QT =F1) covers the condenser "
        "area, and a purge valve =Q9 is fitted at the highest point for "
        "non-condensables. The =S1 high-high level switch LZHH is the liquid "
        "carry-over trip protecting the compressors."
    ),
    findings=[
        Finding(severity="warning", category="designation",
                message="Cooler =A1A3? is drawn with a question mark in its "
                        "reference designation, so the item is not uniquely "
                        "identified. Rev D added a sixth blast freezer; confirm "
                        "whether this is it and assign a final designation.",
                refs=["=A1A3?"]),
        Finding(severity="warning", category="designation",
                message="Both =P1 ammonia pump motors carry the placeholder "
                        "designation =P1P1??-M?. Two machines share one "
                        "unresolved tag, so neither can be referenced in a "
                        "motor list, cable schedule or the PLC.",
                refs=["=P1P1??-M?"]),
        Finding(severity="warning", category="drawing-data",
                message="Every blast freezer data block reads CHAMBER 1. The "
                        "five chambers =A1A1 to =A1A5 all carry identical "
                        "duty text (20 kg per tray, 10 layers, 120 trays, "
                        "2400 kg), which reads as a copied block rather than "
                        "per-chamber data.",
                refs=["=A1A1", "=A1A2", "=A1A3?", "=A1A4", "=A1A5"]),
        Finding(severity="note", category="title-block",
                message="Status is IN PROGRESS while revisions F and G are both "
                        "described as AS BUILT. Plant Name and Plant ID are "
                        "blank and the order numbers are placeholders "
                        "(##### / ###).",
                refs=["Rev G"]),
        Finding(severity="note", category="scope",
                message="Two GEA/CLIENT battery limit markers sit at the =A3A1 "
                        "serpentine freezer tie-in and one at the sea water "
                        "supply. Everything beyond them is client scope, so the "
                        "existing freezer's internals are not represented here.",
                refs=["=A3A1", "CLIENT / GEA"]),
        Finding(severity="info", category="control",
                message="There are no ISA-style control loops on this sheet. "
                        "Capacity, level and safety functions are wired to "
                        "transmitters and switches (PT/TT/LS/LZHH) and executed "
                        "by the plant PLC, so a loop count of zero is correct "
                        "rather than a gap in the scan.",
                refs=[]),
        Finding(severity="info", category="line-data",
                message="Wet return was increased from DN150 to DN125 at "
                        "revision E - note the direction: the line number "
                        "RR-125-A14.510-002 confirms DN125 is current.",
                refs=["RR-125-A14.510-002"]),
    ],
    utilities=[
        "Sea water (CS) - client supply, 0.7 bar, 25 DegC, condensers and oil coolers",
        "Hot gas defrost (RH) - DN20 branches to each cooler station",
        "Oil (OL / RB) - separator drains, oil cooling and return to each compressor",
        "Ammonia liquid (RL / RP) - receiver, sub-cooler and pumped recirculation",
        "Ammonia suction and wet return (RS / RR)",
        "Refrigerant discharge (RD)",
        "Instrument impulse lines - 6mm SST to each station pressure gauge",
    ],
)


def main() -> int:
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Nandi-TBC--A0.pdf"
    readings = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "readings" / "nandi_tbc_a0.py"
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "out"
    out.mkdir(parents=True, exist_ok=True)

    scanner = ReplayScanner(load_readings(readings), ANALYSIS)
    images = {}
    drawing = scan_pdf(pdf, scanner, ScanConfig.preset("balanced"), images=images)

    (out / f"{pdf.stem}.pid.html").write_text(render_html(drawing, images))
    (out / f"{pdf.stem}.pid.md").write_text(render_markdown(drawing))
    (out / f"{pdf.stem}.pid.json").write_text(render_json(drawing))

    stats = drawing.stats
    print(f"{stats['components']} components, {stats['tagged']} tagged")
    for kind, n in stats["by_kind"].items():
        print(f"  {kind:16} {n}")
    print(f"line numbers: {len(stats['line_numbers'])}  text-layer tags: {stats['text_layer_tags']}")
    print(f"wrote {out}/{pdf.stem}.pid.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
