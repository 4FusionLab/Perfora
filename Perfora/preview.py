# SPDX-License-Identifier: GPL-3.0-only
"""Cached graphics preview; no persistent cell geometry or extrusion."""
from time import perf_counter

import adsk.core
import adsk.fusion

from . import model
from .geometry import outline_coordinates, placement_center
from .cache import GeometryCache


# Presentation only: never part of Settings or the prepared geometry cache.
PREVIEW_COLORS = [('magenta', 'Magenta'), ('cyan', 'Cyan'), ('gold', 'Gold'),
                  ('green', 'Green'), ('white', 'White'), ('black', 'Black')]
COLOR_RGB = {'gold': (255, 191, 0), 'cyan': (0, 170, 240),
             'magenta': (255, 70, 210), 'green': (100, 255, 100),
             'white': (255, 255, 255), 'black': (0, 0, 0)}


class Renderer:
    def __init__(self):
        self.graphics = None
        self.lines = None
        self.color_key = None
        self.source_key = 0
        self.source_revision = None
        self.geometry_cache = GeometryCache()
        self.path_cache = model.PathCache()
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
        self.inset_body = None
        self.trim_key = None
        self.clipped_layout = None
        self.surface_prepared = None
        self.multi_key = None
        self.multi_plans = None
        self.hidden_bodies = []
        self.exact_bodies = ()

    def clear(self):
        for body, visible in self.hidden_bodies:
            if body.isValid:
                body.isVisible = visible
        self.hidden_bodies = []
        self.exact_bodies = ()
        if self.graphics and self.graphics.isValid:
            self.graphics.deleteMe()
        self.graphics = None
        self.lines = None
        self.color_key = None
        self.drawn_key = None

    def show_edit_solid(self, custom, source, settings, config):
        """Exact temporary BRep preview; never edit the node being previewed."""
        from . import feature, multi_region, surface
        self.clear()
        frames = [f for f in custom.features if isinstance(f, adsk.fusion.Sketch)]
        selected = list(source) if isinstance(source, (tuple, list)) else [source]
        if len(selected) > 1:
            plans = multi_region.prepare(selected, settings, config, self.geometry_cache, frames)
            tool = surface.merge([multi_region.make_body(plan, config) for plan in plans])
            count = sum(len(plan.cells) for plan in plans)
        else:
            tool, count = feature.make_body(source, settings, config, frames[0],
                frames[1] if len(frames) > 1 else None, self.geometry_cache)
        manager = adsk.fusion.TemporaryBRepManager.get()
        bodies = []
        targets = [model.native(b) for b in config['bodies']]
        operations = dict(cut=adsk.fusion.BooleanTypes.DifferenceBooleanType,
            join=adsk.fusion.BooleanTypes.UnionBooleanType,
            intersect=adsk.fusion.BooleanTypes.IntersectionBooleanType)
        if config['operation'] in operations:
            for target in targets:
                body = manager.copy(target)
                if not manager.booleanOperation(body, manager.copy(tool), operations[config['operation']]):
                    raise ValueError('Unable to preview the Feature operation.')
                bodies.append(body)
        else:
            bodies.append(tool)
        try:
            self.graphics = custom.parentComponent.customGraphicsGroups.add()
            self.graphics.isSelectable = False
            for body in bodies:
                graphic = self.graphics.addBRepBody(body)
                graphic.isSelectable = False
            for target in targets:
                self.hidden_bodies.append((target, target.isVisible))
                target.isVisible = False
            self.exact_bodies = tuple(bodies)
            return count
        except Exception:
            self.clear()
            raise

    def reset(self):
        self.clear()
        self.source_key += 1
        self.source = None
        self.source_revision = None
        self.region = None
        self.component = None
        self.frame = None
        self.settings = None
        self.cells = None
        self.coordinate_key = None
        self.coordinates = None
        self.original_body = None
        self.inset_body = None
        self.trimmed_body = None
        self.trim_margin = None
        self.trim_key = None
        self.clipped_layout = None
        self.surface_prepared = None
        self.multi_key = None
        self.multi_plans = None
        self.geometry_cache.clear()
        self.path_cache = model.PathCache()

    def show(self, source, settings, config, color='magenta'):
        if isinstance(source, (tuple, list)):
            from . import multi_region
            selected, _ = multi_region.validate(source, config)
            if len(selected) > 1:
                return self.show_many(selected, settings, config, color)
            source = selected[0]
        if self.multi_key is not None:
            self.reset()
        from . import cylindrical
        if config.get('surface'):
            return self.show_surface(model.native(source), settings, config, color)
        if cylindrical.is_cylinder(model.native(source)):
            return self.show_cylinder(model.native(source), settings, config, color)
        started = perf_counter()
        rgb = COLOR_RGB[color]
        source = model.native(source)
        revision = model.source_revision(source)
        boundary_key = (config['boundary'], config['width'], config['height'])
        if (self.source is not None and (source != self.source or revision != self.source_revision
                or isinstance(source, adsk.fusion.ConstructionPlane)
                and boundary_key != self.boundary_key)):
            self.reset()
        if self.source is None:
            sketch = model.new_source_sketch(source)
            try:
                self.region = model.get_region(source, sketch, config)
                # Same explicit basis as final CAD, including moved/rotated planes.
                self.frame = model.sketch_frame(sketch)
                self.component = sketch.parentComponent
            finally:
                sketch.deleteMe()
            self.source = source
            self.source_revision = model.source_revision(source)
        self.boundary_key = boundary_key
        settings = model.layout_settings(settings, config, self.region, self.frame, self.component, self.path_cache)
        if settings.clip_boundary and self.original_body is not None and not self.original_body.isValid:
            self.original_body = self.inset_body = self.trimmed_body = None
            self.trim_key = self.trim_margin = None
            self.settings = None
            self.clear()
        if settings != self.settings:
            candidates = self.geometry_cache.resolve(self.region, settings, self.frame)
            clipped = None
            if settings.clip_boundary:
                from . import clipping
                if self.original_body is None:
                    sketch = model.new_source_sketch(source)
                    try:
                        self.original_body = clipping.source_body(source, sketch, config, self.region)
                    finally:
                        sketch.deleteMe()
                if self.inset_body is None or self.trim_margin != settings.margin:
                    inset = clipping.inset_body(source, self.original_body, settings.margin)
                    self.inset_body = inset
                    self.trim_margin = settings.margin
                    self.trim_key = None
                trim_key = (settings.margin, settings.spread_radius,
                            placement_center(self.region, settings) if settings.spread_radius > 0 else None)
                if self.trim_key != trim_key:
                    trimmed = clipping.apply_spread(self.inset_body, self.region, settings)
                    self.trimmed_body = trimmed
                    self.trim_key = trim_key
                clipped = clipping.layout(self.original_body, self.trimmed_body,
                                          self.region, settings, candidates)
                cells = clipped.cells
            else:
                cells = candidates
            # Publish the layout only after preparation succeeds. Native bodies
            # are owned by this renderer; only immutable cells enter the cache.
            self.clipped_layout = clipped
            self.cells = cells
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
                lines.weight = 3.0
                self.lines = lines
                self.drawn_key = coordinate_key
                self.draws += 1
            except Exception:
                self.clear()
                raise
        if self.color_key != rgb:
            try:
                self.lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(
                    adsk.core.Color.create(*rgb, 255))
                self.color_key = rgb
            except Exception:
                self.clear()
                raise
        self.last_seconds = perf_counter() - started
        return len(self.cells)

    def show_cylinder(self, source, settings, config, color):
        from . import cylindrical
        started = perf_counter()
        key = ('cylinder', source.entityToken, model.source_revision(source), settings,
               tuple(config[k] for k in ('cut_depth', 'cylinder_start', 'cylinder_sweep', 'axial_start', 'axial_length')))
        if key != self.coordinate_key:
            self.reset()
            self.frame, self.cells = cylindrical.prepare(source, settings, config)
            self.coordinates = cylindrical.coordinates(self.frame, settings, self.cells)
            self.component = model.source_component(source)
            self.source = source
            self.source_revision = model.source_revision(source)
            self.coordinate_key = key
            self.layout_builds += 1
        if not (self.graphics and self.graphics.isValid):
            self.graphics = self.component.customGraphicsGroups.add()
            try:
                self.graphics.isSelectable = False
                self.lines = self.graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(self.coordinates), [], False)
                self.lines.isSelectable = False
                self.lines.depthPriority = 1
                self.lines.weight = 3.
                self.draws += 1
            except Exception:
                self.clear()
                raise
        rgb = COLOR_RGB[color]
        if self.color_key != rgb:
            self.lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*rgb, 255))
            self.color_key = rgb
        self.last_seconds = perf_counter() - started
        return len(self.cells)

    def show_surface(self, source, settings, config, color):
        from . import surface
        started = perf_counter()
        normalized = surface.normalized(config, model.source_component(source))
        keys = ('_start','_distance1','_distance2','direction','reverse',*surface.ZONE_PARAMETERS)
        anchor = config.get('center_point')
        anchor = tuple(model.point_position(anchor, model.source_component(source)).asArray()) if anchor is not None else None
        key = ('surface',source.entityToken,model.source_revision(source),settings,
               tuple(normalized[k] for k in keys),anchor)
        if key != self.coordinate_key:
            self.reset()
            self.surface_prepared = surface.prepare(source,settings,config)
            self.cells = self.surface_prepared.sections
            self.coordinates = self.surface_prepared.coordinates
            self.component = model.source_component(source)
            self.source = source
            self.source_revision = model.source_revision(source)
            self.coordinate_key = key
            self.layout_builds += 1
        if not (self.graphics and self.graphics.isValid):
            self.graphics = self.component.customGraphicsGroups.add()
            try:
                self.graphics.isSelectable = False
                self.lines = self.graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(self.coordinates), [], False)
                self.lines.isSelectable = False
                self.lines.depthPriority = 1
                self.lines.weight = 3.
                self.draws += 1
            except Exception:
                self.clear()
                raise
        rgb = COLOR_RGB[color]
        if self.color_key != rgb:
            self.lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*rgb,255))
            self.color_key = rgb
        self.last_seconds = perf_counter()-started
        return len(self.cells)

    def show_many(self, selected, settings, config, color):
        from . import multi_region, regions
        started = perf_counter()
        selected, _ = multi_region.validate(selected, config)
        component = model.source_component(selected[0])
        center = config.get('center_point')
        center_key = tuple(model.point_position(center, component).asArray()) if center is not None else None
        key = (tuple(selected), tuple(model.source_revision(s) for s in selected), settings, center_key,
               config['result'], config['operation'], tuple(model.native(b) for b in config['bodies']),
               tuple((k, config.get(k)) for k in ('surface','direction','reverse','start','distance1','distance2','cylinder_start','cylinder_sweep','axial_start','axial_length')) if config.get('surface') else ())
        if self.source is not None:
            self.reset()
        if key != self.multi_key or (self.multi_plans and any(not p.original.isValid for p in self.multi_plans)):
            self.clear()
            # Drop a failed/old plan before preparing; stale contours must never survive.
            previous = self.multi_plans
            self.multi_key = self.multi_plans = None
            self.multi_plans = multi_region.prepare(selected, settings, config, self.geometry_cache, previous=previous)
            self.multi_key = key
            self.layout_builds += 1
        draw_key = (key, config['material'])
        if self.coordinate_key != draw_key:
            coordinates = []
            for plan in self.multi_plans:
                if plan.prepared is not None:
                    coordinates.extend(plan.prepared.coordinates)
                    continue
                local = (plan.clipped.outlines(plan.region, config['material'] == 'panel') if plan.clipped else
                         outline_coordinates(plan.cells, plan.region, config['material'] == 'panel'))
                for i in range(0, len(local), 3):
                    coordinates.extend(regions.to_world(plan.frame, local[i:i+3]))
            self.coordinates = coordinates
            self.coordinate_key = draw_key
        if not (self.graphics and self.graphics.isValid and self.drawn_key == draw_key):
            self.clear()
            try:
                self.graphics = component.customGraphicsGroups.add()
                self.graphics.isSelectable = False
                self.lines = self.graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(self.coordinates), [], False)
                self.lines.isSelectable = False
                self.lines.depthPriority, self.lines.weight = 1, 3.
                self.drawn_key = draw_key
                self.draws += 1
            except Exception:
                self.clear()
                raise
        rgb = COLOR_RGB[color]
        if self.color_key != rgb:
            try:
                self.lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*rgb, 255))
                self.color_key = rgb
            except Exception:
                self.clear()
                raise
        self.cells = tuple(c for p in self.multi_plans for c in p.cells)
        self.last_seconds = perf_counter()-started
        return len(self.cells)
