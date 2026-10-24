# SPDX-License-Identifier: GPL-3.0-only
"""Future CAD acceptance: run with runpy ONLY after explicitly starting that stage.

Requires the registered add-in from this exact checkout. Creates/closes one
unsaved document; restores the user's active document. No installation/reload.
Not executed during offline development. Optional only_cases limits the run.
"""
from dataclasses import replace
import json
from pathlib import Path
import runpy
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
entry = globals().get('entry') or next(m for m in tuple(sys.modules.values())
    if str(getattr(m, '__file__', '')) == str(root / 'Perfora/Perfora.py'))
model, multi, feature = entry.model, entry.multi_region, entry.parametric
geo = sys.modules[entry.Settings.__module__]
fixture = runpy.run_path(str(root / 'PerforaSmokeTest/PerforaSmokeTest.py'))
app = adsk.core.Application.get()
original = app.activeDocument
output = Path.home() / 'Library/Logs/Perfora/multi-region-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)
only_cases = globals().get('only_cases')
results = []


def case(name, action):
    if only_cases and name not in only_cases:
        return
    started = perf_counter()
    try:
        detail = action()
        results.append(dict(name=name, passed=True, seconds=perf_counter()-started, detail=detail))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))
    output.write_text(json.dumps(dict(fusion=app.version, platform=sys.platform, addon=str(entry.__file__),
        passed=bool(results) and all(r['passed'] for r in results), tests=results), indent=2))


def profiles(component, plane=None, centers=((-1.5,0),(1.5,0)), void=False):
    sketch = component.sketches.addWithoutEdges(plane or component.xYConstructionPlane)
    for x,y in centers:
        sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((x,y)), 1.1)
        if void:
            sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((x,y)), .22)
    result = [p for p in sketch.profiles if p.profileLoops.count == (2 if void else 1)]
    assert len(result) == len(centers)
    return sketch,result


def volume(component):
    return sum(b.volume for b in component.bRepBodies if b.isVisible and b.isSolid)


def healthy(custom):
    assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
    for item in custom.features:
        if hasattr(item,'healthState'):
            assert item.healthState != adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState, item.errorOrWarningMessage


doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
try:
    design = adsk.fusion.Design.cast(app.activeProduct)
    for shape in geo.SHAPE_IDS:
        for trim in (False,True):
            def shape_case(shape=shape,trim=trim):
                comp = fixture['component'](design,'Multi '+shape)
                source_sketch, selected = profiles(comp,void=True)
                cfg = fixture['config'](result='profiles',center_point=None)
                settings = geo.Settings(shape=shape,size=.35,slot_length=.6,gap=.14,margin=.1,
                                        grid_angle=.37,clip_boundary=trim,corner_radius=.025 if shape=='voronoi' else 0.)
                renderer = entry.Renderer()
                before = comp.sketches.count
                try:
                    count = renderer.show(selected,settings,cfg)
                    assert comp.sketches.count == before, 'Fast Preview left a reference sketch'
                    expected = [(p.source,p.cells) for p in renderer.multi_plans]
                    reversed_plans = multi.prepare(list(reversed(selected)),settings,cfg)
                    assert all(p.cells == next(c for source,c in expected if source==p.source)
                               for p in reversed_plans), 'Selection order changed phase'
                    first,_,actual = model.build(selected,settings,cfg,renderer.geometry_cache)
                    assert actual == count > 0
                    outputs = [s for s in comp.sketches if s.name.startswith('Perforation ')]
                    assert len(outputs)==2
                    area = sum(p.areaProperties().area for s in outputs for p in model.selected_profiles(s,'cells',trim))
                    assert area > 0
                    for sketch in outputs: sketch.deleteMe()
                    _,extrude,native_count = model.build(selected,settings,dict(cfg,result='extrude'))
                    assert native_count == count
                    assert extrude.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                    assert abs(volume(comp)-area*.2)<1e-6, (volume(comp),area)
                    return dict(holes=count,area_cm2=area,volume_cm3=volume(comp),fast_seconds=renderer.last_seconds)
                finally:
                    renderer.reset()
            case('shape_'+shape+('_trim' if trim else '_whole'),shape_case)

    def moved_planes():
        comp = fixture['component'](design,'Multiple Planes')
        data = comp.constructionPlanes.createInput()
        data.setByOffset(comp.yZConstructionPlane,model.value('27 mm'))
        plane = comp.constructionPlanes.add(data)
        _,a = profiles(comp,centers=((0,0),))
        _,b = profiles(comp,plane,centers=((0,0),))
        selected = a+b
        cfg = fixture['config'](result='profiles',center_point=None)
        settings = geo.Settings(shape='slot',size=.25,slot_length=.55,gap=.12,margin=.08)
        plans = multi.prepare(selected,settings,cfg)
        assert plans[0].frame != plans[1].frame
        _,_,count = model.build(selected,settings,cfg)
        outputs = [s for s in comp.sketches if s.name.startswith('Perforation ')]
        for sketch in outputs:
            for curve in sketch.sketchCurves:
                for point in (curve.startSketchPoint.worldGeometry,curve.endSketchPoint.worldGeometry):
                    assert abs(sketch.modelToSketchSpace(point).z)<1e-7
        return dict(holes=count,frames=[p.frame for p in plans])
    case('translated_vertical_planes',moved_planes)

    def duplicate_overlap_and_failure():
        comp = fixture['component'](design,'Source Validation')
        _,selected = profiles(comp)
        cfg = fixture['config'](result='profiles',center_point=None)
        s = geo.Settings(size=.3,gap=.13,margin=.08)
        assert multi.sources([selected[0],selected[0],selected[1]])==selected
        _,overlap = profiles(comp,centers=((-1.5,0),))
        baseline = comp.sketches.count,design.timeline.count,volume(comp)
        try:
            model.build([selected[0],overlap[0]],s,cfg)
            raise AssertionError('Overlapping sources were accepted')
        except ValueError as error:
            assert 'overlap' in str(error).lower(), str(error)
        assert (comp.sketches.count,design.timeline.count,volume(comp))==baseline
        original_draw = multi.draw
        calls=[]
        def fail_second(*args):
            calls.append(True)
            if len(calls)==2: raise ValueError('Injected second region failure')
            return original_draw(*args)
        multi.draw=fail_second
        try:
            try:
                model.build(selected,s,cfg)
                raise AssertionError('Injected failure did not propagate')
            except ValueError as error:
                assert 'Injected' in str(error)
        finally:
            multi.draw=original_draw
        assert (comp.sketches.count,design.timeline.count,volume(comp))==baseline
        return dict(duplicate_removed=True,overlap_rejected=True,failed_build_clean=True)
    case('duplicate_overlap_atomic_failure',duplicate_overlap_and_failure)

    def shared_body_cut():
        comp = fixture['component'](design,'Shared Cut Target')
        body,face = fixture['plate'](comp)
        sketch = comp.sketches.addWithoutEdges(face)
        for x in (-.95,.95):
            sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((x,0)),.8)
        selected = list(sketch.profiles)
        assert len(selected)==2
        settings=geo.Settings(size=.25,gap=.12,margin=.08,clip_boundary=True)
        cfg=fixture['config'](result='feature',operation='cut',reverse=True,bodies=[body],center_point=None)
        before=body.volume
        _,custom,count=feature.build(selected,settings,cfg)
        healthy(custom)
        assert body.volume<before
        assert len(feature.source_entities(custom))==2
        assert feature.stored(custom)['config']['_body_map']==[[0],[0]]
        custom.parameters.itemById('size').expression='2 mm'
        design.computeAll()
        healthy(custom)
        assert body.isSolid and body.volume<before
        return dict(holes=count,volume_cm3=body.volume)
    case('feature_shared_body_cut_recompute',shared_body_cut)

    def feature_new_body():
        comp = fixture['component'](design,'Multi Feature')
        _,selected=profiles(comp,void=True)
        cfg=fixture['config'](result='feature',center_point=None)
        settings=geo.Settings(shape='voronoi',size=.35,gap=.13,margin=.08,clip_boundary=True,corner_radius=.02)
        _,custom,count=feature.build(selected,settings,cfg)
        healthy(custom)
        before=volume(comp)
        custom.parameters.itemById('distance1').expression='4 mm'
        design.computeAll()
        healthy(custom)
        assert abs(volume(comp)-2*before)<1e-6
        source,stored_settings,stored_config=feature.read(custom)
        assert len(source)==2 and stored_settings.shape=='voronoi'
        assert len(stored_config['_body_map'])==2
        return dict(holes=count,volume_cm3=volume(comp),sources=len(source))
    case('feature_multi_source_schema_recompute',feature_new_body)

    def plate_at(comp,x):
        sketch=comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(model.point((x-1.4,-1.2)),model.point((x+1.4,1.2)))
        extrude=model.extrude(comp,sketch.profiles.item(0),fixture['config'](distance1='4 mm'))
        body=extrude.bodies.item(0)
        face=next(f for f in body.faces if isinstance(f.geometry,adsk.core.Plane)
                  and abs(f.boundingBox.minPoint.z-.4)<1e-7 and abs(f.boundingBox.maxPoint.z-.4)<1e-7)
        sketch.isVisible=False
        return body,face

    for mode in ('extrude','feature'):
        for operation in ('cut','join','intersect'):
            def mapped_operation(mode=mode,operation=operation):
                comp=fixture['component'](design,'Mapped '+mode+' '+operation)
                a,fa=plate_at(comp,-2.)
                b,fb=plate_at(comp,2.)
                before=(a.volume,b.volume)
                cfg=fixture['config'](result=mode,operation=operation,bodies=[b,a],
                                       reverse=operation!='join',center_point=None)
                settings=geo.Settings(size=.35,gap=.15,margin=.1,clip_boundary=True)
                build=feature.build if mode=='feature' else model.build
                _,result,count=build([fa,fb],settings,cfg)
                if mode=='feature': healthy(result)
                else: assert result.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                after=(a.volume,b.volume)
                assert all((new>old if operation=='join' else 0<new<old) for old,new in zip(before,after))
                if mode=='feature':
                    assert feature.stored(result)['config']['_body_map']==[[1],[0]]
                    result.parameters.itemById('size').expression='3 mm'
                    design.computeAll()
                    healthy(result)
                    assert all(body.isSolid and body.volume>0 for body in (a,b))
                return dict(holes=count,before_cm3=before,after_cm3=after)
            case(mode+'_mapped_'+operation,mapped_operation)
finally:
    doc.close(False)
    if original and original.isValid: original.activate()

print('PERFORA_MULTI_REGION',output,results)
