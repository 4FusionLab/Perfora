# SPDX-License-Identifier: GPL-3.0-only
"""Live point anchors and tangent rings; one disposable document, registered add-in."""
from dataclasses import replace
import json
import math
from pathlib import Path
import runpy
import sys
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
entry = globals().get('entry') or next(m for m in tuple(sys.modules.values())
    if str(getattr(m, '__file__', '')) == str(root / 'Perfora/Perfora.py'))
model = entry.model
geo = sys.modules[entry.Settings.__module__]
preview = sys.modules[entry.Renderer.__module__]
fixture = runpy.run_path(str(root / 'PerforaSmokeTest/PerforaSmokeTest.py'))
app = adsk.core.Application.get()
original = app.activeDocument
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
results = []
output = Path.home() / 'Library/Logs/Perfora/center-regression.json'


def case(name, action):
    try:
        results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))


def circle_center(sketch, expected):
    points = [c.geometry.center for c in sketch.sketchCurves.sketchCircles]
    assert min(p.distanceTo(model.point(expected)) for p in points) < 1e-7


try:
    design = adsk.fusion.Design.cast(app.activeProduct)
    comp = design.rootComponent
    sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
    anchor = sketch.sketchPoints.add(adsk.core.Point3D.create(.35, -.2, 0))
    other = sketch.sketchPoints.add(adsk.core.Point3D.create(-.4, .3, 0))
    config = fixture['config'](result='profiles', center_point=anchor)
    settings = geo.Settings(layout='circular', size=.3, gap=.15, margin=.1, offset_x=.12, offset_y=-.08)

    def anchor_cache_and_sketch():
        renderer = preview.Renderer()
        try:
            count = renderer.show(comp.xYConstructionPlane, settings, config)
            assert any(geo.dist(c.center, (.47, -.28)) < 1e-8 for c in renderer.cells)
            builds = renderer.layout_builds
            for _ in range(100):
                renderer.show(comp.xYConstructionPlane, settings, config)
            assert renderer.layout_builds == builds
            cfg = dict(config, center_point=other)
            renderer.show(comp.xYConstructionPlane, settings, cfg)
            assert renderer.layout_builds == builds + 1
            assert any(geo.dist(c.center, (-.28, .22)) < 1e-8 for c in renderer.cells)
            cfg['center_point'] = None
            renderer.show(comp.xYConstructionPlane, settings, cfg)
            assert any(geo.dist(c.center, (.12, -.08)) < 1e-8 for c in renderer.cells)
            assert renderer.layout_builds == builds + 2
        finally:
            renderer.reset()
        built, _, actual = model.build(comp.xYConstructionPlane, settings, config)
        assert actual == count
        circle_center(built, (.47, -.28))
        return dict(cells=count, cache_builds=builds + 2)
    case('anchor_cache_sketch_clear', anchor_cache_and_sketch)

    def rotated_plane_projection():
        data = comp.constructionPlanes.createInput()
        data.setByOffset(comp.yZConstructionPlane, model.value('27 mm'))
        plane = comp.constructionPlanes.add(data)
        reference = model.new_source_sketch(plane)
        try:
            p = reference.sketchToModelSpace(model.point((.3, -.25)))
            # Pick a point 7 mm off the Profiles plane: orthogonal projection.
            p.x += .7
            xy = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
            picked = xy.sketchPoints.add(p)
            cfg = dict(config, center_point=picked)
            built, _, count = model.build(plane, replace(settings, offset_x=0, offset_y=0), cfg)
            circle_center(built, (.3, -.25))
            world = built.sketchToModelSpace(model.point((.3, -.25)))
            assert abs(world.x - 2.7) < 1e-7
            return dict(cells=count, projected_center=world.asArray())
        finally:
            reference.deleteMe()
    case('translated_rotated_projection', rotated_plane_projection)

    def vertex_and_construction_point():
        child = fixture['component'](design, 'Point Types')
        body, face = fixture['plate'](child)
        vertex = body.vertices.item(0)
        cp = child.originConstructionPoint
        for point in (vertex, cp):
            cfg = fixture['config'](result='profiles', center_point=point)
            renderer = preview.Renderer()
            try:
                count = renderer.show(face, settings, cfg)
                built, _, actual = model.build(face, settings, cfg)
                assert actual == count and count > 0
            finally:
                renderer.reset()
        return dict(types=2)
    case('vertex_construction_point', vertex_and_construction_point)

    def assembly_coordinates():
        transform = adsk.core.Matrix3D.create()
        transform.setToRotation(.43, adsk.core.Vector3D.create(0, 0, 1), adsk.core.Point3D.create())
        transform.translation = adsk.core.Vector3D.create(.3, -.2, .4)
        occurrence = comp.occurrences.addNewComponent(transform)
        child = occurrence.component
        source_sketch = child.sketches.addWithoutEdges(child.xYConstructionPlane)
        point = source_sketch.sketchPoints.add(model.point((.2, -.15)))
        proxy = point.createForAssemblyContext(occurrence)
        expected = model.point((.2, -.15))
        expected.transformBy(transform)
        actual = model.point_position(proxy, comp)
        assert expected.distanceTo(actual) < 1e-7, (expected.asArray(), actual.asArray())
        assert model.point_position(proxy, child).distanceTo(model.point((.2, -.15))) < 1e-7
        root_point = sketch.sketchPoints.add(expected)
        assert model.point_position(root_point, child).distanceTo(model.point((.2, -.15))) < 1e-7
        renderer = preview.Renderer()
        try:
            cfg = dict(config, center_point=proxy)
            renderer.show(comp.xYConstructionPlane, settings, cfg)
            target = (expected.x + settings.offset_x, expected.y + settings.offset_y)
            assert any(geo.dist(c.center, target) < 1e-7 for c in renderer.cells)
        finally:
            renderer.reset()
        return dict(root_center=actual.asArray())
    case('assembly_point_coordinates', assembly_coordinates)

    def tangent_trim_extrude():
        cfg = fixture['config'](center_point=anchor, material='panel')
        s = replace(settings, shape='slot', slot_length=.65, size=.25,
                    start_radius=.5, tangential_orientation=True, clip_boundary=True)
        renderer = preview.Renderer()
        try:
            count = renderer.show(comp.xYConstructionPlane, s, cfg)
            cells = list(renderer.cells)
            for cell in cells:
                x,y=cell.center[0]-.47,cell.center[1]+.28
                assert abs(math.remainder(cell.angle-math.atan2(y,x)-math.pi/2,math.tau)) < 1e-8
            built, _, actual = model.build(comp.xYConstructionPlane, s, dict(cfg, result='profiles'))
            area = sum(p.areaProperties().area for p in model.selected_profiles(built, 'panel', True))
            _, extrude, final = model.build(comp.xYConstructionPlane, s, cfg)
            assert count == actual == final
            assert abs(sum(b.volume for b in extrude.bodies)-area*.2) < 1e-6
        finally:
            renderer.reset()
        return dict(cells=count, area_cm2=area)
    case('tangential_trim_preview_extrude', tangent_trim_extrude)

    def global_spread():
        details = []
        for name, shape, layout, staggered in (('Staggered', 'circle', 'grid', True),
                ('Rectangular', 'slot', 'grid', False), ('Circular', 'slot', 'circular', False),
                ('Voronoi', 'voronoi', 'grid', False)):
            for trim in (False, True):
                s = geo.Settings(shape=shape, layout=layout, staggered=staggered,
                    size=.25, slot_length=.5, gap=.12, margin=.1, grid_angle=.37,
                    offset_x=.12, offset_y=-.08, spread_radius=1.1, clip_boundary=trim,
                    tangential_orientation=layout == 'circular')
                cfg = dict(config, result='profiles')
                renderer = preview.Renderer()
                try:
                    count = renderer.show(comp.xYConstructionPlane, s, cfg)
                    resolved = renderer.settings
                    center = geo.placement_center(renderer.region, resolved)
                    if trim:
                        assert abs(renderer.trimmed_body.area - math.pi) < 1e-6
                    built, _, actual = model.build(comp.xYConstructionPlane, s, cfg)
                    assert count == actual and count > 0
                    for curve in built.sketchCurves:
                        for pt in model.strokes(curve.geometry.evaluator, lambda p: p):
                            assert geo.dist(pt, center) <= 1.000003, (name, trim, pt, center)
                    old = renderer.layout_builds
                    renderer.show(comp.xYConstructionPlane, replace(s, spread_radius=.85), cfg)
                    assert renderer.layout_builds == old + 1
                    if trim:
                        assert abs(renderer.trimmed_body.area - math.pi*.75**2) < 1e-6
                    details.append(dict(distribution=name, trim=trim, cells=count))
                finally:
                    renderer.reset()
        return details
    case('global_origin_spread_all_distributions', global_spread)

    if hasattr(entry, 'parametric'):
        def feature_dependency():
            f = entry.parametric
            child = fixture['component'](design, 'Center Feature')
            upstream = child.sketches.addWithoutEdges(child.xYConstructionPlane)
            picked = upstream.sketchPoints.add(model.point((.2, -.1)))
            replacement = upstream.sketchPoints.add(model.point((-.35, .2)))
            dimension = upstream.sketchDimensions.addDistanceDimension(upstream.originPoint, picked,
                adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation, model.point((.2, .3)))
            cfg = fixture['config'](result='feature', material='panel', center_point=picked)
            s = replace(settings, shape='slot', size=.25, slot_length=.65,
                        tangential_orientation=True, start_radius=.45, clip_boundary=True, spread_radius=1.2)
            _, custom, count = f.build(child.xYConstructionPlane, s, cfg)
            assert f.center_entity(custom) is not None
            assert custom.parameters.itemById('spread_radius')
            before = sum(b.volume for b in child.bRepBodies)
            centroid_before = child.bRepBodies.item(0).physicalProperties.centerOfMass
            dimension.parameter.expression = '6.5 mm'
            # Dependency must trigger recompute naturally; no explicit computeAll.
            after = sum(b.volume for b in child.bRepBodies)
            centroid_after = child.bRepBodies.item(0).physicalProperties.centerOfMass
            assert (abs(after-before)>1e-7 or centroid_before.distanceTo(centroid_after)>1e-7), (before, after)
            assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
            custom.parameters.itemById('spread_radius').expression = '5 mm'
            assert abs(f.read(custom)[1].spread_radius-.5) < 1e-9
            assert abs(sum(b.volume for b in child.bRepBodies)-after)>1e-7
            source, read, cfg = f.read(custom)
            assert read.tangential_orientation and not read.radial_orientation
            cfg['center_point'] = replacement
            custom.timelineObject.rollTo(True)
            f.update(custom, read, cfg)
            custom.timelineObject.rollTo(False)
            assert model.native(f.center_entity(custom)) == replacement
            cfg['center_point'] = None
            custom.timelineObject.rollTo(True)
            f.update(custom, read, cfg)
            custom.timelineObject.rollTo(False)
            assert custom.dependencies.itemById('center_point') is None
            assert f.read(custom)[2]['center_point'] is None
            # Add a dependency when editing an existing automatic-center node.
            cfg['center_point'] = picked
            custom.timelineObject.rollTo(True)
            f.update(custom, read, cfg)
            custom.timelineObject.rollTo(False)
            assert model.native(f.center_entity(custom)) == picked
            assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
            return dict(cells=count, before=before, after=after, centroid_shift=centroid_before.distanceTo(centroid_after))
        case('feature_dependency_recompute_replace_clear_add', feature_dependency)
finally:
    doc.close(False)
    if original and original.isValid:
        original.activate()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(passed=bool(results) and all(r['passed'] for r in results), fusion=app.version,
                  addon=entry.__file__, tests=results)
    output.write_text(json.dumps(report, indent=2))
print('PERFORA_CENTER_REGRESSION', report)
