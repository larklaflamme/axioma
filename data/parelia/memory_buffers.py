"""
Memory Buffers — L1 scratch + L2 working memory for Parelia v2.

L1: Fixed-size ring buffer for raw telemetry history (fast, compact)
L2: Time-decay attention buffer for working memory (structured, queryable)

Architecture:
  Telemetry stream → L1 (raw ring) → L2 (decay-weighted summaries)
                       ↓
                 PlateauDetector reads from L1

Design: 01_ARCHITECTURE_OVERVIEW.md §IV
"""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── L1: Scratch Buffer (fixed-size ring) ─────────────────────────────────

@dataclass
class L1Config:
    """Configuration for L1 scratch buffer."""

    maxlen: int = 1000       # Max records kept in memory
    auto_persist: bool = True  # Write checkpoint to disk periodically
    persist_path: str | None = None  # Optional checkpoint file


class L1ScratchBuffer:
    """Fixed-size ring buffer for raw telemetry records.

    Stores the last N records in memory. Oldest records are evicted
    when the buffer fills. Optionally persists checkpoints to disk.
    """

    def __init__(self, config: L1Config | None = None) -> None:
        self.config = config or L1Config()
        self._buffer: deque[dict] = deque(maxlen=self.config.maxlen)
        self._write_count: int = 0
        self._last_checkpoint: int = 0

    def append(self, record: dict) -> None:
        """Add a record to the buffer. Evicts oldest if full."""
        self._buffer.append(record)
        self._write_count += 1

        if self.config.auto_persist and self.config.persist_path:
            if self._write_count - self._last_checkpoint >= 100:
                self._checkpoint()

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def filled(self) -> bool:
        return len(self._buffer) >= self.config.maxlen

    @property
    def occupancy(self) -> float:
        return len(self._buffer) / self.config.maxlen

    def tail(self, n: int) -> list[dict]:
        """Return the last n records (or fewer if buffer isn't full)."""
        return list(self._buffer)[-n:]

    def slice(self, start: int, end: int | None = None) -> list[dict]:
        """Return records from index start to end (negative indexing works)."""
        records = list(self._buffer)
        return records[start:end]

    def get_field(self, field: str, n: int | None = None) -> list[Any]:
        """Extract a single field from the last n records."""
        records = self.tail(n) if n else list(self._buffer)
        return [r.get(field) for r in records if field in r]

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()

    def _checkpoint(self) -> None:
        """Write current buffer to disk as JSON."""
        if not self.config.persist_path:
            return
        try:
            path = Path(self.config.persist_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(list(self._buffer), f, separators=(",", ":"))
            self._last_checkpoint = self._write_count
        except OSError as e:
            logger.warning("l1_checkpoint_failed: %s", e)

    def load_checkpoint(self, path: str | None = None) -> int:
        """Load buffer from a checkpoint file. Returns records loaded."""
        p = path or self.config.persist_path
        if not p or not Path(p).exists():
            return 0
        try:
            with open(p) as f:
                records = json.load(f)
            for r in records[-self.config.maxlen:]:
                self._buffer.append(r)
            self._write_count = len(self._buffer)
            return len(records)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("l1_load_failed: %s", e)
            return 0


# ── L2: Working Memory (time-decay attention) ────────────────────────────

@dataclass
class L2Config:
    """Configuration for L2 working memory."""

    max_items: int = 100        # Max items in working memory
    base_decay: float = 0.95    # Decay factor per tick
    significance_decay: float = 0.1  # How much significance slows decay
    min_weight: float = 0.01    # Prune items below this weight


@dataclass
class MemoryItem:
    """A single item in working memory with decay tracking."""

    content: dict
    weight: float = 1.0
    created: str = ""
    last_accessed: str = ""
    access_count: int = 1
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "weight": round(self.weight, 4),
            "created": self.created,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "tags": self.tags,
        }


class L2WorkingMemory:
    """Time-decay attention buffer for structured working memory.

    Items decay each tick unless re-accessed. High-significance items
    decay more slowly. Items below min_weight are pruned.
    """

    def __init__(self, config: L2Config | None = None) -> None:
        self.config = config or L2Config()
        self._items: list[MemoryItem] = []
        self._tick_count: int = 0

    def add(self, content: dict, significance: float = 0.5,
            tags: list[str] | None = None) -> None:
        """Add a new memory item with initial significance-weighted weight."""
        now = datetime.now(timezone.utc).isoformat()
        item = MemoryItem(
            content=content,
            weight=min(1.0, significance),
            created=now,
            last_accessed=now,
            tags=tags or [],
        )
        self._items.append(item)

        # Evict oldest if over capacity
        if len(self._items) > self.config.max_items:
            self._items.sort(key=lambda x: x.weight)
            self._items.pop(0)

    def access(self, index: int) -> dict | None:
        """Access an item by index. Resets its decay on this tick."""
        if index < 0 or index >= len(self._items):
            return None
        item = self._items[index]
        item.weight = min(1.0, item.weight + 0.1)
        item.last_accessed = datetime.now(timezone.utc).isoformat()
        item.access_count += 1
        return item.content

    def query(self, tags: list[str] | None = None,
              min_weight: float | None = None) -> list[MemoryItem]:
        """Return items matching tags and/or weight threshold."""
        mw = min_weight or self.config.min_weight
        results = [it for it in self._items if it.weight >= mw]
        if tags:
            results = [it for it in results
                       if any(t in it.tags for t in tags)]
        return sorted(results, key=lambda x: x.weight, reverse=True)

    def decay(self) -> None:
        """Apply time decay to all items. Prune below threshold."""
        self._tick_count += 1
        keep: list[MemoryItem] = []
        for item in self._items:
            # Items accessed this tick don't decay
            decay = self.config.base_decay
            # High significance slows decay
            if item.weight > 0.5:
                decay += self.config.significance_decay * item.weight
            item.weight *= decay
            if item.weight >= self.config.min_weight:
                keep.append(item)
        self._items = keep

    def summarize(self, top_n: int = 5) -> list[dict]:
        """Return top-N items as plain dicts."""
        sorted_items = sorted(self._items, key=lambda x: x.weight, reverse=True)
        return [it.to_dict() for it in sorted_items[:top_n]]

    @property
    def count(self) -> int:
        return len(self._items)

    @property
    def ticks(self) -> int:
        return self._tick_count

    def clear(self) -> None:
        self._items.clear()
        self._tick_count = 0


# ── Combined Manager ──────────────────────────────────────────────────────

@dataclass
class MemoryConfig:
    """Combined configuration for the full memory system."""

    l1_maxlen: int = 1000
    l2_max_items: int = 100
    l2_base_decay: float = 0.95
    l2_significance_decay: float = 0.1
    l2_min_weight: float = 0.01


class MemoryManager:
    """Unified interface to L1 + L2 memory buffers.

    L1 receives every telemetry record (raw ring).
    L2 receives high-significance items for longer retention.
    """

    def __init__(self, config: MemoryConfig | None = None,
                 persist_path: str | None = None) -> None:
        cfg = config or MemoryConfig()
        self.l1 = L1ScratchBuffer(L1Config(
            maxlen=cfg.l1_maxlen,
            persist_path=persist_path,
        ))
        self.l2 = L2WorkingMemory(L2Config(
            max_items=cfg.l2_max_items,
            base_decay=cfg.l2_base_decay,
            significance_decay=cfg.l2_significance_decay,
            min_weight=cfg.l2_min_weight,
        ))
        self._total_records: int = 0

    def record(self, record: dict, significance: float = 0.5,
               tags: list[str] | None = None) -> None:
        """Record a telemetry entry. Goes to L1 always, L2 if significant."""
        self.l1.append(record)
        self._total_records += 1
        if significance > 0.3:
            self.l2.add(record, significance=significance, tags=tags)

    def decay(self) -> None:
        """Apply L2 time decay. Call every tick."""
        self.l2.decay()

    @property
    def total(self) -> int:
        return self._total_records


__all__ = [
    "L1Config", "L1ScratchBuffer",
    "L2Config", "L2WorkingMemory", "MemoryItem",
    "MemoryConfig", "MemoryManager",
]