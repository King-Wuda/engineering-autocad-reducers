"""ISA-5.1 tag parsing.

Reading a P&ID correctly depends on reading its tags correctly, and tags are
one thing we do *not* need a model for: they follow a published standard
(ISA-5.1) plus a per-plant convention. Decoding them deterministically here
means the model's job is symbol recognition and topology, not OCR-plus-guessing
what ``FIC`` stands for.

Everything is overridable: ``load_conventions()` merges a site-specific JSON
file over these defaults, because no two owner-operators tag identically.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# --------------------------------------------------------------------------
# ISA-5.1 letter tables
# --------------------------------------------------------------------------

#: First letter -> measured or initiating variable.
ISA_FIRST: Dict[str, str] = {
    "A": "Analysis", "B": "Burner/Combustion", "C": "Conductivity",
    "D": "Density", "E": "Voltage", "F": "Flow", "G": "Gauging/Position",
    "H": "Hand", "I": "Current", "J": "Power", "K": "Time/Schedule",
    "L": "Level", "M": "Moisture/Humidity", "N": "User Defined",
    "O": "User Defined", "P": "Pressure/Vacuum", "Q": "Quantity",
    "R": "Radiation", "S": "Speed/Frequency", "T": "Temperature",
    "U": "Multivariable", "V": "Vibration/Mechanical Analysis",
    "W": "Weight/Force", "X": "Unclassified", "Y": "Event/State/Presence",
    "Z": "Position/Dimension",
}

#: Modifier letters that qualify the first letter.
ISA_MODIFIER: Dict[str, str] = {
    "D": "Differential", "F": "Ratio", "J": "Scan",
    "K": "Rate of Change", "M": "Momentary", "Q": "Totalized",
    "S": "Safety", "X": "X Axis", "Y": "Y Axis", "Z": "Z Axis",
}

#: Succeeding letters -> readout or output function.
ISA_SUCCEEDING: Dict[str, str] = {
    "A": "Alarm", "B": "User Defined", "C": "Control",
    "E": "Sensor/Primary Element", "G": "Glass/Gauge/Sight",
    "H": "High", "I": "Indicate", "K": "Control Station", "L": "Low",
    "M": "Middle/Intermediate", "N": "User Defined",
    "O": "Orifice/Restriction", "P": "Test Point", "Q": "Totalize",
    "R": "Record", "S": "Switch", "T": "Transmit", "U": "Multifunction",
    "V": "Valve/Damper/Louver", "W": "Well/Probe", "X": "Unclassified",
    "Y": "Relay/Compute/Convert", "Z": "Actuator/Final Control Element",
}

#: Equipment tag prefixes. These win over an ISA reading, because e.g. "TK"
#: parses as a valid instrument string (Temperature + Control Station) but
#: universally means "tank".
EQUIPMENT_PREFIXES: Dict[str, Dict[str, str]] = {
    "P":   {"kind": "pump", "desc": "Pump"},
    "PU":  {"kind": "pump", "desc": "Pump"},
    "GP":  {"kind": "pump", "desc": "Gear Pump"},
    "C":   {"kind": "compressor", "desc": "Compressor"},
    "K":   {"kind": "compressor", "desc": "Compressor"},
    "KO":  {"kind": "vessel", "desc": "Knockout Drum"},
    "B":   {"kind": "compressor", "desc": "Blower"},
    "BL":  {"kind": "compressor", "desc": "Blower"},
    "FN":  {"kind": "compressor", "desc": "Fan"},
    "EJ":  {"kind": "compressor", "desc": "Ejector"},
    "E":   {"kind": "heat_exchanger", "desc": "Heat Exchanger"},
    "HX":  {"kind": "heat_exchanger", "desc": "Heat Exchanger"},
    "AC":  {"kind": "heat_exchanger", "desc": "Air Cooler"},
    "CD":  {"kind": "heat_exchanger", "desc": "Condenser"},
    "RB":  {"kind": "heat_exchanger", "desc": "Reboiler"},
    "H":   {"kind": "heat_exchanger", "desc": "Fired Heater"},
    "F":   {"kind": "heat_exchanger", "desc": "Furnace"},
    "V":   {"kind": "vessel", "desc": "Vessel"},
    "D":   {"kind": "vessel", "desc": "Drum"},
    "DR":  {"kind": "vessel", "desc": "Drum"},
    "T":   {"kind": "vessel", "desc": "Tower/Tank"},
    "TK":  {"kind": "vessel", "desc": "Tank"},
    "TW":  {"kind": "vessel", "desc": "Tower"},
    "CL":  {"kind": "vessel", "desc": "Column"},
    "R":   {"kind": "vessel", "desc": "Reactor"},
    "RX":  {"kind": "vessel", "desc": "Reactor"},
    "SEP": {"kind": "vessel", "desc": "Separator"},
    "ACC": {"kind": "vessel", "desc": "Accumulator"},
    "FL":  {"kind": "inline_device", "desc": "Filter"},
    "FLT": {"kind": "inline_device", "desc": "Filter"},
    "ST":  {"kind": "inline_device", "desc": "Strainer"},
    "SIL": {"kind": "inline_device", "desc": "Silencer"},
    "M":   {"kind": "driver", "desc": "Motor"},
    "MTR": {"kind": "driver", "desc": "Motor"},
    "TB":  {"kind": "driver", "desc": "Turbine"},
    "AG":  {"kind": "equipment_other", "desc": "Agitator"},
    "MX":  {"kind": "equipment_other", "desc": "Mixer"},
    "CV":  {"kind": "equipment_other", "desc": "Conveyor"},
    "CT":  {"kind": "equipment_other", "desc": "Cooling Tower"},
}

#: Instrument prefixes that denote a physical valve rather than a bubble.
VALVE_INSTRUMENT_PREFIXES = {"PSV", "PRV", "TSV", "RV", "RD", "PVSV", "BDV", "SDV", "XV", "FV", "LV", "PV", "TV", "HV"}

TAG_RE = re.compile(
    r"\b(?P<prefix>[A-Z]{1,5})[\-\s]?(?P<number>\d{1,6})(?:-?(?P<suffix>[A-Z]{1,2})\b)?"
)

#: Line numbers: size - service - sequence - spec [- insulation], in any of the
#: orders plants actually use. Deliberately permissive; validated by the
#: presence of at least three dash-separated groups and a size-looking token.
LINE_NUMBER_RE = re.compile(
    r"""(?P<line>
        # Metric, service-first (ISO / European practice, and what AutoCAD
        # Plant 3D emits by default): RR-125-A14.510-002, OL-1/2"-D25CS-005
        \b[A-Z]{1,4}
        -(?:\d{1,3}\s*/\s*\d{1,3}\s*["']?|\d{1,4}\s*["']?)
        -[A-Z0-9][A-Z0-9.]{1,11}
        -\d{1,4}\b
        |
        # Imperial, size-first (common US practice): 6"-P-1201-A1A-HC
        (?:\d{1,2}\s*-\s*\d{1,2}\s*/\s*\d{1,2}              # 1-1/2
           |\d{1,2}\s*/\s*\d{1,2}                              # 1/2
           |\d{1,2})                                           # 6
        \s*["']?\s*-                                           # closing inch mark
        (?![0-9]+[\-])[A-Z0-9]{1,6}[\-]                      # service code (not all digits)
        [A-Z0-9]{2,8}                                        # sequence
        (?:[\-][A-Z0-9]{1,8}){0,3}                           # spec / insulation
    )""",
    re.VERBOSE,
)

#: IEC 81346 / RDS reference designations, as used by GEA, Siemens and most
#: European OEM drawings: =Q1, =A2A5, =P1P1, =K10. These identify an item
#: within a plant breakdown structure and carry no symbol meaning, so unlike an
#: ISA tag they must never be used to infer what a component *is*.
RDS_RE = re.compile(r"^[=+-]{1,2}[A-Z]{1,3}\d{1,3}(?:[A-Z]{1,3}\d{0,3})*\??$")

#: Tag pattern for scanning prose. Unlike TAG_RE it allows no space between
#: the letters and the number.
TAG_RE_STRICT = re.compile(
    r"\b(?P<prefix>[A-Z]{1,5})-?(?P<number>\d{1,6})(?:-?(?P<suffix>[A-Z]{1,2})\b)?"
)

#: A string that is entirely one plain tag, and so is safe to normalise.
WHOLE_TAG_RE = re.compile(r"^[A-Z]{1,5}[\-\s]?\d{1,6}(?:[\-\s]?[A-Z]{1,2})?$")

SIZE_RE = re.compile(r"\b(\d{1,2}(?:\s*[-/]\s*\d{1,2})?)\s*[\"']")


@dataclass
class TagInfo:
    raw: str
    prefix: str = ""
    number: str = ""
    #: The text exactly as it appeared. Always preferred for display - a tag we
    #: could not fully parse must never be rewritten into something that only
    #: looks like a tag we understand.
    verbatim: str = ""
    suffix: str = ""
    category: str = "unknown"      # "instrument" | "equipment" | "unknown"
    kind: str = ""                 # ComponentKind guess
    isa_function: str = ""         # decoded human-readable function
    measured_variable: str = ""
    loop: str = ""                 # number+suffix, shared across a loop
    is_valve: bool = False

    @property
    def normalized(self) -> str:
        """Canonical form for matching, or the verbatim text when unsafe.

        Normalising ``P 101A`` to ``P-101A`` helps de-duplication. Normalising
        ``=A2A5`` to ``A-2`` destroys it, so anything that is not wholly a
        plain tag is returned untouched.
        """
        if self.category == "reference_designation" or not self.number:
            return self.verbatim or self.raw
        if not WHOLE_TAG_RE.match((self.verbatim or self.raw).upper().strip()):
            return self.verbatim or self.raw
        return f"{self.prefix}-{self.number}{self.suffix}"


#: Noun form of a function letter when it is the head of the tag.
ISA_NOUN: Dict[str, str] = {
    "A": "Alarm", "B": "User Defined Device", "C": "Controller",
    "E": "Primary Element", "G": "Gauge", "I": "Indicator",
    "K": "Control Station", "N": "User Defined Device",
    "O": "Restriction Orifice", "P": "Test Point", "Q": "Totalizer",
    "R": "Recorder", "S": "Switch", "T": "Transmitter",
    "U": "Multifunction Device", "V": "Valve", "W": "Well",
    "X": "Unclassified Device", "Y": "Relay/Converter", "Z": "Actuator",
    "H": "High Device", "L": "Low Device", "M": "Middle Device",
}

#: Adjective form of a function letter when another function letter follows it.
ISA_ADJ: Dict[str, str] = {
    "I": "Indicating", "R": "Recording", "C": "Controlling",
    "S": "Switch", "T": "Transmitting", "Q": "Totalizing",
    "A": "Alarm", "G": "Gauge", "K": "Control Station",
    "E": "Sensing", "Y": "Computing", "V": "Valve", "W": "Well",
    "Z": "Actuating", "U": "Multifunction", "O": "Restriction",
    "P": "Test", "B": "User Defined", "N": "User Defined",
    "X": "Unclassified",
}

#: Trailing letters that qualify a range rather than name a device.
ISA_RANGE_SUFFIX: Dict[str, str] = {"H": "High", "L": "Low", "M": "Middle"}


def decode_instrument(letters: str) -> Optional[Dict[str, str]]:
    """Decode an ISA letter string into its standard English name.

    ``FIC``  -> Flow Indicating Controller
    ``PDSH`` -> Pressure Differential Switch High
    ``LSHH`` -> Level Switch High High
    ``LG``   -> Level Gauge

    Returns ``None`` when the string is not a valid ISA tag, which is how
    callers tell an instrument apart from an equipment tag.
    """
    letters = letters.upper()
    if len(letters) < 2:
        return None

    first = letters[0]
    if first not in ISA_FIRST:
        return None

    rest = letters[1:]
    modifier = ""
    # A second letter may modify the variable (PD = pressure differential),
    # but only when at least one real function letter follows it. H and L are
    # excluded because they almost always mean High/Low on the readout side.
    if (
        len(rest) >= 2
        and rest[0] in ISA_MODIFIER
        and rest[0] not in ("H", "L")
        and (rest[0] not in ("S", "Z") or rest[1] in ("V", "Z", "E"))
    ):
        modifier = ISA_MODIFIER[rest[0]]
        rest = rest[1:]

    if not rest or any(ch not in ISA_SUCCEEDING for ch in rest):
        return None

    # Peel trailing range qualifiers: LSHH -> functions "S", range "High High".
    range_words: List[str] = []
    while len(rest) > 1 and rest[-1] in ISA_RANGE_SUFFIX:
        range_words.insert(0, ISA_RANGE_SUFFIX[rest[-1]])
        rest = rest[:-1]

    variable = ISA_FIRST[first]
    if modifier:
        variable = f"{variable} {modifier}"

    head, tail = rest[:-1], rest[-1]
    words = [ISA_ADJ.get(ch, ISA_SUCCEEDING[ch]) for ch in head]
    words.append(ISA_NOUN.get(tail, ISA_SUCCEEDING[tail]))

    name = " ".join([variable] + words + range_words)
    return {
        "measured_variable": variable,
        "function": name,
        "functions": ",".join(rest),
        "range": " ".join(range_words),
    }


def parse_tag(text: str, conventions: Optional[Dict] = None) -> Optional[TagInfo]:
    """Parse a single tag string like ``P-101A`` or ``FIC 1010``."""
    conventions = conventions or {}
    equip = {**EQUIPMENT_PREFIXES, **conventions.get("equipment_prefixes", {})}

    verbatim = text.strip()
    upper = verbatim.upper()
    stop = STOP_PREFIXES | {w.upper() for w in conventions.get("stop_prefixes", [])}

    # A reference designation is an identifier, not a description. Record it
    # and let the symbol decide what the component is.
    if RDS_RE.match(upper):
        return TagInfo(raw=verbatim, verbatim=verbatim, prefix="", number="",
                       category="reference_designation")

    # Some drawings print the ISA function letters separately from the item
    # identifier - a bubble reading "PI" with "=P1" beside it. The letters
    # alone still tell us exactly what the instrument does.
    if upper.isalpha() and 2 <= len(upper) <= 5:
        if upper in stop:
            return None
        decoded = decode_instrument(upper)
        if decoded:
            return TagInfo(
                raw=verbatim, verbatim=verbatim, prefix=upper, number="",
                category="instrument",
                measured_variable=decoded["measured_variable"],
                isa_function=decoded["function"],
                is_valve=upper in VALVE_INSTRUMENT_PREFIXES or upper[-1] in ("V", "Z"),
                kind="valve" if (upper in VALVE_INSTRUMENT_PREFIXES or upper[-1] in ("V", "Z"))
                     else "instrument",
            )

    m = TAG_RE.search(upper)
    if not m:
        return None

    prefix, number = m.group("prefix"), m.group("number")
    if prefix in stop:
        return None
    suffix = m.group("suffix") or ""
    info = TagInfo(
        raw=m.group(0), verbatim=verbatim, prefix=prefix, number=number,
        suffix=suffix, loop=f"{number}{suffix}",
    )

    # Equipment prefixes win outright.
    if prefix in equip:
        info.category = "equipment"
        info.kind = equip[prefix]["kind"]
        info.isa_function = equip[prefix]["desc"]
        return info

    decoded = decode_instrument(prefix)
    if decoded:
        info.category = "instrument"
        info.measured_variable = decoded["measured_variable"]
        info.isa_function = decoded["function"]
        # A tag whose final function letter is V/Z is a physical final element,
        # not a bubble on the drawing.
        info.is_valve = prefix in VALVE_INSTRUMENT_PREFIXES or prefix[-1] in ("V", "Z")
        info.kind = "valve" if info.is_valve else "instrument"
        # Loop number for an instrument is shared by every member of the loop,
        # so it excludes the function letters but keeps the numeric suffix.
        info.loop = f"{prefix[0]}{number}{suffix}"
        return info

    info.category = "unknown"
    return info


def find_tags(text: str, conventions: Optional[Dict] = None) -> List[TagInfo]:
    """Find every tag-looking token in a blob of text."""
    out: List[TagInfo] = []
    seen = set()
    for m in TAG_RE.finditer(text.upper()):
        info = parse_tag(m.group(0), conventions)
        if info and info.normalized not in seen:
            seen.add(info.normalized)
            out.append(info)
    return out


def find_line_numbers(text: str) -> List[str]:
    """Extract pipe line numbers from a blob of text."""
    out, seen = [], set()
    for m in LINE_NUMBER_RE.finditer(text.upper()):
        ln = re.sub(r"\s+", "", m.group("line"))
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out


def load_conventions(path: Optional[str]) -> Dict:
    """Load a site-specific tag convention file (JSON).

    Shape::

        {
          "equipment_prefixes": {"XC": {"kind": "vessel", "desc": "Crystallizer"}},
          "notes": "Acme Refinery drawing standard DS-0042"
        }
    """
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object at the top level")
    return data


#: Words that look like tag prefixes but never are. Extend per site through
#: the conventions file's "stop_prefixes" list.
STOP_PREFIXES = {
    # units and ratings
    "SET", "PSIG", "PSI", "BARG", "BAR", "KPA", "KW", "DEG", "DEGC", "KG",
    # sizes - DN15 is a nominal diameter, not a density instrument
    "DN", "PN", "NPS", "SCH", "DIA", "OD", "ID",
    # vessel level marks
    "LL", "HL", "HHL", "LLL", "NLL",
    # drawing furniture
    "STEEL", "UNIT", "DWG", "DRAWING", "SHEET", "REV", "NOTE", "NOTES",
    "SCALE", "DATE", "TYP", "MIN", "MAX", "CL", "ANSI", "ASME", "API",
    "ITEM", "NO", "APPROX", "EVAP", "OP",
    # common OEM product-series codes that decode as nonsense ISA strings
    "CPI",
}

#: A tag directly after one of these words is a document reference, not a tag.
_REF_CONTEXT = re.compile(
    r"\b(?:DWG|DRAWING|SHEET|REF|SEE|PER)\.?\s*(?:NO\.?|NUMBER|#)?\s*[A-Z]{1,5}-?\d"
)


def find_component_tags(text: str, conventions: Optional[Dict] = None) -> List[TagInfo]:
    """Find tags in free text that plausibly name a real component.

    Stricter than :func:`find_tags`: it drops document references, units, and
    fragments of line numbers. Used to cross-check the vision pass - a tag the
    text layer contains but that no component carries is a candidate for
    something the scan missed, which is exactly the failure mode that matters
    on a drawing review.
    """
    conventions = conventions or {}
    stop = STOP_PREFIXES | {p.upper() for p in conventions.get("stop_prefixes", [])}
    upper = text.upper()

    # Spans we must not read tags out of. A line number like 8"-P-1101-A1A-HC
    # contains "P-1101" and "B-1A" and neither names a component.
    dead_spans = [m.span() for m in LINE_NUMBER_RE.finditer(upper)]
    dead_spans += [m.span() for m in _REF_CONTEXT.finditer(upper)]

    def overlaps_dead(start: int, end: int) -> bool:
        return any(start < d_end and end > d_start for d_start, d_end in dead_spans)

    out: List[TagInfo] = []
    seen = set()

    # Reference designations first: on an IEC 81346 drawing these *are* the
    # tags, and they are unambiguous because of the leading aspect character.
    for token in re.split(r"[\s,;()]+", upper):
        token = token.strip(".")
        if RDS_RE.match(token):
            info = parse_tag(token, conventions)
            if info and info.normalized not in seen:
                seen.add(info.normalized)
                out.append(info)

    for m in TAG_RE_STRICT.finditer(upper):
        if overlaps_dead(m.start(), m.end()):
            continue
        # Skip the ISA-shaped tail of a reference designation ("=K10" -> "K10")
        # and anything glued to the preceding token.
        before = upper[m.start() - 1] if m.start() else " "
        after = upper[m.end()] if m.end() < len(upper) else " "
        if before in "=+-" or before.isalnum():
            continue
        # Glued to what follows: "M12x1.5" is a thread spec, not tag M-12.
        if after.isalnum():
            continue
        info = parse_tag(m.group(0), conventions)
        if not info or info.category == "unknown":
            continue
        if info.prefix in stop:
            continue
        # A one-letter prefix with a one-digit number ("B-1A") is prose about a
        # line class or a note reference, never an equipment tag - real ones
        # carry at least a two-digit number.
        if len(info.prefix) == 1 and len(info.number) == 1:
            continue
        if info.normalized in seen:
            continue
        seen.add(info.normalized)
        out.append(info)
    return out


def find_tags_in_words(words, conventions: Optional[Dict] = None) -> List[TagInfo]:
    """Find tags using the text layer's *coordinates*, not just its characters.

    An instrument bubble is drafted with the ISA letters on one line and the
    loop number on the line below, so the PDF text layer holds them as two
    separate words: ``FIC`` and ``1010``. Joined by string adjacency they are
    indistinguishable from prose like "SIZED FOR 300" - joined by geometry they
    are unambiguous, because the number sits directly beneath the letters
    inside the same circle.

    ``words`` is a sequence of :class:`pid_scan.pdfdoc.Word`.
    """
    conventions = conventions or {}
    stop = STOP_PREFIXES | {w.upper() for w in conventions.get("stop_prefixes", [])}

    out: List[TagInfo] = []
    seen = set()

    def keep(info: Optional[TagInfo]) -> None:
        if info and info.normalized not in seen:
            seen.add(info.normalized)
            out.append(info)

    # Whole-token tags and reference designations, from the joined text.
    for info in find_component_tags(" ".join(w.text for w in words), conventions):
        keep(info)

    def isolated(w) -> bool:
        """True when nothing else sits beside ``w`` on its own line.

        Text inside an instrument bubble is alone in its circle. Prose is not:
        "120 TRAYS" stacked over "2400 KG" has the same geometry as a bubble
        until you notice TRAYS has a neighbour.
        """
        height = max(w.y1 - w.y0, 1.0)
        width = max(w.x1 - w.x0, 1.0)
        for other in words:
            if other is w:
                continue
            if abs(other.cy - w.cy) > 0.5 * height:
                continue  # a different line
            gap = max(other.x0 - w.x1, w.x0 - other.x1)
            if gap < 1.2 * width:
                return False
        return True

    letters = [w for w in words
               if 2 <= len(w.text) <= 5 and w.text.isalpha()
               and w.text.upper() not in stop and decode_instrument(w.text.upper())]
    numbers = [w for w in words if w.text.isdigit() and 1 <= len(w.text) <= 6]

    for lw in letters:
        height = max(lw.y1 - lw.y0, 1.0)
        width = max(lw.x1 - lw.x0, 1.0)
        if not isolated(lw):
            continue
        best, best_dy = None, None
        for nw in numbers:
            # Bubble text is set at one size; a much larger or smaller number
            # below is a different piece of text that happens to line up.
            if not (0.6 * height < (nw.y1 - nw.y0) < 1.5 * height):
                continue
            dy = nw.cy - lw.cy
            # Directly below, within about one and a half line heights, and
            # horizontally centred on the letters.
            if not (0.3 * height < dy < 2.4 * height):
                continue
            if abs(nw.cx - lw.cx) > 0.9 * max(width, nw.x1 - nw.x0):
                continue
            if not isolated(nw):
                continue
            if best_dy is None or dy < best_dy:
                best, best_dy = nw, dy
        if best is not None:
            keep(parse_tag(f"{lw.text.upper()}-{best.text}", conventions))
    return out
