"""Manual vision reading of Nandi-TBC--A0.pdf.

Recorded by reading the rendered tiles directly rather than calling the API,
so the merge/report half of the pipeline can be exercised and reviewed before
any API key exists. Coordinates are tile-relative 0-1000, taken from the PDF
text layer where a tag exists, so they land on the real symbol.

Coverage: tiles 0, 1, 2, 4, 5, 9, 10, 19, 21, 23, 24, 25, 11, 29 were read at
full resolution. The =A2Ax valve stations and =A1Ax chambers are five
repetitions of one pattern; the pattern was read on =A2A1/=A1A1 and applied to
its repeats, which is recorded per component in ``basis``.
"""

# (tile, x, y, kind, subtype, tag, label, notes, confidence, basis)
# basis: "read" = seen at full resolution, "pattern" = repeat of a read unit.
R = [
    # ---------------- =K1 screw compressor package (tile 21) --------------
    (21, 355, 690, "compressor", "screw", "=K1", "Screw compressor",
     "Main refrigeration compressor, package =K1", 0.95, "read"),
    (21, 253, 825, "driver", "motor", "=K1 motor", "M 3~",
     "Three-phase motor driving the =K1 screw compressor", 0.93, "read"),
    (21, 645, 720, "vessel", "oil_separator", "=K1 oil sep", "Oil separator",
     "Horizontal separator with coalescer and baffles; carries LS =B7 level "
     "switch and =P1/=P2 sight glasses", 0.88, "read"),
    (21, 241, 560, "instrument", "position_transmitter", "GIT =K1", "",
     "Slide-valve position transmitter - compressor capacity feedback", 0.82, "read"),
    (21, 12, 572, "instrument", "pressure_transmitter", "PT =K2", "", "Suction pressure", 0.85, "read"),
    (21, 10, 652, "instrument", "temperature_transmitter", "TT =K3", "", "Suction temperature", 0.85, "read"),
    (21, 345, 794, "instrument", "pressure_transmitter", "PT =K4", "", "", 0.88, "read"),
    (21, 345, 743, "instrument", "temperature_transmitter", "TT =K5", "", "", 0.88, "read"),
    (21, 402, 708, "instrument", "temperature_transmitter", "TT =K6", "", "", 0.88, "read"),
    (21, 465, 708, "instrument", "level_switch", "LS =B7", "",
     "Oil separator level switch", 0.88, "read"),
    (21, 472, 808, "instrument", "temperature_transmitter", "TT =K8", "", "Discharge temperature", 0.88, "read"),
    (21, 527, 988, "instrument", "pressure_transmitter", "PT =K9", "", "Oil pressure", 0.75, "read"),
    (21, 429, 864, "instrument", "pressure_transmitter", "PT =K10", "", "", 0.88, "read"),
    (21, 655, 620, "instrument", "pressure_gauge", "PI =P1", "", "Oil pressure gauge", 0.88, "read"),
    (21, 85, 509, "valve", "solenoid", "=Q14/=Q15", "Capacity control solenoids",
     "Block of four solenoid valves =Q12/=Q13/=Q14/=Q15 - slide valve load/unload", 0.80, "read"),
    (21, 101, 561, "valve", "solenoid", "=Q12/=Q13", "Capacity control solenoids",
     "Lower pair of the four-solenoid capacity control block", 0.80, "read"),
    (21, 679, 442, "valve", "relief", "=F1", "", "On oil separator, RB-40-A2505-003", 0.85, "read"),
    (21, 735, 444, "valve", "relief", "=F2", "", "Second relief on the oil separator", 0.85, "read"),
    (21, 756, 428, "valve", "relief", "=F4", "", "Discharge relief, RD-50-A2505-034", 0.85, "read"),
    (21, 836, 427, "valve", "relief", "=F5", "", "Second discharge relief on changeover =Q6", 0.85, "read"),
    (21, 810, 659, "valve", "check", "=R1", "", "Discharge check valve", 0.80, "read"),
    (21, 143, 702, "inline_device", "suction_filter", "=R2 / =V1", "",
     "Suction strainer and shut-off on the compressor inlet", 0.72, "read"),
    (21, 592, 960, "valve", "three_way", "=V2", "Oil thermostatic valve",
     "Three-way oil temperature control valve, ports A/B/C, marked 65/70/90/135", 0.72, "read"),
    (21, 498, 751, "inline_device", "oil_filter", "=E1", "", "Oil filter / heater element", 0.65, "read"),
    (21, 514, 839, "inline_device", "oil_filter", "=E2", "", "Second oil filter element", 0.65, "read"),

    # ---------------- =K2 screw compressor package (tile 23) --------------
    (23, 99, 620, "compressor", "screw", "=K2", "Screw compressor",
     "Second refrigeration compressor, package =K2; mirrors =K1", 0.93, "read"),
    (23, 99, 613, "driver", "motor", "=K2 motor", "M 3~", "Three-phase motor", 0.90, "read"),
    (23, 500, 540, "vessel", "oil_separator", "=K2 oil sep", "Oil separator",
     "As =K1: coalescer, baffles, LS =B7, sight glasses =P1/=P2", 0.85, "read"),
    (23, 88, 355, "instrument", "position_transmitter", "GIT =K1", "",
     "Slide-valve position transmitter on =K2", 0.80, "read"),
    (23, 193, 588, "instrument", "pressure_transmitter", "PT =K4", "", "", 0.85, "read"),
    (23, 193, 538, "instrument", "temperature_transmitter", "TT =K5", "", "", 0.85, "read"),
    (23, 250, 504, "instrument", "temperature_transmitter", "TT =K6", "", "", 0.85, "read"),
    (23, 313, 504, "instrument", "level_switch", "LS =B7", "", "Oil separator level switch", 0.85, "read"),
    (23, 320, 603, "instrument", "temperature_transmitter", "TT =K8", "", "", 0.85, "read"),
    (23, 375, 792, "instrument", "pressure_transmitter", "PT =K9", "", "", 0.85, "read"),
    (23, 277, 659, "instrument", "pressure_transmitter", "PT =K10", "", "", 0.85, "read"),
    (23, 502, 416, "instrument", "pressure_gauge", "PI =P1", "", "Oil pressure gauge", 0.85, "read"),
    (23, 527, 238, "valve", "relief", "=F1", "", "Oil separator relief", 0.82, "read"),
    (23, 583, 241, "valve", "relief", "=F2", "", "Oil separator relief", 0.82, "read"),
    (23, 604, 224, "valve", "relief", "=F4", "", "Discharge relief, RD-50-A2505-035", 0.82, "read"),
    (23, 684, 223, "valve", "relief", "=F5", "", "Discharge relief on changeover", 0.82, "read"),
    (23, 658, 455, "valve", "check", "=R1", "", "Discharge check valve", 0.78, "read"),
    (23, 267, 775, "valve", "three_way", "=V2", "Oil thermostatic valve",
     "Three-way oil temperature control valve", 0.70, "read"),
    (23, 614, 873, "heat_exchanger", "plate", "=E1", "Oil cooler",
     "Sea-water cooled plate oil cooler for =K2; nozzles N1-N4, N6", 0.85, "read"),
    (23, 722, 898, "instrument", "pressure_gauge", "PI =F", "", "Oil cooler water side", 0.82, "read"),
    (23, 689, 969, "instrument", "pressure_gauge", "PI =F", "", "Oil cooler water side", 0.82, "read"),

    # ---------------- =C1 sea-water condensers (tiles 4, 5) ---------------
    (4, 540, 408, "heat_exchanger", "plate", "=C1C1", "Plate condenser",
     "Sea-water cooled condenser, nozzles N1(100) N2 N4(40) N5(25) N6(65) N7(40)", 0.90, "read"),
    (5, 229, 415, "heat_exchanger", "plate", "=C1C2", "Plate condenser",
     "Second sea-water cooled condenser", 0.90, "read"),
    (4, 434, 303, "instrument", "pressure_gauge", "PI =F", "", "=C1C1 refrigerant side", 0.85, "read"),
    (4, 530, 326, "instrument", "pressure_gauge", "PI =F", "", "=C1C1", 0.85, "read"),
    (4, 660, 303, "instrument", "pressure_gauge", "PI =F", "", "=C1C1 water side", 0.85, "read"),
    (4, 925, 303, "instrument", "pressure_gauge", "PI =F", "", "=C1C2 refrigerant side", 0.85, "read"),
    (5, 349, 303, "instrument", "pressure_gauge", "PI =F", "", "=C1C2", 0.85, "read"),
    (5, 122, 303, "instrument", "pressure_gauge", "PI =F", "", "=C1C2", 0.85, "read"),
    (4, 714, 464, "instrument", "gas_detector", "QT =F1", "GFG SENSOR",
     "Ammonia gas detector serving the condenser area", 0.88, "read"),
    (4, 564, 451, "valve", "relief", "=F2", "DN20/32 20 bar", "Condenser relief valve", 0.85, "read"),
    (5, 253, 451, "valve", "relief", "=F2", "DN20/32 20 bar", "Condenser relief valve", 0.85, "read"),
    (4, 679, 76, "valve", "manual", "=Q9", "Purge valve",
     "PURGE VALVE AT HIGHEST POINT - non-condensable purge", 0.88, "read"),

    # ---------------- =R1 liquid receiver (tile 9) ------------------------
    (9, 797, 435, "vessel", "horizontal_drum", "=C", "DIA. 800 X 2500",
     "High-pressure liquid receiver, block =R1/=R1R1; nozzles N1(15) N3(25) "
     "N4(40) N6(200) N9(40)", 0.92, "read"),
    (9, 765, 336, "valve", "relief", "=F1", "DN25/40 21 bar",
     "Receiver relief valve, one of a pair on changeover =Q5, to Blow Off", 0.90, "read"),
    (9, 805, 335, "valve", "relief", "=F2", "DN25/40 21 bar",
     "Second receiver relief valve on the changeover", 0.90, "read"),
    (9, 787, 361, "valve", "three_way", "=Q5", "Relief changeover",
     "Changeover valve so one relief can be isolated while the other stays in service", 0.85, "read"),
    (9, 649, 310, "instrument", "pressure_gauge", "PI =F", "", "Receiver pressure, isolated by =Q2", 0.88, "read"),
    (9, 428, 513, "instrument", "level_switch", "LSAL =F1", "NO",
     "Receiver low level alarm, normally open contact", 0.88, "read"),
    (9, 478, 434, "inline_device", "sight_glass", "=P1", "",
     "Level column / sight glass on the receiver, isolated by =Q1 and =Q3", 0.75, "read"),
    (9, 645, 599, "valve", "relief", "=F3", "DN15/15 20 bar", "On the N6 200mm liquid outlet", 0.85, "read"),
    (9, 887, 599, "valve", "relief", "=F2", "DN15/15 20 bar", "On the N9 40mm connection", 0.85, "read"),

    # ---------------- =S1 pump separator / surge drum (tile 19) -----------
    (19, 469, 411, "vessel", "vertical_drum", "=C1", "DIA. 1200 X 2500",
     "Pump separator / low pressure receiver, block =S1. Nozzles N1(150) "
     "N2(40) N3(25) N4(40) N5(100) N6(20) N8(32) N9(20) N10(20) N11(20) N12(150)", 0.92, "read"),
    (19, 386, 118, "valve", "relief", "=F1", "DN25/40 14 Bar",
     "Separator relief valve, one of a pair on changeover =Q2", 0.90, "read"),
    (19, 428, 118, "valve", "relief", "=F2", "DN25/40 14 Bar",
     "Second separator relief valve on the changeover", 0.90, "read"),
    (19, 407, 138, "valve", "three_way", "=Q2", "Relief changeover", "", 0.85, "read"),
    (19, 634, 301, "instrument", "pressure_gauge", "PI =F", "", "Separator pressure, isolated by =Q5", 0.88, "read"),
    (19, 803, 392, "instrument", "level_switch", "LZHH =F", "NC",
     "High-high level trip, GAUGE PANEL 2, normally closed. HHL = 1412mm", 0.90, "read"),
    (19, 803, 442, "instrument", "level_switch", "LSAH =F", "NC",
     "High level alarm, GAUGE PANEL 2, normally closed. HL = 1200mm", 0.90, "read"),
    (19, 802, 511, "instrument", "level_switch", "LSAL =F", "NO",
     "Low level alarm, GAUGE PANEL 2, normally open. LL = 395mm", 0.90, "read"),
    (19, 625, 170, "valve", "manual", "=Q17", "",
     "Isolation on the DN125 wet return RR-125-A14.510-002 into N12", 0.82, "read"),
    (19, 1258, 180, "valve", "solenoid", "=Q7", "Make-up solenoid",
     "MAKE-UP STATION SIZED FOR 300/0.9 = 340 kW - duty leg solenoid", 0.78, "read"),
    (19, 234, 922, "vessel", "horizontal_drum", "=C1", "DIA. 1000 X 150",
     "Small drum in the =S1 block with vent lines and hot gas connection; "
     "nozzles N1(20) N2(32) N3(20) N4(20)", 0.75, "read"),
    (19, 211, 743, "valve", "relief", "=F1", "DN15/15 14 bar", "On the small =S1 drum", 0.85, "read"),
    (19, 168, 832, "instrument", "pressure_gauge", "PI =F", "", "Small drum pressure, isolated by =Q21", 0.82, "read"),
    (19, 369, 893, "inline_device", "strainer", "=R1", "", "", 0.65, "read"),

    # ---------------- =H1 liquid sub-cooler / economiser (tile 21) --------
    (21, 731, 175, "heat_exchanger", "plate", "=E1", "Sub-cooler / economiser",
     "Sub-cools HP liquid from +35 DegC to -3 DegC against refrigerant "
     "evaporating at approx -18 DegC; suction leaves at -8 DegC (10 K superheat). "
     "Nozzles S1(50) S2(50) S3(50) S4(50)", 0.90, "read"),
    (21, 592, 214, "instrument", "temperature_controller", "TC =Q4", "",
     "Temperature controller driving the =Q4 expansion valve on the economiser", 0.85, "read"),
    (21, 592, 240, "valve", "control", "=Q4", "Expansion valve",
     "Economiser feed expansion valve, TC controlled", 0.82, "read"),
    (21, 696, 30, "valve", "relief", "=F1", "DN15/15 20 bar", "On RB-15-A2506-024, +35 DegC liquid", 0.85, "read"),
    (21, 403, 196, "valve", "relief", "=F2", "DN15/15 20 bar", "On the economiser", 0.85, "read"),

    # ---------------- =P2 sea water pumps (tile 11) -----------------------
    (11, 282, 588, "pump", "centrifugal", "=G1", "DUTY",
     "Sea water pump, duty. Feeds the =C1 condensers via CS-200-A1010-032", 0.90, "read"),
    (11, 282, 840, "pump", "centrifugal", "=G2", "STANDBY", "Sea water pump, standby", 0.90, "read"),
    (11, 256, 611, "driver", "motor", "=G1 motor", "M", "", 0.85, "read"),
    (11, 256, 864, "driver", "motor", "=G2 motor", "M", "", 0.85, "read"),
    (11, 143, 566, "valve", "check", "=R1", "", "Duty pump discharge check", 0.82, "read"),
    (11, 143, 819, "valve", "check", "=R2", "", "Standby pump discharge check", 0.82, "read"),
    (11, 227, 493, "instrument", "differential_pressure", "PdI =P1", "",
     "Differential pressure across the duty pump / strainer", 0.85, "read"),
    (11, 227, 746, "instrument", "differential_pressure", "PdI =P1", "",
     "Differential pressure across the standby pump / strainer", 0.85, "read"),
    (11, 184, 450, "instrument", "pressure_gauge", "PI =P1", "", "Duty pump", 0.85, "read"),
    (11, 184, 703, "instrument", "pressure_gauge", "PI =P1", "", "Standby pump", 0.85, "read"),
    (11, 760, 835, "connector", "battery_limit", "CLIENT / GEA", "SEA WATER SUPPLY 0.7 BAR 25 DEGC",
     "Scope split: sea water supplied by client at 0.7 bar, 25 DegC", 0.90, "read"),

    # ---------------- =P1 ammonia recirculation pumps (tile 25) -----------
    (25, 321, 588, "pump", "centrifugal", "=G1", "DUTY",
     "Ammonia liquid recirculation pump, duty, drawing from the =S1 separator", 0.90, "read"),
    (25, 640, 564, "pump", "centrifugal", "=G2", "STANDBY",
     "Ammonia liquid recirculation pump, standby", 0.90, "read"),
    (25, 350, 528, "driver", "motor", "=P1P1??-M?", "M 3~",
     "Duty pump motor - designation shown unresolved on the drawing", 0.80, "read"),
    (25, 605, 528, "driver", "motor", "=P1P1??-M?", "M 3~",
     "Standby pump motor - designation shown unresolved on the drawing", 0.80, "read"),
    (25, 227, 443, "valve", "check", "=R1", "", "Duty pump discharge check", 0.82, "read"),
    (25, 735, 443, "valve", "check", "=R2", "", "Standby pump discharge check", 0.82, "read"),
    (25, 142, 511, "valve", "relief", "=F3", "DN15 14 bar", "Duty pump relief", 0.85, "read"),
    (25, 819, 511, "valve", "relief", "=F4", "DN15 14 bar", "Standby pump relief", 0.85, "read"),
    (25, 423, 497, "inline_device", "strainer", "=V1", "", "Duty pump suction strainer", 0.70, "read"),
    (25, 526, 497, "inline_device", "strainer", "=V2", "", "Standby pump suction strainer", 0.70, "read"),
    (25, 495, 676, "instrument", "pressure_gauge", "PI =F", "", "Pump discharge, isolated by =Q20", 0.82, "read"),

    # ---------------- =A3A1 existing serpentine freezer tie-in (tile 24) --
    (24, 490, 601, "connector", "tie_in", "=A3A1", "TIE INTO EXISTING SERPENTINE FREEZER",
     "Battery limit to an existing serpentine freezer, with a six-branch "
     "liquid distribution manifold and GEA/CLIENT scope markers", 0.88, "read"),
    (24, 673, 258, "valve", "relief", "=F1", "DN15/15 14 bar", "=A3A1 station relief", 0.85, "read"),
    (24, 772, 124, "instrument", "pressure_gauge", "PI =F", "", "=A3A1 station, 6mm SST impulse line", 0.85, "read"),
    (24, 808, 251, "connector", "battery_limit", "GEA / CLIENT", "", "Scope split marker", 0.85, "read"),
    (24, 808, 467, "connector", "battery_limit", "GEA / CLIENT", "", "Scope split marker", 0.85, "read"),
]

# The five blast-freeze chambers. Read on =A1A1 (tile 1); the rest are the
# same unit repeated, confirmed by their text layer.
CHAMBERS = [
    ("=A1A1", 1, 411, 282), ("=A1A2", 1, 941, 283), ("=A1A3?", 2, 661, 283),
    ("=A1A4", 2, 153, 948), ("=A1A5", 3, 62, 948),
]
for tag, tile, x, y in CHAMBERS:
    basis = "read" if tag == "=A1A1" else "pattern"
    R.append((tile, x, y + 120, "heat_exchanger", "air_cooler", f"{tag} =E1",
              "Blast freezer air cooler",
              "Two-section finned evaporator, four fans. Chamber air -28 DegC, "
              "evaporating -31.6 DegC. 120 trays / 2400 kg at 20 kg per tray, "
              "10 layers. No drain tray - floor drain by others.", 0.88, basis))
    for n, fan in enumerate(("=G1", "=G2", "=G4", "=G5")):
        R.append((tile, x - 95 + n * 47, y + 95, "driver", "fan_motor",
                  f"{tag} {fan}", "M 3~", f"Fan motor on {tag}", 0.85, basis))
    R.append((tile, x - 100, y + 330, "instrument", "temperature_indicator",
              f"{tag} TI =F1", "", f"Chamber temperature indicator, {tag}", 0.85, basis))

# The five cooler valve stations feeding those chambers. Read on =A2A1
# (tile 0) and =A2A5 (tile 24).
STATIONS = [("=A2A1", 0, 877, 576), ("=A2A2", 6, 877, 576), ("=A2A3", 12, 877, 576),
            ("=A2A4", 19, 74, 165), ("=A2A5", 19, 74, 655)]
for tag, tile, x, y in STATIONS:
    basis = "read" if tag in ("=A2A1", "=A2A5") else "pattern"
    R.append((tile, x - 100, y - 400, "valve", "relief", f"{tag} =F1", "DN15/15 14 bar",
              f"Relief valve on the {tag} cooler station", 0.85, basis))
    R.append((tile, x - 100, y - 480, "instrument", "pressure_gauge", f"{tag} PI =F", "",
              f"Station pressure gauge, {tag}, on a 6mm SST impulse line", 0.85, basis))
