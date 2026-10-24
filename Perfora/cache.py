# SPDX-License-Identifier: GPL-3.0-only
"""One immutable layout per slot, with bounded command-local region slots."""
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
        self.regions = {}
        self.hits = 0
        self.misses = 0

    def clear(self):
        self.prepared = None
        self.regions.clear()

    def for_region(self, index):
        """Bounded slots contain only immutable 2D data, never selected entities."""
        from .regions import MAX_REGIONS
        if not 0 <= index < MAX_REGIONS:
            raise ValueError('Too many Profiles regions.')
        if index not in self.regions:
            self.regions[index] = GeometryCache()
        return self.regions[index]

    def resolve(self, region, settings, context=()):
        value = self.prepared
        if value is not None and (value.region, value.settings, value.context) == (region, settings, context):
            self.hits += 1
            return value.cells
        self.misses += 1
        cells = tuple(generate(region, settings))
        self.prepared = Prepared(region, settings, context, cells)
        return cells
