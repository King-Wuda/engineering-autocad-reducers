#!/usr/bin/env python3
"""Build a P&ID-derived schedule workbook (BOM) from a scan result.

A P&ID supports an *enquiry-grade* schedule: what exists, how many, what size,
what set pressure. It does not carry body material, pressure class, end
connections or part numbers - those live in the line class spec and the valve
datasheets. Every sheet therefore states its own basis and completeness.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent

FONT = "Arial"
H_FILL = PatternFill("solid", fgColor="1F3864")
H_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
TITLE = Font(name=FONT, bold=True, size=14)
SUB = Font(name=FONT, italic=True, size=10, color="555555")
BODY = Font(name=FONT, size=10)
BOLD = Font(name=FONT, bold=True, size=10)
WARN = Font(name=FONT, size=10, color="9C2500", bold=True)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

#: Service codes, read off the line numbers. No legend sheet was supplied with
#: the drawing, so these are inferred from context and must be confirmed.
SERVICE = {
    "RR": "Refrigerant wet return",
    "RS": "Refrigerant dry suction",
    "RL": "Refrigerant liquid",
    "RD": "Refrigerant discharge",
    "RH": "Refrigerant hot gas (defrost)",
    "RB": "Refrigerant / oil balance and drain",
    "RP": "Refrigerant pumped liquid",
    "CS": "Cooling / sea water",
    "OL": "Lubricating oil",
}

LINE_RE = re.compile(r'^(?P<svc>[A-Z]{1,4})-(?P<size>\d{1,3}/\d{1,3}"?|\d{1,4}"?)-(?P<spec>[A-Z0-9.]+)-(?P<seq>\d{1,4})$')

KIND_LABEL = {
    "vessel": "Vessel", "pump": "Pump", "compressor": "Compressor",
    "heat_exchanger": "Heat exchanger", "driver": "Driver", "valve": "Valve",
    "instrument": "Instrument", "inline_device": "Inline device",
    "connector": "Connector / battery limit", "equipment_other": "Other",
}


def header(ws, row, cols, widths):
    for i, (c, w) in enumerate(zip(cols, widths), start=1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.fill, cell.font, cell.border = H_FILL, H_FONT, BOX
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 28
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def write(ws, row, values, font=BODY):
    for i, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=i, value=v)
        cell.font, cell.border = font, BOX
        cell.alignment = Alignment(vertical="top", wrap_text=isinstance(v, str) and len(str(v)) > 40)


def banner(ws, text, row=1, span=6, font=None):
    ws.cell(row=row, column=1, value=text).font = font or SUB
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    ws.row_dimensions[row].height = 30
    ws.cell(row=row, column=1).alignment = Alignment(vertical="center", wrap_text=True)


def build(result: Path, out: Path) -> None:
    data = json.loads(result.read_text())
    page = data["pages"][0]
    comps = page["components"]
    analysis = page["analysis"]

    wb = Workbook()

    # ---------------------------------------------------------------- Basis
    ws = wb.active
    ws.title = "Basis"
    ws["A1"] = "Nandi Harvest Frozen Fish Plant - Plantroom P&ID"
    ws["A1"].font = TITLE
    ws["A2"] = "Schedule of equipment, lines and field items derived from the drawing"
    ws["A2"].font = SUB
    for c, w in zip("ABCD", (30, 62, 20, 34)):
        ws.column_dimensions[c].width = w

    rows = [
        ("Drawing", "NANDI HARVEST PLANTROOM P&ID", "", ""),
        ("Project number", "51938-003-1-01", "", ""),
        ("Designer", "GEA Refrigeration Netherlands N.V.", "", ""),
        ("Revision", "G - AS BUILT, 29-07-2026 (T.MASHABA / C.GIDEON)", "", ""),
        ("Sheet status", "IN PROGRESS", "", "Title block says IN PROGRESS while revs F and G say AS BUILT"),
        ("Source file", result.name, "", ""),
        ("", "", "", ""),
        ("SECTION", "CONTENT", "COMPLETENESS", "BASIS"),
    ]
    for i, r in enumerate(rows, start=4):
        write(ws, i, r, BOLD if r[0] == "SECTION" else BODY)

    sections = [
        ("Line schedule", "Every pipe line number printed on the sheet",
         "COMPLETE", "Read from the PDF text layer - exact, not interpreted"),
        ("Equipment", "Compressors, vessels, heat exchangers, pumps, drivers",
         "COMPLETE", "All plant areas read at full resolution"),
        ("Relief devices", "Relief valves with set pressure and size",
         "COMPLETE for areas read", "Read at full resolution; set pressures off the drawing"),
        ("Instruments", "Gauges, transmitters, switches, detectors",
         "SUBSTANTIALLY COMPLETE", "Cooler-station gauges applied from the repeated pattern"),
        ("Valves - process", "Isolation, check, solenoid, control valves",
         "PARTIAL - see note", "Needs the remaining 16 of 30 tiles read individually"),
        ("Bulk / fittings", "Reducers, sleeves, strainers, sight glasses",
         "NOT COMPILED", "Requires a full tile-by-tile count"),
        ("Materials / class", "Body material, pressure class, end connections",
         "NOT DERIVABLE", "Not on a P&ID - lives in the line class spec"),
    ]
    r = 12
    for s in sections:
        write(ws, r, s, WARN if s[2].startswith(("PARTIAL", "NOT")) else BODY)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="WHAT THIS IS NOT").font = BOLD
    r += 1
    note = ("This is an enquiry-grade schedule, not a purchasing bill of materials. A P&ID "
            "records what exists, how many, nominal size and set pressure. It does not record "
            "body material, pressure class, end connection, face-to-face, trim, gasket or bolt "
            "specification, or manufacturer part number. Those come from the line class "
            "specification (codes A1605 / A2506 / A2505 / A1010 / A14.510 / D25CS on this sheet) "
            "and the valve datasheets, neither of which was supplied. Quantities marked PARTIAL "
            "must not be used for procurement.")
    ws.cell(row=r, column=1, value=note).font = BODY
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 3, end_column=4)
    ws.cell(row=r, column=1).alignment = Alignment(vertical="top", wrap_text=True)

    # ------------------------------------------------------------- Summary
    ws = wb.create_sheet("Summary")
    banner(ws, "Counts are formulas over the detail sheets - they update if a sheet is edited.", 1, 4)
    header(ws, 3, ["Category", "Count", "Completeness", "Detail sheet"], [34, 12, 26, 20])
    cats = [
        ("Pipe lines", '=COUNTA(Lines!A2:A400)-1', "Complete", "Lines"),
        ("Major equipment items", '=COUNTA(Equipment!A2:A200)-1', "Complete", "Equipment"),
        ("Drivers (motors)", '=COUNTA(Motors!A2:A200)-1', "Complete", "Motors"),
        ("Relief devices", '=COUNTA(Relief!A2:A200)-1', "Complete for areas read", "Relief"),
        ("Instruments", '=COUNTA(Instruments!A2:A400)-1', "Substantially complete", "Instruments"),
        ("Process valves identified", '=COUNTA(Valves!A2:A400)-1', "PARTIAL", "Valves"),
    ]
    for i, c in enumerate(cats, start=4):
        write(ws, i, list(c))
        ws.cell(row=i, column=2).alignment = Alignment(horizontal="right")
    r = 4 + len(cats) + 1
    ws.cell(row=r, column=1,
            value="The Count column holds live formulas over the detail sheets. Excel "
                  "evaluates them on open; they are stored without cached values, so a "
                  "script reading the file without recalculating will see them as blank.")
    ws.cell(row=r, column=1).font = SUB
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=4)
    ws.cell(row=r, column=1).alignment = Alignment(vertical="top", wrap_text=True)

    # --------------------------------------------------------------- Lines
    ws = wb.create_sheet("Lines")
    banner(ws, "Every line number printed on the drawing, parsed into its fields. "
               "Read from the PDF text layer, so the numbers are exact. Service names are "
               "inferred from context - no legend sheet was supplied - and must be confirmed.",
           1, 7)
    header(ws, 2, ["Line number", "Service code", "Service (inferred)", "Nominal size",
                   "Line class", "Sequence", "Notes"], [26, 13, 32, 14, 13, 11, 40])
    r = 3
    for ln in sorted(page["line_numbers"], key=lambda s: (s.split("-")[0], s)):
        m = LINE_RE.match(ln)
        if m:
            svc, size, spec, seq = m.group("svc"), m.group("size"), m.group("spec"), m.group("seq")
            size_txt = size if '"' in size else f"DN{size}"
            write(ws, r, [ln, svc, SERVICE.get(svc, "UNKNOWN - confirm"), size_txt, spec, seq, ""])
        else:
            write(ws, r, [ln, "", "could not parse", "", "", "", "Check format"])
        r += 1
    ws.cell(row=3, column=3).comment = Comment(
        "Service names inferred from line routing and equipment served. "
        "Confirm against the project legend sheet before use.", "pid-scan")

    # ----------------------------------------------------------- Equipment
    ws = wb.create_sheet("Equipment")
    banner(ws, "Major equipment. Sizes and duties are transcribed from the drawing verbatim.", 1, 6)
    header(ws, 2, ["Designation", "Type", "Detail", "Size / duty from drawing",
                   "Area", "Notes"], [22, 20, 22, 34, 12, 46])
    equip_kinds = ("compressor", "vessel", "heat_exchanger", "pump")
    r = 3
    for c in sorted([c for c in comps if c["kind"] in equip_kinds],
                    key=lambda c: (equip_kinds.index(c["kind"]), c["tag"])):
        area = c["tag"].split()[0] if c["tag"].startswith("=") and " " in c["tag"] else ""
        write(ws, r, [c["tag"], KIND_LABEL.get(c["kind"], c["kind"]),
                      c["subtype"].replace("_", " "), c["label"], area, c["notes"]])
        r += 1

    # -------------------------------------------------------------- Motors
    ws = wb.create_sheet("Motors")
    banner(ws, "Electrical drives. No kW ratings are shown on this sheet - obtain from the "
               "motor list. Fan motors are four per blast-freeze chamber.", 1, 5)
    header(ws, 2, ["Designation", "Type", "Supply", "Drives", "Notes"], [26, 16, 12, 30, 44])
    r = 3
    for c in sorted([c for c in comps if c["kind"] == "driver"], key=lambda c: c["tag"]):
        write(ws, r, [c["tag"], c["subtype"].replace("_", " "), c["label"], "", c["notes"]])
        r += 1

    # -------------------------------------------------------------- Relief
    ws = wb.create_sheet("Relief")
    banner(ws, "Pressure relief devices - the safety-critical section. Set pressures and sizes "
               "are as printed. Paired devices sit on a changeover valve so one can be removed "
               "for test while the other stays in service.", 1, 5)
    header(ws, 2, ["Designation", "Size (DN in / out)", "Set pressure", "Protects", "Notes"],
           [20, 20, 16, 34, 48])
    r = 3
    for c in sorted([c for c in comps if c["subtype"] == "relief"], key=lambda c: c["notes"]):
        label = c["label"]
        size = set_p = ""
        if label:
            parts = label.split()
            size = parts[0] if parts else ""
            set_p = " ".join(parts[1:]) if len(parts) > 1 else ""
        write(ws, r, [c["tag"], size, set_p, "", c["notes"]])
        r += 1

    # --------------------------------------------------------- Instruments
    ws = wb.create_sheet("Instruments")
    banner(ws, "Field instruments. Function is decoded from the ISA-5.1 letters printed in each "
               "bubble; the designation beside it is IEC 81346 and is scoped to its parent block, "
               "so the same text repeats across stations.", 1, 5)
    header(ws, 2, ["Tag as printed", "Function (ISA-5.1)", "Type", "Signal / state", "Notes"],
           [22, 40, 24, 16, 46])
    r = 3
    for c in sorted([c for c in comps if c["kind"] == "instrument"],
                    key=lambda c: (c["subtype"], c["tag"])):
        write(ws, r, [c["tag"], c["isa_function"], c["subtype"].replace("_", " "),
                      c["label"], c["notes"]])
        r += 1

    # -------------------------------------------------------------- Valves
    ws = wb.create_sheet("Valves")
    banner(ws, "PARTIAL - DO NOT USE FOR PROCUREMENT. Only valves in the 14 of 30 tiles read at "
               "full resolution are listed. The drawing carries many more hand valves, and "
               "designations run to =Q27 in some blocks. A complete count needs every tile read "
               "individually.", 1, 5, font=WARN)
    header(ws, 2, ["Designation", "Type", "Actuation", "Location", "Notes"],
           [20, 18, 16, 30, 50])
    r = 3
    for c in sorted([c for c in comps if c["kind"] == "valve" and c["subtype"] != "relief"],
                    key=lambda c: (c["subtype"], c["tag"])):
        write(ws, r, [c["tag"], c["subtype"].replace("_", " "), c["actuator"], "", c["notes"]])
        r += 1

    # ------------------------------------------------------------ Findings
    ws = wb.create_sheet("Findings")
    banner(ws, "Points a reviewer should resolve before this schedule is used.", 1, 4)
    header(ws, 2, ["Severity", "Category", "Finding", "References"], [12, 18, 78, 26])
    r = 3
    for f in analysis.get("findings", []):
        write(ws, r, [f["severity"].upper(), f["category"], f["message"], ", ".join(f["refs"])],
              WARN if f["severity"] == "warning" else BODY)
        r += 1
    extra = [
        ("WARNING", "line-size", "Both DN125 dry suction lines (RS-125-A1605-026 to =K1 and "
         "RS-125-A1605-027 to =K2) branch off a horizontal line labelled RS-40-A1605-003, fed "
         "from the =S1 DN150 outlet N1 through a reducer marked 150/40. A DN125 branch cannot "
         "come off a DN40 header - the reducer callout, the line number or the connection is "
         "wrong.", "RS-40-A1605-003, RS-125-A1605-026/027"),
        ("WARNING", "line-number", "RS-40-A1605-003 is printed on two different lines - one "
         "upper line and one off the =S1 separator outlet. A line number must be unique.",
         "RS-40-A1605-003"),
        ("NOTE", "legend", "No legend or symbol sheet was supplied. CPI-40 / CPI-50 / CPI-60 "
         "appear throughout as hatched rectangles at block boundaries and are recorded as pipe "
         "penetrations or supports, but this is inferred, not read.", "CPI-40, CPI-50, CPI-60"),
    ]
    for f in extra:
        write(ws, r, list(f), WARN if f[0] == "WARNING" else BODY)
        r += 1

    wb.save(out)
    print(f"wrote {out}")
    for name in wb.sheetnames:
        print(f"  {name:14} {wb[name].max_row - 2} rows")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "Nandi-TBC--A0.pid.json"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out" / "Nandi-TBC--A0-schedules.xlsx"
    build(src, dst)
