# SPDX-License-Identifier: GPL-3.0-only
"""One successful immutable layout per command; no native Fusion objects."""
from dataclasses import dataclass
from .geometry import generate


@dataclass(frozen=True)
class Prepared:
    region: object
    settings: object
    context: tuple
    cells: tuple


class GeometryCache:
    def __init__(self):
        self.prepared = None
        self.hits = 0
        self.misses = 0

    def clear(self):
        self.prepared = None

    def resolve(self, region, settings, context=()):
        value = self.prepared
        if value is not None and (value.region, value.settings, value.context) == (region, settings, context):
            self.hits += 1
            return value.cells
        self.misses += 1
        cells = tuple(generate(region, settings))
        self.prepared = Prepared(region, settings, context, cells)
        return cells
