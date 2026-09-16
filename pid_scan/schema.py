"""Data model for a scanned P&ID.

Two layers of types live here:

* ``Tile*`` models are what Claude returns for a single image tile. They are
  deliberately flat and small so the model can fill them reliably, and all
  geometry is expressed in *tile-relative* 0-1000 units.
* ``Component`` / ``Drawing`` are the merged, page-level result. Geometry is in
  *page-relative* 0-1000 units, so a consumer never needs to know the render
  DPI or the tile grid that produced it.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------

#: Top-level component families. Kept short on purpose: a long enum makes the
#: model hesitate between near-synonyms, and the useful detail lives in
#: ``subtype`` anyway.
ComponentKind = Literal[
    "vessel",        # drums, tanks, columns, reactors, separators, accumulators
    "pump",
    "compressor",    # compressors, blowers, fans, ejectors
    "heat_exchanger",# coolers, condensers, reboilers, heaters, chillers
    "driver",        # motors, turbines, engines driving a machine
    "valve",
    "instrument",    # anything drawn as an ISA bubble
    "inline_device", # filters, strainers, silencers, flame arrestors, orifice plates
    "connector",     # off-page / off-drawing continuation arrows
    "equipment_other",
]

#: Valve subtypes we ask the model to distinguish, by symbol shape.
VALVE_SUBTYPES = [
    "gate", "globe", "ball", "butterfly", "plug", "needle", "diaphragm",
    "check", "three_way", "four_way", "control", "relief", "rupture_disc",
    "self_regulating", "unknown",
]

#: How an actuated valve is driven.
ActuatorKind = Literal[
    "none", "manual", "diaphragm", "piston", "motor", "solenoid",
    "hydraulic", "self_actuated", "unknown",
]

#: ISA-5.1 line styles for instrument signals.
SignalKind = Literal[
    "process", "electric", "pneumatic", "hydraulic", "capillary",
    "software", "data_link", "electromagnetic", "mechanical", "unknown",
]


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

class Box(BaseModel):
    """Axis-aligned bounding box in 0-1000 units, origin top-left."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def area(self) -> float:
        return max(0, self.x1 - self.x0) * max(0, self.y1 - self.y0)

    def union(self, other: "Box") -> "Box":
        return Box(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )

    def iou(self, other: "Box") -> float:
        ix0, iy0 = max(self.x0, other.x0), max(self.y0, other.y0)
        ix1, iy1 = min(self.x1, other.x1), min(self.y1, other.y1)
        inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
        if inter == 0:
            return 0.0
        return inter / (self.area + other.area - inter)


# --------------------------------------------------------------------------
# What Claude returns per tile
# --------------------------------------------------------------------------

class TileComponent(BaseModel):
    """One symbol recognised inside a single tile."""

    local_id: str = Field(
        description="Short id unique within this tile, e.g. 'c1'. Used to "
                    "reference this component from connections."
    )
    kind: ComponentKind
    subtype: str = Field(
        description="Specific symbol type, lowercase snake_case. For valves one "
                    "of: gate, globe, ball, butterfly, plug, needle, diaphragm, "
                    "check, three_way, four_way, control, relief, rupture_disc, "
                    "self_regulating, unknown. For vessels: horizontal_drum, "
                    "vertical_drum, tank, column, reactor, separator, sphere. "
                    "For pumps: centrifugal, positive_displacement, reciprocating, "
                    "gear, screw, vertical_can, sump. For compressors: "
                    "centrifugal, reciprocating, screw, blower, fan, ejector. "
                    "For heat exchangers: shell_and_tube, air_cooled, plate, "
                    "double_pipe, kettle_reboiler, coil, fired_heater. "
                    "Use 'unknown' if the symbol is ambiguous."
    )
    tag: str = Field(
        description="Equipment or instrument tag exactly as printed, e.g. "
                    "'P-101A', 'PSV-2201', 'FIC-1010'. Empty string if untagged."
    )
    label: str = Field(
        description="Any other text printed on or immediately beside the symbol "
                    "(service description, size, rating, duty, notes). Empty if none."
    )
    box: Box = Field(description="Bounding box of the symbol in 0-1000 tile units.")
    actuator: ActuatorKind = Field(
        default="none",
        description="For valves only: how it is actuated. 'none' for non-valves.",
    )
    fail_position: str = Field(
        default="",
        description="For valves only: FC, FO, FL, FI or '' if not marked.",
    )
    notes: str = Field(
        default="",
        description="Anything else that matters about this item: set pressure on "
                    "a relief valve, spare/standby marking, insulation, tracing, "
                    "jacket, vendor package boundary. Empty if nothing notable.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="0-1. Below 0.5 means the symbol is genuinely ambiguous.",
    )


class TileConnection(BaseModel):
    """A line segment between two things visible in this tile."""

    from_id: str = Field(description="local_id of the source component, or '' if the line enters from a tile edge.")
    to_id: str = Field(description="local_id of the destination component, or '' if the line leaves at a tile edge.")
    signal: SignalKind = Field(description="Line style: solid=process, dashed=electric, etc.")
    line_number: str = Field(
        default="",
        description="Line number printed on the pipe, e.g. '6\"-P-1201-A1A-HC'. Empty if none.",
    )
    edge: str = Field(
        default="",
        description="If the line runs off the tile, which edge: top/bottom/left/right. Empty otherwise.",
    )


class TileResult(BaseModel):
    """Everything Claude found in one tile."""

    components: List[TileComponent]
    connections: List[TileConnection]
    texts: List[str] = Field(
        default_factory=list,
        description="Free-standing text in this tile that is not a component "
                    "label: notes, legend entries, title block lines.",
    )


# --------------------------------------------------------------------------
# Merged, page-level result
# --------------------------------------------------------------------------

class Component(BaseModel):
    """A component after tiles have been merged and tags reconciled."""

    id: str
    kind: ComponentKind
    subtype: str = ""
    tag: str = ""
    label: str = ""
    page: int = 1
    box: Box
    actuator: str = "none"
    fail_position: str = ""
    notes: str = ""
    confidence: float = 0.0
    #: How many tiles independently saw this component. Higher is better
    #: evidence; 1 on a component in an overlap zone is a soft warning.
    detections: int = 1
    #: "vision" (symbol only), "text" (tag from the PDF text layer only),
    #: or "both" (symbol recognised AND tag confirmed against the text layer).
    source: str = "vision"
    #: Decoded ISA meaning for instruments, e.g. "Flow Indicating Controller".
    isa_function: str = ""
    loop: str = ""


class Connection(BaseModel):
    from_tag: str = ""
    to_tag: str = ""
    from_id: str = ""
    to_id: str = ""
    signal: str = "process"
    line_number: str = ""
    page: int = 1


class ControlLoop(BaseModel):
    loop_id: str
    measured_variable: str = ""
    description: str = ""
    members: List[str] = Field(default_factory=list)
    final_element: str = ""


class Finding(BaseModel):
    """Something worth a human's attention, produced by the synthesis pass."""

    severity: Literal["info", "note", "warning"] = "note"
    category: str = ""
    message: str = ""
    refs: List[str] = Field(default_factory=list)


class PageAnalysis(BaseModel):
    """Narrative synthesis for one drawing sheet."""

    title: str = ""
    drawing_number: str = ""
    revision: str = ""
    summary: str = ""
    process_description: str = ""
    major_streams: List[str] = Field(default_factory=list)
    control_narrative: str = ""
    safety_narrative: str = ""
    utilities: List[str] = Field(default_factory=list)
    loops: List[ControlLoop] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class Page(BaseModel):
    number: int
    width_pt: float
    height_pt: float
    has_text_layer: bool
    tiles: int = 0
    components: List[Component] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)
    texts: List[str] = Field(default_factory=list)
    #: Pipe line numbers read from the PDF's own text layer. Exact, and
    #: independent of whether the vision pass noticed the line they label.
    line_numbers: List[str] = Field(default_factory=list)
    #: Tags the text layer proves are on this sheet. Anything here that no
    #: component carries is a candidate for something the scan missed.
    text_tags: List[str] = Field(default_factory=list)
    analysis: PageAnalysis = Field(default_factory=PageAnalysis)


class Drawing(BaseModel):
    """The complete scan result for one PDF."""

    source: str
    model: str = ""
    pages: List[Page] = Field(default_factory=list)
    scanned_at: str = ""
    stats: dict = Field(default_factory=dict)

    def all_components(self) -> List[Component]:
        return [c for p in self.pages for c in p.components]
