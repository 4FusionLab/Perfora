# SPDX-License-Identifier: GPL-3.0-only
"""Cached graphics preview; no persistent cell geometry or extrusion."""
from time import perf_counter

import adsk.core
import adsk.fusion

from . import model
from .geometry import generate, outline_coordinates


class Renderer:
    def __init__(self):
        self.graphics = None
        self.source_key = 0
        self.source = None
        self.region = None
        self.component = None
        self.frame = None
        self.settings = None
        self.cells = None
        self.coordinates = None
        self.coordinate_key = None
        self.drawn_key = None
        self.last_seconds = 0.0
        self.layout_builds = 0
        self.draws = 0
        self.original_body = None
        self.trimmed_body = None
        self.trim_margin = None
        self.clipped_layout = None

    def clear(self):
        if self.graphics and self.graphics.isValid:
            self.graphics.deleteMe()
        self.graphics = None
        self.drawn_key = None

    def reset(self):
        self.clear()
        self.source_key += 1
        self.source = None
        self.region = None
        self.settings = None
        self.cells = None
        self.coordinate_key = None
        self.coordinates = None
        self.original_body = None
        self.trimmed_body = None
        self.trim_margin = None
        self.clipped_layout = None

    def show(self, source, settings, config):
        started = perf_counter()
        source = model.native(source)
        if self.source is None or source != self.source:
            self.reset()
            # One empty sketch obtains Fusion's own plane frame. It is deleted
            # immediately; there are no persistent sketch entities in fast mode.
            sketch = model.new_source_sketch(source)
            try:
                self.region = model.get_region(source, sketch, config)
                # Use the same explicit coordinate conversion as final CAD.
                # Sketch.transform conventions differ from graphics transforms;
                # an inverse matrix can rotate/translate outlines off the face.
                origin = sketch.sketchToModelSpace(adsk.core.Point3D.create(0, 0, 0))
                x_point = sketch.sketchToModelSpace(adsk.core.Point3D.create(1, 0, 0))
                y_point = sketch.sketchToModelSpace(adsk.core.Point3D.create(0, 1, 0))
                self.frame = (tuple(origin.asArray()), tuple(origin.vectorTo(x_point).asArray()),
                              tuple(origin.vectorTo(y_point).asArray()))
                self.component = sketch.parentComponent
            finally:
                sketch.deleteMe()
            self.source = source
        elif isinstance(source, adsk.fusion.ConstructionPlane):
            # On an infinite plane the explicit boundary is part of the source.
            boundary_key = (config['boundary'], config['width'], config['height'])
            if getattr(self, 'boundary_key', None) != boundary_key:
                sketch = model.new_source_sketch(source)
                try:
                    self.region = model.get_region(source, sketch, config)
                finally:
                    sketch.deleteMe()
                self.settings = None
                self.original_body = None
                self.trimmed_body = None
                self.trim_margin = None
        self.boundary_key = (config['boundary'], config['width'], config['height'])
        if settings != self.settings:
            self.clipped_layout = None
            if settings.clip_boundary:
                from . import clipping
                if self.original_body is None or self.trim_margin != settings.margin:
                    sketch = model.new_source_sketch(source)
                    try:
                        self.original_body = clipping.source_body(source, sketch, config, self.region)
                        self.trimmed_body = clipping.inset_body(source, self.original_body, settings.margin)
                        self.trim_margin = settings.margin
                    finally:
                        sketch.deleteMe()
                self.clipped_layout = clipping.layout(self.original_body, self.trimmed_body, self.region, settings)
                self.cells = self.clipped_layout.cells
            else:
                self.cells = generate(self.region, settings)
            self.settings = settings
            self.coordinate_key = None
            self.layout_builds += 1
        coordinate_key = (self.source_key, settings, config['material'])
        if coordinate_key != self.coordinate_key:
            local = (self.clipped_layout.outlines(self.region, config['material'] == 'panel')
                     if self.clipped_layout else outline_coordinates(self.cells, self.region, config['material'] == 'panel'))
            origin, u, v = self.frame
            self.coordinates = []
            for i in range(0, len(local), 3):
                x, y = local[i], local[i + 1]
                self.coordinates.extend(origin[j] + x * u[j] + y * v[j] for j in range(3))
            self.coordinate_key = coordinate_key
        if not (self.graphics and self.graphics.isValid and self.drawn_key == coordinate_key):
            self.clear()
            group = self.component.customGraphicsGroups.add()
            self.graphics = group  # Owned even if a subsequent API call fails.
            try:
                group.isSelectable = False
                lines = group.addLines(adsk.fusion.CustomGraphicsCoordinates.create(self.coordinates), [], False)
                lines.isSelectable = False
                lines.depthPriority = 1
                lines.weight = 1.5
                lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(0, 170, 240, 255))
                self.drawn_key = coordinate_key
                self.draws += 1
            except Exception:
                self.clear()
                raise
        self.last_seconds = perf_counter() - started
        return len(self.cells)
