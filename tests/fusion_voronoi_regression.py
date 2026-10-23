# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy in Fusion. Uses one separate, unsaved disposable document."""
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
package = '_perfora_voronoi_test'
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
clipping = import_module(package + '.clipping')
spec = importlib.util.spec_from_file_location('_voronoi_fixture', root / 'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
app = adsk.core.Application.get()
original = app.activeDocument
doc = None
results = []
only_cases = globals().get('only_cases')
output = Path.home() / 'Library/Logs/Perfora/voronoi-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)


def save(running=None):
    output.write_text(json.dumps(dict(passed=bool(results) and all(r['passed'] for r in results),
                                     running=running, fusion=app.version, tests=results), indent=2), encoding='utf-8')


def case(name, action):
    if only_cases and name not in only_cases:
        return
    save(name)
    try:
        results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))
    save()


try:
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)

    def frame_cache_and_contours():
        comp = fixture.component(design, 'Voronoi frame and cache')
        plane_input = comp.constructionPlanes.createInput()
        plane_input.setByOffset(comp.yZConstructionPlane, adsk.core.ValueInput.createByString('27 mm'))
        plane = comp.constructionPlanes.add(plane_input)
        config = fixture.config(result='profiles')
        settings = geo.Settings(shape='voronoi', size=.7, gap=.12, margin=.1, grid_angle=.31)
        renderer = preview.Renderer()
        try:
            renderer.show(plane, settings, config)
            builds = renderer.layout_builds
            started = perf_counter()
            for _ in range(100):
                renderer.show(plane, settings, config)
            cached_seconds = perf_counter() - started
            assert renderer.layout_builds == builds
            for change in (dict(seed=17), dict(irregularity=0), dict(irregularity=1), dict(gap=.15),
                           dict(margin=.15), dict(offset_x=.23), dict(grid_angle=.62)):
                settings = replace(settings, **change)
                renderer.show(plane, settings, config)
                builds += 1
                assert renderer.layout_builds == builds, change
            cells = renderer.cells
            local = geo.outline_coordinates(cells, renderer.region)
            actual = renderer.graphics.item(0).coordinates.getCoordinate(0)
            actual.transformBy(renderer.graphics.transform)
            reference = model.new_source_sketch(plane)
            try:
                expected = reference.sketchToModelSpace(adsk.core.Point3D.create(*local[:3]))
                frame_error = actual.distanceTo(expected)
                assert frame_error < 1e-5, frame_error
            finally:
                reference.deleteMe()
        finally:
            renderer.reset()
        sketch, _, count = model.build(plane, settings, config)
        assert count == len(cells) == sketch.profiles.count
        def point_key(p):
            return tuple(round(v, 7) for v in p[:2])
        expected_edges = sorted(tuple(sorted((point_key(a), point_key(b))))
                                for c in cells for a, b in geo.edges(c.vertices))
        actual_edges = sorted(tuple(sorted((point_key(line.startSketchPoint.geometry.asArray()),
                                          point_key(line.endSketchPoint.geometry.asArray()))))
                              for line in sketch.sketchCurves.sketchLines)
        assert actual_edges == expected_edges, 'Preview contours differ from final sketch lines'
        return dict(cells=count, frame_error_cm=frame_error, hundred_cached_seconds=cached_seconds,
                    layout_builds=builds, matching_edges=len(actual_edges))
    case('frame_cache_and_exact_contours', frame_cache_and_contours)

    def clipped_corner_tangency():
        comp=fixture.component(design,'Rounded boundary junctions')
        settings=geo.Settings(shape='voronoi',size=1,gap=.12,margin=.1,
                              irregularity=0,offset_x=.3,corner_radius=.12,clip_boundary=True)
        config=fixture.config(result='profiles',width=2.6,height=2.6)
        renderer=preview.Renderer()
        try:
            renderer.show(comp.xYConstructionPlane,settings,config)
            loops=renderer.clipped_layout.partial_loops
            assert loops
            vertices=0
            for curves,outer in loops:
                if not outer:
                    continue
                body=clipping.sheet([curves])
                contour=clipping.loop_contour(body.faces.item(0).loops.item(0))
                for i,edge in enumerate(contour):
                    u,v=edge.tangent(True),contour[(i+1)%len(contour)].tangent()
                    assert u[0]*v[0]+u[1]*v[1]>1-1e-7, ('Sharp trimmed corner',edge.end,u,v)
                    vertices+=1
            return dict(tangent_junctions=vertices,partial_loops=len(loops))
        finally:
            renderer.reset()
    case('trimmed_corners_are_tangent',clipped_corner_tangency)

    def tiny_bevel_radius():
        comp=fixture.component(design,'Tiny bevel absorbed by fillet')
        sketch=comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        cell=geo.Cell((0,0),'voronoi',2,2,0,
                      polygon=((-1,-1),(.999,-1),(1,-.999),(1,1),(-1,1)),corner_radius=.2)
        sketch.isComputeDeferred=True
        try:
            model.add_cell(sketch,cell)
        finally:
            sketch.isComputeDeferred=False
        assert sketch.profiles.count==1
        arcs=sketch.sketchCurves.sketchArcs
        assert arcs.count==4, ('Short bevel was not absorbed',arcs.count)
        assert all(abs(arc.geometry.radius-.2)<1e-8 for arc in arcs)
        area=sketch.profiles.item(0).areaProperties().area
        assert abs(area-(4-(4-math.pi)*.2**2))<1e-7
        return dict(arcs=arcs.count,radius_cm=.2,area_cm2=area)
    case('tiny_bevel_keeps_requested_radius',tiny_bevel_radius)

    def annulus(corner_radius=0):
        comp = fixture.component(design, 'Voronoi annulus')
        source = comp.sketches.addWithoutEdges(comp.xZConstructionPlane)
        source.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), 1.5)
        source.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), .3)
        profile = next(p for p in source.profiles if p.profileLoops.count == 2)
        settings = geo.Settings(shape='voronoi', size=.65, gap=.12, margin=.1,
                                clip_boundary=True, grid_angle=.29, seed=47, corner_radius=corner_radius)
        config = fixture.config(result='profiles')
        renderer = preview.Renderer()
        try:
            count = renderer.show(profile, settings, config)
            assert renderer.clipped_layout.partial_loops
            if corner_radius:
                for curves,outer in renderer.clipped_layout.partial_loops:
                    if not outer:
                        continue
                    partial=clipping.sheet([curves])
                    contour=clipping.loop_contour(partial.faces.item(0).loops.item(0))
                    for i,edge in enumerate(contour):
                        u,v=edge.tangent(True),contour[(i+1)%len(contour)].tangent()
                        turn=math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1])
                        assert turn<1e-6, ('Sharp circular trim corner',edge.end,turn)
            expected_trim_area = math.pi * (1.4**2 - .4**2)
            assert abs(renderer.trimmed_body.area - expected_trim_area) < 1e-6
        finally:
            renderer.reset()
        sketch, _, final_count = model.build(profile, settings, config)
        assert final_count == count
        area = sum(p.areaProperties().area for p in model.selected_profiles(sketch, 'cells', True))
        for curve in sketch.sketchCurves:
            for p in model.strokes(curve.geometry.evaluator, lambda p: p):
                assert .4-2e-6 <= math.hypot(*p) <= 1.4+2e-6, p
        assert sketch.sketchCurves.sketchArcs.count > 0, 'Circular trim edges must remain exact arcs'
        _, feature, _ = model.build(profile, settings, fixture.config(material='panel'))
        volume = sum(b.volume for b in feature.bodies)
        assert abs(volume - (math.pi*(1.5**2-.3**2)-area)*.2) < 1e-6
        return dict(cells=count, holes_area_cm2=area, panel_volume_cm3=volume)
    case('annulus_inner_clearance_and_exact_arcs', annulus)
    case('rounded_annulus_inner_clearance_and_exact_arcs', lambda: annulus(.05))

    def rounded_profiles():
        comp = fixture.component(design, 'Rounded Voronoi profiles')
        settings = geo.Settings(shape='voronoi', size=.8, gap=.12, margin=.1,
                                irregularity=0, corner_radius=.05)
        config = fixture.config(result='profiles', width=3, height=2)
        renderer = preview.Renderer()
        try:
            count = renderer.show(comp.xYConstructionPlane, settings, config)
            cells = renderer.cells
            before = renderer.layout_builds
            renderer.show(comp.xYConstructionPlane, replace(settings, corner_radius=.1), config)
            assert renderer.layout_builds == before+1
            renderer.show(comp.xYConstructionPlane, settings, config)
            coordinates = tuple(renderer.coordinates)
            for _ in range(100):
                renderer.show(comp.xYConstructionPlane, settings, config)
            assert renderer.layout_builds == before+2 and tuple(renderer.coordinates) == coordinates
        finally:
            renderer.reset()
        sketch, _, built_count = model.build(comp.xYConstructionPlane, settings, config)
        assert count == built_count == sketch.profiles.count
        assert sketch.sketchCurves.sketchArcs.count == 4*count
        assert all(abs(arc.geometry.radius-.05) < 1e-8 for arc in sketch.sketchCurves.sketchArcs)
        area = sum(p.areaProperties().area for p in sketch.profiles)
        expected = count*((.8-.12)**2-(4-math.pi)*.05**2)
        assert abs(area-expected) < 1e-7, (area,expected)
        actual = sorted(tuple(round(v,7) for v in arc.geometry.center.asArray()[:2])
                        for arc in sketch.sketchCurves.sketchArcs)
        expected_centers = sorted(tuple(round(v,7) for v in edge.center)
                                  for cell in cells for edge in cell.contour if edge.center is not None)
        assert actual == expected_centers, 'CAD fillets differ from preview arc centers'
        _, feature, _ = model.build(comp.xYConstructionPlane, settings,
                                    fixture.config(width=3,height=2))
        volume = sum(b.volume for b in feature.bodies)
        assert abs(volume-area*.2) < 1e-7
        return dict(cells=count, arcs=sketch.sketchCurves.sketchArcs.count, area_cm2=area, volume_cm3=volume)
    case('rounded_profiles_area_volume_and_cache', rounded_profiles)

    for operation in ('cut','join','intersect','body','component'):
        def rounded_operation(operation=operation):
            comp = fixture.component(design, 'Rounded '+operation)
            body, face = fixture.plate(comp)
            settings = geo.Settings(shape='voronoi',size=.8,gap=.15,margin=.1,
                                    corner_radius=.05,clip_boundary=True)
            _, feature, count = model.build(face, settings, fixture.config(
                operation=operation,reverse=operation in ('cut','intersect'),bodies=[body]))
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            return dict(cells=count,bodies=feature.bodies.count)
        case('rounded_'+operation, rounded_operation)

    def concave():
        comp = fixture.component(design, 'Voronoi concave boundary')
        source = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        model.add_polygon(source, ((-2,-2),(2,-2),(2,2),(1,2),(1,-1),(-1,-1),(-1,2),(-2,2)), 'cell')
        settings = geo.Settings(shape='voronoi', size=.8, gap=.12, margin=.1, clip_boundary=True)
        sketch, _, count = model.build(source.profiles.item(0), settings, fixture.config(result='profiles'))
        assert count > 0 and sketch.profiles.count > 0
        return dict(cells=count, profiles=sketch.profiles.count)
    case('concave_boundary', concave)
finally:
    if doc:
        doc.close(False)
    if original and original.isValid:
        original.activate()
    save()
print('PERFORA_VORONOI', json.loads(output.read_text()))
