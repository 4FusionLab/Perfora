# SPDX-License-Identifier: GPL-3.0-only
"""PREPARED, NOT EXECUTED. Run explicitly inside the agreed Fusion test session.

Requires the registered add-in from this checkout. Creates/closes one separate
unsaved document; never saves the user's document. See docs/CURVE_LAYOUT.md for
real OK/Cancel, Edit Feature, Undo/Redo, missing-reference and reopen acceptance.
"""
from dataclasses import replace
import importlib.util
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
addon_path = Path(globals().get('addon_path', root / 'Perfora')).resolve()
entry = next((m for m in tuple(sys.modules.values())
              if str(getattr(m, '__file__', '')) == str(addon_path / 'Perfora.py')), None)
assert entry is not None and 'path' in dict(entry.LAYOUTS), 'Run the registered Along Path add-in from this checkout first'
model, feature = entry.model, entry.parametric
geo = sys.modules[entry.Settings.__module__]
preview = sys.modules[entry.Renderer.__module__]
spec = importlib.util.spec_from_file_location('_perfora_curve_fixture', root / 'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
app = adsk.core.Application.get()
original = app.activeDocument
doc = None
results = []
output_root = Path.home() / ('Library/Logs/Perfora' if sys.platform == 'darwin' else 'Perfora-test-results')
output_root.mkdir(parents=True, exist_ok=True)
output = output_root / 'curve-regression.json'
only_cases = globals().get('only_cases')


def save(stage):
    output.write_text(json.dumps(dict(stage=stage, fusion=app.version, addon=str(addon_path),
        passed=bool(results) and all(r['passed'] for r in results), tests=results), indent=2), encoding='utf-8')


def case(name, action):
    if only_cases and name not in only_cases:
        return
    save(name)
    started = perf_counter()
    try:
        detail = action()
        results.append(dict(name=name, passed=True, seconds=perf_counter()-started, detail=detail))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))
    save(name + ' complete')


def path_on(comp, kind, plane=None):
    sketch = comp.sketches.addWithoutEdges(plane or comp.xYConstructionPlane)
    sketch.name = 'Path ' + kind
    curves = sketch.sketchCurves
    if kind == 'line':
        curve = curves.sketchLines.addByTwoPoints(model.point((-1.6, 0)), model.point((1.6, 0)))
    elif kind == 'arc':
        curve = curves.sketchArcs.addByThreePoints(model.point((-1.2, 0)), model.point((0, 1.2)), model.point((1.2, 0)))
    elif kind == 'circle':
        curve = curves.sketchCircles.addByCenterRadius(model.point((0, 0)), 1.2)
    else:
        points = adsk.core.ObjectCollection.create()
        for p in ((-1.6, -.1), (-1.3, .25), (-.2, -.15), (.1, .1), (1.6, 0)):
            points.add(model.point(p))
        curve = curves.sketchFittedSplines.add(points)
    curve.isConstruction = True
    return sketch, curve


def healthy(item):
    assert item.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, item.errorOrWarningMessage


try:
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    for kind in ('line', 'arc', 'spline', 'circle'):
        for shape in geo.SHAPE_IDS:
            if shape == 'voronoi':
                continue

            def preview_profiles_extrude(kind=kind, shape=shape):
                comp = fixture.component(design, 'Curve ' + kind + ' ' + shape)
                _, path = path_on(comp, kind)
                settings = geo.Settings(layout='path', shape=shape, size=.22, slot_length=.4,
                    arm_width=.07, gap=.06, margin=.05, path_spacing=math.tau*1.2/12 if kind == 'circle' else .7,
                    path_orientation='tangent', shape_angle=.19)
                cfg = fixture.config(result='profiles', path=path)
                renderer = preview.Renderer()
                try:
                    count = renderer.show(comp.xYConstructionPlane, settings, cfg)
                    cells = tuple(renderer.cells)
                    builds = renderer.layout_builds
                    sampling = renderer.path_cache.builds
                    for _ in range(5):
                        renderer.show(comp.xYConstructionPlane, settings, dict(cfg, distance1='5 mm'), color='cyan')
                    assert renderer.layout_builds == builds and renderer.path_cache.builds == sampling
                    assert comp.sketches.count == 1, 'Fast Preview left a persistent sketch'
                finally:
                    renderer.reset()
                sketch, _, actual = model.build(comp.xYConstructionPlane, settings, cfg)
                assert count == actual == sketch.profiles.count
                area = sum(p.areaProperties().area for p in sketch.profiles)
                if shape == 'circle':
                    centers = [c.geometry.center for c in sketch.sketchCurves.sketchCircles]
                    assert all(any(math.hypot(p.x-c.center[0], p.y-c.center[1]) < 1e-6 for p in centers) for c in cells)
                    assert abs(area-count*math.pi*settings.size**2/4) < 1e-7
                elif shape in geo.POLYGON_SHAPES:
                    expected = {(round(x,6),round(y,6)) for c in cells for x,y in c.vertices}
                    actual = {(round(c.startSketchPoint.geometry.x,6),round(c.startSketchPoint.geometry.y,6))
                              for c in sketch.sketchCurves.sketchLines}
                    assert expected == actual
                _, extrusion, count2 = model.build(comp.xYConstructionPlane, settings, fixture.config(path=path))
                healthy(extrusion)
                volume = sum(b.volume for b in extrusion.bodies)
                assert count2 == count and abs(volume-area*.2) < 1e-6
                if kind == 'circle':
                    assert count == 12
                return dict(cells=count, area_cm2=area, volume_cm3=volume, sampling_builds=sampling)
            case('profiles_' + kind + '_' + shape, preview_profiles_extrude)

    def arc_length_and_reverse():
        comp = fixture.component(design, 'Spline lengths')
        _, path = path_on(comp, 'spline')
        evaluator = path.geometry.evaluator
        settings = geo.Settings(layout='path', size=.2, gap=.05, path_spacing=.5,
            path_start=.1, path_end=.2, path_position=.15, path_orientation='tangent')
        frame_sketch = model.new_source_sketch(comp.xYConstructionPlane)
        try:
            frame = model.sketch_frame(frame_sketch)
            a, b = evaluator.getParameterExtents()[1:]
            length = evaluator.getLengthAtParameter(a,b)[1]
            for reverse in (False, True):
                samples = model.path_samples(path, replace(settings, path_reverse=reverse), frame, comp)
                for i,(x,y,angle) in enumerate(samples):
                    ok, t = evaluator.getParameterAtPoint(model.point((x,y)))
                    assert ok
                    actual = evaluator.getLengthAtParameter(a,t)[1]
                    distance = .25+i*.5
                    assert abs(actual-(length-distance if reverse else distance)) < 1e-6
                    tangent = evaluator.getFirstDerivative(t)[1]
                    expected = math.atan2(tangent.y,tangent.x)+(math.pi if reverse else 0)
                    assert abs(math.remainder(angle-expected,math.tau)) < 1e-6
            return dict(length_cm=length, samples=len(samples))
        finally:
            frame_sketch.deleteMe()
    case('spline_arc_length_reverse_offsets', arc_length_and_reverse)

    def moved_plane_and_path_cache():
        comp = fixture.component(design, 'Moved path')
        plane_input = comp.constructionPlanes.createInput()
        plane_input.setByOffset(comp.yZConstructionPlane, model.value('27 mm'))
        plane = comp.constructionPlanes.add(plane_input)
        _, path = path_on(comp, 'line', plane)
        settings = geo.Settings(layout='path', shape='hexagon', size=.3, gap=.1, margin=.1, path_spacing=.7)
        cfg = fixture.config(path=path, result='profiles')
        renderer = preview.Renderer()
        try:
            count = renderer.show(plane,settings,cfg)
            sample_builds = renderer.path_cache.builds
            renderer.show(plane,replace(settings,shape_angle=.31),cfg)
            assert renderer.path_cache.builds == sample_builds
            renderer.show(plane,replace(settings,path_position=.1),cfg)
            assert renderer.path_cache.builds == sample_builds+1
            first = renderer.graphics.item(0).coordinates.getCoordinate(0)
            first.transformBy(renderer.graphics.transform)
            assert abs(first.x-2.7) < 1e-6
            path.endSketchPoint.move(adsk.core.Vector3D.create(-.3,0,0))
            renderer.show(plane,replace(settings,path_position=.1),cfg)
            assert renderer.path_cache.builds == sample_builds+2
            return dict(cells=count,sampling_builds=renderer.path_cache.builds)
        finally:
            renderer.reset()
    case('moved_plane_path_edit_cache', moved_plane_and_path_cache)

    def clipping_void_panel():
        comp = fixture.component(design, 'Path annulus')
        boundary = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        for radius in (2,.45):
            boundary.sketchCurves.sketchCircles.addByCenterRadius(model.point((0,0)),radius)
        source = next(p for p in boundary.profiles if p.profileLoops.count == 2)
        _, path = path_on(comp,'line')
        # Extend beyond the annulus to exercise partial outer and inner holes.
        path.startSketchPoint.move(adsk.core.Vector3D.create(-.5,0,0))
        path.endSketchPoint.move(adsk.core.Vector3D.create(.5,0,0))
        settings = geo.Settings(layout='path',size=.4,gap=.1,margin=.12,clip_boundary=True,path_spacing=.6,path_start=.2)
        cfg = fixture.config(path=path,result='profiles')
        renderer = preview.Renderer()
        try:
            count = renderer.show(source,settings,cfg)
            assert renderer.clipped_layout.partial_loops
            sketch,_,built = model.build(source,settings,cfg)
            assert built == count
            area = sum(p.areaProperties().area for p in model.selected_profiles(sketch,'cells',True))
        finally:
            renderer.reset()
        _,extrusion,built = model.build(source,settings,fixture.config(path=path,material='panel'))
        healthy(extrusion)
        expected = (math.pi*(4-.45**2)-area)*.2
        assert abs(sum(b.volume for b in extrusion.bodies)-expected) < 1e-5
        return dict(cells=built,hole_area_cm2=area)
    case('annulus_exact_trim_edge_offset_panel', clipping_void_panel)

    for operation in ('join','cut','intersect','body','component'):
        def native_operation(operation=operation):
            comp = fixture.component(design,'Path '+operation)
            body,face = fixture.plate(comp)
            _,path = path_on(comp,'line',face)
            settings = geo.Settings(layout='path',size=.3,gap=.1,margin=.1,path_spacing=.6)
            _,extrusion,count = model.build(face,settings,fixture.config(path=path,operation=operation,
                reverse=operation in ('cut','intersect'),bodies=[body]))
            healthy(extrusion)
            assert all(b.isSolid and b.volume > 0 for b in extrusion.bodies)
            return dict(cells=count,bodies=extrusion.bodies.count)
        case('native_'+operation,native_operation)

    def feature_dependency_recompute():
        comp = fixture.component(design,'Path Feature')
        _,path = path_on(comp,'line')
        settings = geo.Settings(layout='path',size=.25,gap=.1,margin=.05,path_spacing=.7)
        cfg = fixture.config(path=path,result='feature')
        _,custom,count = feature.build(comp.xYConstructionPlane,settings,cfg)
        healthy(custom)
        assert model.native(custom.dependencies.itemById('path').entity) == path
        before = sum(b.volume for b in comp.bRepBodies)
        custom.parameters.itemById('path_spacing').expression = '5 mm'
        after = sum(b.volume for b in comp.bRepBodies)  # Natural recompute first.
        healthy(custom)
        assert after > before
        nodes = design.timeline.count
        path.endSketchPoint.move(adsk.core.Vector3D.create(-.6,0,0))
        shorter = sum(b.volume for b in comp.bRepBodies)
        healthy(custom)
        assert shorter < after
        design.computeAll();healthy(custom)
        assert design.timeline.count == nodes
        assert 'path_samples' not in feature.stored(custom)['settings']
        assert feature.path_dependency(custom) is not None
        return dict(initial_cells=count,before=before,after=after,shorter=shorter)
    case('feature_parameters_upstream_path_natural_recompute',feature_dependency_recompute)

    def rejected_paths_and_seam():
        comp = fixture.component(design,'Rejected paths')
        _,path = path_on(comp,'arc',comp.xZConstructionPlane)
        settings = geo.Settings(layout='path',size=.3,gap=.1,path_spacing=.7)
        before = comp.sketches.count
        try:
            model.build(comp.xYConstructionPlane,settings,fixture.config(path=path,result='profiles'))
            raise AssertionError('Off-plane path accepted')
        except ValueError as error:
            assert 'plane' in str(error)
        assert comp.sketches.count == before
        _,path = path_on(comp,'circle')
        # A tiny closing remainder violates the web; do not duplicate/drop it.
        settings = replace(settings,path_spacing=math.tau*1.2/12.1)
        try:
            model.build(comp.xYConstructionPlane,settings,fixture.config(path=path,result='profiles'))
            raise AssertionError('Unsafe closing seam accepted')
        except ValueError as error:
            assert 'Web Thickness' in str(error)
        return dict(off_plane_rejected=True,seam_rejected=True)
    case('reject_nonplanar_and_short_seam',rejected_paths_and_seam)
finally:
    save('complete')
    if doc:
        doc.close(False)
    if original and original.isValid:
        original.activate()
print('PERFORA_CURVE_REGRESSION', output)
