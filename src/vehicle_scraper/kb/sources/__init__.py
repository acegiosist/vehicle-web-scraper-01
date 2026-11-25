"""External sources (migration 0017): which value wins, and the code that queries each source.

Decided 2026-11-25:

* Several sources can give a value for one field; each keeps its own ``external`` evidence
  (``spec_evidence.source_code``). Among them, what a person captured in the template
  (``captura``) wins, then ``kb.external_source.priority`` (lower first). Across kinds nothing
  changes: manual > external > listings > ai.
* A source is queried one generation at a time from the portal (``source_lookup``), and a
  person accepts field by field what it returned (``source_apply``). Only active sources that
  apply to one of the generation's countries are offered (``countries`` empty = all); paid
  sources aren't offered at all yet.
* Each adapter (``vpic.py``, ``fueleconomy.py``) has a pure ``propose(target, records)`` that
  matches the source's records to the generation and its powertrains (tested offline with
  saved responses) and a ``fetch(client, target)`` that calls the source through
  ``PoliteClient`` (robots.txt, per-host delay, retries). Only make, model and years are sent.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..levels import SOURCE_RANK

CAPTURE = "captura"            # the capture template (kb/specs.py): always first among external values
UNRANKED = 10 ** 6             # an external value from a source no longer in the registry
MAX_YEARS = 12                 # years queried per lookup (each year is one or more requests)


def external_ranks(cur) -> dict[str, int]:
    """Source code -> rank among external values (``captura`` first, then the registry's priority)."""
    cur.execute("SELECT code, priority FROM kb.external_source")
    return {CAPTURE: 0, **{code: priority for code, priority in cur.fetchall()}}


def evidence_rank(kind: str, code: str, ranks: dict[str, int]) -> tuple[int, int]:
    """Lower wins: the kind's precedence, then (for external values) the source's rank."""
    return SOURCE_RANK[kind], (ranks.get(code, UNRANKED) if kind == "external" else 0)


@dataclass
class PowertrainTarget:
    id: int
    displacement: Optional[float]
    cylinders: Optional[int]
    fuel: Optional[str]
    transmission: Optional[str]
    drivetrain: Optional[str]
    years: list[int]                 # sale years of its variants in the source's countries


@dataclass
class Target:
    """What a source is asked about: one generation and the powertrains in its countries."""
    generation_id: int
    make: str
    model: str
    body_style: Optional[str]
    years: list[int]
    powertrains: list[PowertrainTarget] = field(default_factory=list)


@dataclass
class Proposal:
    entity_type: str                 # generation | powertrain
    entity_id: int
    field: str                       # level column
    value: object
    records: int                     # source records that gave this value
    alternatives: dict = field(default_factory=dict)    # other values -> records, when they disagree
    years: list[int] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)    # the source's names for what matched

    def as_dict(self) -> dict:
        return {"entity_type": self.entity_type, "entity_id": self.entity_id, "field": self.field,
                "value": self.value, "records": self.records, "alternatives": self.alternatives,
                "years": self.years, "matched": self.matched}


def most_common(entity_type: str, entity_id: int, field_name: str, values: list[tuple[object, int, str]]
                ) -> Optional[Proposal]:
    """The value most records give (ties: the larger one), with the others as alternatives.
    ``values``: (value, year, source name) per record."""
    if not values:
        return None
    counts = Counter(v for v, _, _ in values)
    best = max(counts, key=lambda v: (counts[v], v))
    return Proposal(entity_type, entity_id, field_name, best, counts[best],
                    {str(v): n for v, n in counts.items() if v != best},
                    sorted({y for v, y, _ in values if v == best}),
                    sorted({name for v, _, name in values if v == best}))


def adapters() -> dict[str, Callable]:
    """Source code -> ``lookup(client, target) -> (proposals, notes)``."""
    from . import fueleconomy, vpic
    return {"vpic_canada": vpic.lookup, "fueleconomy": fueleconomy.lookup}
