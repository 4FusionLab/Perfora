# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy inside Fusion. Closes its separate unsaved document."""
import importlib.util
from importlib import import_module
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
package = '_perfora_circular_test'
for key in tuple(sys.modules):
    if key == package or key.startswith(package + '.'):
        del sys.modules[key]
spec = importlib.util.spec_from_file_location(package, root / 'Perfora/__init__.py',
                                            submodule_search_locations=[str(root / 'Perfora')])
module = importlib.util.module_from_spec(spec)
sys.modules[package] = module
spec.loader.exec_module(module)
model = import_module(package + '.model')
geo = import_module(package + '.geometry')
preview = import_module(package + '.preview')
spec = importlib.util.spec_from_file_location('_circular_fixture', root / 'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
app = adsk.core.Application.get()
original = app.activeDocument
doc = None
results = []
output = Path.home() / 'Library/Logs/Perfora/circular-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)


def case(name, action):
    output.write_text(json.dumps(dict(running=name, tests=results)), encoding='utf-8')
    try:
        results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))


try:
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)

    def exact_edge_offset():
        comp=fixture.component(design,'Exact Edge Offset')
        settings=geo.Settings(layout='circular',size=.5,gap=.15,margin=.3)
        config=fixture.config(result='profiles',width=5.,height=5.)
        renderer=preview.Renderer()
        key=lambda c:(round(c.center[0],7),round(c.center[1],7))
        poles={(-1.95,0.),(1.95,0.)}
        try:
            count=renderer.show(comp.xYConstructionPlane,settings,config)
            whole={key(c) for c in renderer.cells}
            assert poles<=whole,'Complete tangent holes were rejected without Trim to Boundary'
            renderer.reset()
            renderer.show(comp.xYConstructionPlane,replace(settings,clip_boundary=True),config)
            assert poles<={key(c) for c in renderer.clipped_layout.whole},'Exact clipping changed a whole tangent hole'
        finally:renderer.reset()
        for trim in (False,True):
            sketch,_,built=model.build(comp.xYConstructionPlane,replace(settings,clip_boundary=trim),config)
            circles={(round(c.centerSketchPoint.geometry.x,7),round(c.centerSketchPoint.geometry.y,7)):
                c.radius for c in sketch.sketchCurves.sketchCircles}
            assert poles<=circles.keys()
            assert all(abs(circles[p]-.25)<1e-9 for p in poles)
            if not trim:assert built==count==sketch.profiles.count
        # A real intrusion into the inset must still become a partial contour.
        shifted=replace(settings,offset_x=-1e-4,clip_boundary=True)
        try:
            renderer.show(comp.xYConstructionPlane,shifted,config)
            assert (-1.9501,0.) not in {key(c) for c in renderer.clipped_layout.whole}
            assert renderer.clipped_layout.partial_loops
        finally:renderer.reset()
        return dict(whole_holes=count,edge_offset_mm=3.,tangent_holes_preserved=True,real_crossing_still_trimmed=True)
    case('exact_edge_offset_retains_whole_cells',exact_edge_offset)

    for shape in geo.SHAPE_IDS:
        if shape == 'voronoi':
            continue

        def profiles_and_volume(shape=shape):
            comp = fixture.component(design, 'Circular ' + shape)
            settings = geo.Settings(layout='circular', shape=shape, size=.45, slot_length=.8,
                                    gap=.14, margin=.12, grid_angle=.29, shape_angle=.37,
                                    radial_orientation=True, start_radius=.3)
            config = fixture.config(result='profiles')
            renderer = preview.Renderer()
            try:
                count = renderer.show(comp.xYConstructionPlane, settings, config)
                cells = list(renderer.cells)
                assert comp.sketches.count == 0
            finally:
                renderer.reset()
            sketch, _, actual_count = model.build(comp.xYConstructionPlane, settings, config)
            assert count == actual_count == sketch.profiles.count
            area = sum(p.areaProperties().area for p in sketch.profiles)
            if shape == 'circle':
                assert abs(area - count * math.pi * settings.size ** 2 / 4) < 1e-7
                centers = [c.geometry.center for c in sketch.sketchCurves.sketchCircles]
                assert all(any(math.hypot(p.x - c.center[0], p.y - c.center[1]) < 1e-7 for p in centers) for c in cells)
            elif shape in geo.POLYGON_SHAPES:
                actual = {(round(c.startSketchPoint.geometry.x, 6), round(c.startSketchPoint.geometry.y, 6))
                          for c in sketch.sketchCurves.sketchLines}
                expected = {(round(x, 6), round(y, 6)) for c in cells for x, y in c.vertices}
                assert actual == expected, 'Preview and sketch vertices differ'
            _, feature, built = model.build(comp.xYConstructionPlane, settings, fixture.config())
            assert built == count and feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            volume = sum(b.volume for b in feature.bodies)
            assert abs(volume - area * .2) < 1e-6
            return dict(cells=count, area_cm2=area, volume_cm3=volume)
        case('profiles_volume_' + shape, profiles_and_volume)

    def frame_and_cache():
        comp = fixture.component(design, 'Circular frame')
        data = comp.constructionPlanes.createInput()
        data.setByOffset(comp.yZConstructionPlane, adsk.core.ValueInput.createByString('27 mm'))
        plane = comp.constructionPlanes.add(data)
        config = fixture.config(result='profiles')
        settings = geo.Settings(shape='slot', size=.35, slot_length=.7, layout='circular', radial_orientation=True)
        renderer = preview.Renderer()
        try:
            renderer.show(plane, settings, config)
            builds = renderer.layout_builds
            for _ in range(100):
                renderer.show(plane, settings, config)
            assert renderer.layout_builds == builds
            for change in (dict(start_radius=.8), dict(radial_orientation=False), dict(offset_x=.21),
                           dict(offset_y=-.13), dict(grid_angle=.61), dict(shape_angle=.31),
                           dict(layout='grid'), dict(layout='circular')):
                settings = replace(settings, **change)
                renderer.show(plane, settings, config)
                builds += 1
                assert renderer.layout_builds == builds, change
            local = geo.outline_coordinates(renderer.cells, renderer.region)
            actual = renderer.graphics.item(0).coordinates.getCoordinate(0)
            actual.transformBy(renderer.graphics.transform)
            reference = model.new_source_sketch(plane)
            try:
                expected = reference.sketchToModelSpace(adsk.core.Point3D.create(*local[:3]))
                error = actual.distanceTo(expected)
                assert error < 1e-5
            finally:
                reference.deleteMe()
        finally:
            renderer.reset()
        return dict(cache_builds=builds, frame_error_cm=error)
    case('frame_cache', frame_and_cache)

    def annulus_clipping():
        comp = fixture.component(design, 'Circular annulus')
        source = comp.sketches.addWithoutEdges(comp.xZConstructionPlane)
        source.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), 2)
        source.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), .45)
        profile = next(p for p in source.profiles if p.profileLoops.count == 2)
        settings = geo.Settings(layout='circular', shape='slot', size=.4, slot_length=.8,
                                gap=.13, margin=.17, clip_boundary=True, radial_orientation=True,
                                shape_angle=math.pi / 2, offset_x=.19, start_radius=.5)
        renderer = preview.Renderer()
        config = fixture.config(result='profiles')
        try:
            count = renderer.show(profile, settings, config)
            assert renderer.clipped_layout.partial_loops
            trim_area = renderer.trimmed_body.area
            assert abs(trim_area - math.pi * (1.83 ** 2 - .62 ** 2)) < 1e-6
        finally:
            renderer.reset()
        sketch, _, built = model.build(profile, settings, config)
        assert built == count
        area = sum(p.areaProperties().area for p in model.selected_profiles(sketch, 'cells', True))
        for curve in sketch.sketchCurves:
            for p in model.strokes(curve.geometry.evaluator, lambda p: p):
                assert .62 - 2e-6 <= math.hypot(*p) <= 1.83 + 2e-6, p
        _, feature, _ = model.build(profile, settings, fixture.config(material='panel'))
        assert abs(sum(b.volume for b in feature.bodies) - (math.pi * (4 - .45 ** 2) - area) * .2) < 1e-5
        return dict(cells=count, trim_area_cm2=trim_area)
    case('annulus_clipping_panel', annulus_clipping)

    for operation in ('cut', 'join', 'intersect', 'body', 'component'):
        def native_operation(operation=operation):
            comp = fixture.component(design, 'Circular ' + operation)
            body, face = fixture.plate(comp)
            settings = geo.Settings(layout='circular', shape='slot', size=.4, slot_length=.8,
                                    gap=.12, margin=.15, radial_orientation=True, clip_boundary=True)
            _, feature, count = model.build(face, settings, fixture.config(operation=operation,
                reverse=operation in ('cut', 'intersect'), bodies=[body]))
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            return dict(cells=count, bodies=feature.bodies.count)
        case('operation_' + operation, native_operation)
finally:
    if doc:
        doc.close(False)
    if original and original.isValid:
        original.activate()
    report = dict(passed=bool(results) and all(r['passed'] for r in results), fusion=app.version, tests=results)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
print('PERFORA_CIRCULAR', report)
