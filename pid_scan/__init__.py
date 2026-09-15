"""pid-scan - read a P&ID PDF with Claude and report what is on it."""

from .scan import ScanConfig, scan_pdf
from .schema import Component, Drawing, Page
from .vision import Scanner

__version__ = "0.1.0"
__all__ = ["ScanConfig", "scan_pdf", "Scanner", "Drawing", "Page", "Component"]
