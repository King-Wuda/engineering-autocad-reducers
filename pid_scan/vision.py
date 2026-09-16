"""Claude vision passes over a P&ID.

Two passes, deliberately separated:

* **Tile pass** - one call per image tile, at full resolution, returning a
  strict :class:`TileResult`. This is where symbol recognition happens. Tiles
  are independent, so they run concurrently.
* **Synthesis pass** - one call per page over the *merged* inventory plus a
  downscaled overview image, producing the narrative. It reasons about the
  drawing as a whole, which a tile can never do.

The system prompt is identical across every tile call and is marked for prompt
caching, so a 40-tile sheet pays for that prefix once instead of forty times.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import anthropic
from pydantic import ValidationError

from .pdfdoc import PageView, Tile
from .prompts import SYNTH_SYSTEM, SYNTH_USER, TILE_SYSTEM, TILE_USER
from .schema import Component, Connection, PageAnalysis, TileResult

log = logging.getLogger("pid_scan.vision")

DEFAULT_MODEL = "claude-opus-5"

#: USD per million tokens, for the run cost estimate. Update alongside the
#: model default.
PRICING = {
    "claude-opus-5":   {"in": 5.00, "out": 25.00},
    "claude-sonnet-5": {"in": 2.00, "out": 10.00},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
}


@dataclass
class Usage:
    """Token and cost accounting for a whole run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, usage) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
            self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def estimate_usd(self, model: str) -> float:
        rate = PRICING.get(model)
        if not rate:
            return 0.0
        return (
            self.input_tokens * rate["in"]
            + self.cache_write_tokens * rate["in"] * 1.25
            + self.cache_read_tokens * rate["in"] * 0.10
            + self.output_tokens * rate["out"]
        ) / 1_000_000

    def as_dict(self, model: str) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "estimated_usd": round(self.estimate_usd(model), 4),
        }


class RefusalError(RuntimeError):
    """The model declined the request. Never expected for engineering drawings."""


def _check_stop(response) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise RefusalError(f"model declined this request (category={category})")


def _image_block(png: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png).decode("utf-8"),
        },
    }


class Scanner:
    """Runs the vision passes against the Claude API."""

    def __init__(
        self,
        client: Optional[anthropic.Anthropic] = None,
        model: str = DEFAULT_MODEL,
        concurrency: int = 4,
        max_retries: int = 3,
        timeout: float = 600.0,
    ):
        self.client = client or anthropic.Anthropic(timeout=timeout)
        self.model = model
        self.concurrency = max(1, concurrency)
        self.max_retries = max_retries
        self.usage = Usage()

    # -- tile pass ---------------------------------------------------------

    def extract_tile(self, tile: Tile, page: PageView) -> TileResult:
        """Inventory one tile. Retries transient failures and bad JSON."""
        hints = tile.word_hints()
        words_json = json.dumps(hints, separators=(",", ":")) if hints else \
            "(no text layer on this page - read all tags from the image itself)"

        user_text = TILE_USER.format(
            index=tile.index + 1, total=len(page.tiles), row=tile.row + 1,
            col=tile.col + 1, page=page.number, words=words_json,
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    system=[{
                        "type": "text",
                        "text": TILE_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{
                        "role": "user",
                        "content": [_image_block(tile.png), {"type": "text", "text": user_text}],
                    }],
                    thinking={"type": "adaptive"},
                    output_format=TileResult,
                )
                _check_stop(response)
                self.usage.add(response.usage)
                result = response.parsed_output
                if result is None:
                    raise ValueError("model returned no parsed output")
                return result
            except RefusalError:
                raise
            except (anthropic.APIStatusError, anthropic.APIConnectionError,
                    ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                sleep = 2 ** attempt
                log.warning("tile %d attempt %d failed (%s), retrying in %ss",
                            tile.index, attempt + 1, type(exc).__name__, sleep)
                time.sleep(sleep)

        log.error("tile %d failed after %d attempts: %s", tile.index, self.max_retries, last_error)
        return TileResult(components=[], connections=[], texts=[])

    def scan_page_tiles(
        self,
        page: PageView,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[Tuple[Tile, TileResult]]:
        """Run every tile of a page concurrently, preserving tile order."""
        results: List[Optional[TileResult]] = [None] * len(page.tiles)
        done = 0

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = {pool.submit(self.extract_tile, t, page): t for t in page.tiles}
            for future in as_completed(futures):
                tile = futures[future]
                results[tile.index] = future.result()
                done += 1
                if progress:
                    progress(done, len(page.tiles))

        return [(t, results[t.index] or TileResult(components=[], connections=[]))
                for t in page.tiles]

    # -- synthesis pass ----------------------------------------------------

    def synthesize(
        self,
        page: PageView,
        components: List[Component],
        connections: List[Connection],
        source: str,
    ) -> PageAnalysis:
        """Turn a merged inventory into a process narrative."""
        inventory = "\n".join(
            f"- {c.tag or '(untagged)'} | {c.kind}/{c.subtype or '?'}"
            f"{' | ' + c.isa_function if c.isa_function else ''}"
            f"{' | ' + c.label if c.label else ''}"
            f"{' | ' + c.notes if c.notes else ''}"
            f" | at ({int(c.box.cx)},{int(c.box.cy)}) | conf {c.confidence:.2f}"
            for c in components
        ) or "(none found)"

        conns = "\n".join(
            f"- {c.from_tag or c.from_id or '?'} -> {c.to_tag or c.to_id or '?'}"
            f" [{c.signal}]{' ' + c.line_number if c.line_number else ''}"
            for c in connections
        ) or "(none found)"

        text = page.full_text[:20000] or "(no text layer)"

        user_text = SYNTH_USER.format(
            page=page.number, source=source,
            n_components=len(components), inventory=inventory,
            n_connections=len(connections), connections=conns,
            text=text,
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    system=[{"type": "text", "text": SYNTH_SYSTEM,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{
                        "role": "user",
                        "content": [_image_block(page.overview_png),
                                    {"type": "text", "text": user_text}],
                    }],
                    thinking={"type": "adaptive"},
                    output_format=PageAnalysis,
                )
                _check_stop(response)
                self.usage.add(response.usage)
                return response.parsed_output or PageAnalysis()
            except RefusalError:
                raise
            except (anthropic.APIStatusError, anthropic.APIConnectionError,
                    ValidationError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(2 ** attempt)

        log.error("synthesis failed for page %d: %s", page.number, last_error)
        return PageAnalysis(summary=f"Synthesis pass failed: {last_error}")
