# SPDX-License-Identifier: GPL-3.0-only
"""Native optimization checks; optional baseline_path compares a frozen package."""
from dataclasses import replace
import importlib.util
from importlib import import_module
import json
from pathlib import Path
import runpy
import sys
from time import perf_counter
import traceback
from unittest.mock import patch

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
entry = globals().get('entry') or next(m for m in tuple(sys.modules.values())
    if str(getattr(m, '__file__', '')) == str(root / 'Perfora/Perfora.py'))
model, preview = entry.model, sys.modules[entry.Renderer.__module__]
g = sys.modules[entry.Settings.__module__]
clipping = (entry.parametric.clipping if hasattr(entry, 'parametric') else
            import_module(entry.Settings.__module__.rsplit('.', 1)[0] + '.clipping'))
fixture = runpy.run_path(str(root / 'PerforaSmokeTest/PerforaSmokeTest.py'))
app = adsk.core.Application.get()
original = app.activeDocument
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design = adsk.fusion.Design.cast(app.activeProduct)
results = []
output = Path.home() / 'Library/Logs/Perfora/optimization-regression.json'


def case(name, action):
    started = perf_counter()
    try:
        results.append(dict(name=name, passed=True, seconds=perf_counter()-started, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(passed=all(r['passed'] for r in results), tests=results), indent=2))


def new_component(name):
    return fixture['component'](design, name)


try:
    def cache_and_lazy():
        comp = new_component('Cache and Lazy Panel')
        cfg = fixture['config'](result='profiles', width=3, height=2.5)
        settings = g.Settings(shape='circle', size=.55, gap=.13, margin=0,
                              clip_boundary=True, offset_x=.2)
        renderer = preview.Renderer()
        try:
            count = renderer.show(comp.xYConstructionPlane, settings, cfg)
            layout = renderer.clipped_layout
            assert layout.partial_bodies
            assert layout.panel_builds == layout.panel_subtractions == 0
            original_area = renderer.original_body.area
            misses = renderer.geometry_cache.misses
            start = perf_counter()
            sketch, _, built = model.build(comp.xYConstructionPlane, settings, cfg, cache=renderer.geometry_cache)
            build_seconds = perf_counter()-start
            assert renderer.geometry_cache.hits == 1 and renderer.geometry_cache.misses == misses
            assert built == count
            area = sum(p.areaProperties().area for p in sketch.profiles)
            renderer.show(comp.xYConstructionPlane, settings, dict(cfg, material='panel'))
            assert layout.panel_builds == 1 and layout.panel_subtractions == len(layout.partial_bodies)
            renderer.show(comp.xYConstructionPlane, settings, cfg)
            renderer.show(comp.xYConstructionPlane, settings, dict(cfg, material='panel'))
            assert layout.panel_builds == 1
            assert abs(renderer.original_body.area-original_area) < 1e-9
            # The same cells must use current extrusion settings, not cached cfg.
            _, extrude, built = model.build(comp.xYConstructionPlane, settings,
                dict(cfg, result='extrude', distance1='3 mm'), cache=renderer.geometry_cache)
            assert count == built and abs(sum(b.volume for b in extrude.bodies)-area*.3)<1e-6
            return dict(cells=count, partial=len(layout.partial_bodies), panel_builds=layout.panel_builds,
                        cache_hits=renderer.geometry_cache.hits, build_seconds=build_seconds)
        finally:
            renderer.reset()
    case('shared_cells_lazy_panel_current_extrude', cache_and_lazy)

    def native_failure_retry():
        comp = new_component('Panel Retry')
        cfg = fixture['config'](result='profiles', width=3, height=2.5)
        settings = g.Settings(size=.55, gap=.13, margin=0, clip_boundary=True, offset_x=.2)
        renderer = preview.Renderer()
        try:
            renderer.show(comp.xYConstructionPlane, settings, cfg)
            layout = renderer.clipped_layout
            area = renderer.original_body.area
            manager = adsk.fusion.TemporaryBRepManager.get()
            class FailAfterMutation:
                def __getattr__(self, key): return getattr(manager, key)
                def booleanOperation(self, target, tool, kind):
                    result = manager.booleanOperation(target, tool, kind)
                    assert result
                    return False  # Real target was modified before this failure.
            with patch.object(adsk.fusion.TemporaryBRepManager, 'get', return_value=FailAfterMutation()):
                try:
                    layout.panel_loops
                    raise AssertionError('Expected the injected failure')
                except ValueError:
                    pass
            assert layout._panel_loops is None and layout.panel_builds == 0
            assert abs(renderer.original_body.area-area)<1e-9
            loops = layout.panel_loops
            assert loops and layout.panel_builds == 1
            assert abs(renderer.original_body.area-area)<1e-9
            return dict(partial=len(layout.partial_bodies), successful_builds=layout.panel_builds)
        finally:
            renderer.reset()
    case('panel_retry_after_real_target_mutation', native_failure_retry)

    def original_inset_scope_cache():
        comp = new_component('Inset Layers')
        cfg = fixture['config'](result='profiles')
        settings = g.Settings(size=.3, gap=.13, margin=.1, clip_boundary=True, spread_radius=1.1)
        renderer = preview.Renderer()
        try:
            with patch.object(clipping, 'source_body', wraps=clipping.source_body) as source_calls, \
                 patch.object(clipping, 'inset_body', wraps=clipping.inset_body) as inset_calls:
                for margin in (.1, .15, .2, .25):
                    renderer.show(comp.xYConstructionPlane, replace(settings, margin=margin), cfg)
                assert source_calls.call_count == 1 and inset_calls.call_count == 4
                for size in (.31, .32, .33):
                    renderer.show(comp.xYConstructionPlane, replace(settings, margin=.25, size=size), cfg)
                for radius in (1.2, 1.3, 1.4):
                    renderer.show(comp.xYConstructionPlane, replace(settings, margin=.25, spread_radius=radius), cfg)
                assert source_calls.call_count == 1 and inset_calls.call_count == 4
                return dict(source_calls=source_calls.call_count, inset_calls=inset_calls.call_count,
                            layouts=renderer.layout_builds)
        finally:
            renderer.reset()
    case('separate_source_inset_spread_cache', original_inset_scope_cache)

    def moved_plane_revision():
        comp = new_component('Moving Source Plane')
        data = comp.constructionPlanes.createInput()
        data.setByOffset(comp.yZConstructionPlane, model.value('20 mm'))
        plane = comp.constructionPlanes.add(data)
        cfg = fixture['config'](result='profiles')
        settings = g.Settings(shape='hexagon', size=.4, gap=.13, margin=.1)
        renderer = preview.Renderer()
        try:
            renderer.show(plane, settings, cfg)
            before = renderer.frame
            key = renderer.source_key
            plane.definition.offset.expression = '25 mm'
            renderer.show(plane, settings, cfg)
            assert renderer.source_key > key and renderer.frame != before
            assert abs(renderer.frame[0][0]-2.5)<1e-7
            return dict(before=before[0], after=renderer.frame[0])
        finally:
            renderer.reset()
    case('same_plane_identity_updated_frame', moved_plane_revision)

    if hasattr(entry, 'parametric'):
        def feature_cache():
            comp = new_component('Shared Feature Cache')
            sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
            anchor = sketch.sketchPoints.add(model.point((.2, -.1)))
            cfg = fixture['config'](result='feature', material='panel', center_point=anchor)
            settings = g.Settings(shape='slot', layout='circular', size=.3, slot_length=.6,
                gap=.13, margin=.1, spread_radius=1.3, tangential_orientation=True, clip_boundary=True)
            renderer = preview.Renderer()
            try:
                count = renderer.show(comp.xYConstructionPlane, settings, cfg)
                _, custom, built = entry.parametric.build(comp.xYConstructionPlane, settings, cfg,
                                                          cache=renderer.geometry_cache)
                assert built == count and renderer.geometry_cache.hits == 1
                assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                before = sum(b.volume for b in comp.bRepBodies)
                custom.parameters.itemById('spread_radius').expression = '7 mm'
                after = sum(b.volume for b in comp.bRepBodies)
                assert abs(after-before)>1e-7 and custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                return dict(cells=count, cache_hits=renderer.geometry_cache.hits, before=before, after=after)
            finally:
                renderer.reset()
        case('feature_cache_then_live_radius_recompute', feature_cache)

    baseline_path = globals().get('baseline_path')
    if baseline_path:
        package = '_perfora_optimization_baseline'
        spec = importlib.util.spec_from_file_location(package, Path(baseline_path)/'__init__.py',
            submodule_search_locations=[str(baseline_path)])
        module = importlib.util.module_from_spec(spec);sys.modules[package]=module;spec.loader.exec_module(module)
        bm, bg, bp = [import_module(package+'.'+name) for name in ('model','geometry','preview')]
        def paired():
            rows = []
            for name, values, changes in (
                ('disk_hexagon',dict(shape='hexagon',size=.5,gap=.15,margin=.3),dict(boundary='circle',width=12)),
                ('disk_ellipse',dict(shape='ellipse',size=.5,slot_length=1,gap=.15,margin=.3),dict(boundary='circle',width=8)),
                ('scoped_tangential',dict(shape='slot',layout='circular',size=.3,slot_length=.65,gap=.13,
                    margin=.1,clip_boundary=True,tangential_orientation=True,spread_radius=1.1),{})):
                pair=[]
                for label, mm, gg, pp in (('baseline',bm,bg,bp),('optimized',model,g,preview)):
                    comp = new_component(name+' '+label)
                    cfg = fixture['config'](result='profiles',**changes)
                    settings = gg.Settings(**values)
                    renderer = pp.Renderer()
                    try:
                        start = perf_counter();count = renderer.show(comp.xYConstructionPlane,settings,cfg);fast = perf_counter()-start
                        coords = list(renderer.coordinates)
                        start = perf_counter()
                        kw = {'cache':renderer.geometry_cache} if label=='optimized' else {}
                        sketch, _, built = mm.build(comp.xYConstructionPlane,settings,cfg,**kw)
                        build = perf_counter()-start
                        area = sum(p.areaProperties().area for p in sketch.profiles)
                        assert count == built
                        pair.append(dict(variant=label,cells=count,area=area,fast_seconds=fast,build_seconds=build,coords=coords))
                    finally:
                        renderer.reset()
                a,b = pair
                assert a['cells']==b['cells'] and abs(a['area']-b['area'])<1e-6
                assert len(a['coords'])==len(b['coords']) and max(abs(x-y) for x,y in zip(a['coords'],b['coords']))<1e-7
                for item in pair:item.pop('coords')
                rows.append(dict(case=name,results=pair))
            return rows
        case('paired_baseline_native_geometry_and_timings', paired)
finally:
    doc.close(False)
    if original and original.isValid: original.activate()
    report = dict(passed=all(r['passed'] for r in results),fusion=app.version,addon=entry.__file__,tests=results)
    output.write_text(json.dumps(report,indent=2))
print('PERFORA_OPTIMIZATION',report)
