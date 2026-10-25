# SPDX-License-Identifier: GPL-3.0-only
"""PREPARED, NOT RUN. Run manually inside Fusion only after explicit CAD handoff.

Requires the registered add-in from this checkout. Uses a separate unsaved
document and restores the original. Optional shapes=('circle', ...) bounds a
run; default covers all 12 repeating shapes. Does not install/reload anything.
"""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
addon_path = Path(globals().get('addon_path', root/'Perfora')).resolve()
entry = next(m for m in tuple(sys.modules.values())
             if str(getattr(m,'__file__','')) == str(addon_path/'Perfora.py'))
model, feature = entry.model, entry.parametric
geo = sys.modules[entry.Settings.__module__]
preview = sys.modules[entry.Renderer.__module__]
spec = importlib.util.spec_from_file_location('_layout_fixture',root/'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
app = adsk.core.Application.get()
original = app.activeDocument
output = Path(globals()['report_path']) if 'report_path' in globals() else Path.home()/'Library/Logs/Perfora/layout-variants-regression.json' if sys.platform=='darwin' else Path.home()/'Perfora-test-results/layout-variants-regression.json'
output.parent.mkdir(parents=True,exist_ok=True)
results=[]


def save(stage):
    output.write_text(json.dumps(dict(stage=stage, fusion=app.version, os=platform.platform(),
                     addon=str(addon_path), passed=bool(results) and all(r['passed'] for r in results),
                     tests=results),indent=2),encoding='utf-8')


def case(name, action):
    save(name)
    global doc, design
    # Keep native computeAll bounded: prior cases must not regenerate every
    # previous Feature in an ever-growing acceptance design.
    if doc:
        doc.close(False)
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design=adsk.fusion.Design.cast(app.activeProduct)
    started=perf_counter()
    try:
        results.append(dict(name=name,passed=True,seconds=perf_counter()-started,detail=action()))
        results[-1]['seconds']=perf_counter()-started
    except Exception:
        results.append(dict(name=name,passed=False,seconds=perf_counter()-started,error=traceback.format_exc()))
    save(name+' complete')


def guides(comp,plane):
    sketch=comp.sketches.addWithoutEdges(plane)
    result=[]
    for y in (-.7,.7):
        line=sketch.sketchCurves.sketchLines.addByTwoPoints(model.point((-1.5,y)),model.point((1.5,y+.15)))
        line.isConstruction=True
        result.append(line)
    sketch.isVisible=False
    return result


def healthy(custom):
    assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage


doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
try:
    design=adsk.fusion.Design.cast(app.activeProduct)
    for layout in globals().get('layouts', geo.VARIANT_LAYOUTS):
        for shape in globals().get('shapes',tuple(s for s in geo.SHAPE_IDS if s!='voronoi' and s not in geo.ORGANIC_SHAPES)):
            for trim in (False,True):
                def check(layout=layout,shape=shape,trim=trim):
                    comp=fixture.component(design,layout+' '+shape)
                    data=comp.constructionPlanes.createInput()
                    data.setByOffset(comp.yZConstructionPlane,adsk.core.ValueInput.createByString('27 mm'))
                    plane=comp.constructionPlanes.add(data)
                    cfg=fixture.config(result='profiles',width=4,height=3)
                    if layout=='between_curves': cfg.update(zip(('guide1','guide2'),guides(comp,plane)))
                    s=geo.Settings(layout=layout,shape=shape,size=.35,slot_length=.65,arm_width=.12,
                                   gap=.12,margin=.15,shape_angle=.37,grid_angle=.21,
                                   clip_boundary=trim,limit=5000,contour_tolerance=.04,
                                   distribution_revision=globals().get('revision',1),
                                   layout_orientation='tangent' if globals().get('revision')==2 else 'fixed')
                    renderer=preview.Renderer()
                    before=comp.sketches.count
                    try:
                        count=renderer.show(plane,s,cfg)
                        assert comp.sketches.count==before
                        expected=tuple(renderer.cells)
                        builds=renderer.layout_builds
                        renderer.show(plane,s,dict(cfg,distance1='3 mm'))
                        assert renderer.layout_builds==builds,'Extrude-only edit rebuilt layout'
                        local=geo.outline_coordinates(expected,renderer.region)
                        if not trim:
                            actual=renderer.graphics.item(0).coordinates.getCoordinate(0)
                            actual.transformBy(renderer.graphics.transform)
                            reference=model.new_source_sketch(plane)
                            try:
                                target=reference.sketchToModelSpace(adsk.core.Point3D.create(*local[:3]))
                                assert actual.distanceTo(target)<1e-5
                            finally: reference.deleteMe()
                        sketch,_,n=model.build(plane,s,cfg,cache=renderer.geometry_cache)
                        assert n==count
                        area=sum(p.areaProperties().area for p in sketch.profiles)
                        assert area>0
                        if not trim:
                            assert sketch.profiles.count==count
                            if shape=='circle':
                                actual=[c.geometry.center for c in sketch.sketchCurves.sketchCircles]
                                assert all(any(abs(p.x-c.center[0])<1e-7 and abs(p.y-c.center[1])<1e-7 for p in actual) for c in expected)
                        _,extrude,n=model.build(plane,s,dict(cfg,result='extrude'),cache=renderer.geometry_cache)
                        healthy(extrude)
                        assert n==count
                        assert abs(sum(b.volume for b in extrude.bodies)-area*.2)<1e-5
                        _,custom,n=feature.build(plane,s,dict(cfg,result='feature'),cache=renderer.geometry_cache)
                        healthy(custom)
                        assert n==count
                        read_source,read_s,read_cfg=feature.read(custom)
                        assert read_s.layout==layout
                        assert all(custom.parameters.itemById(k) for k in entry.VARIANT_PARAMETERS)
                        if layout=='between_curves':
                            assert all(custom.dependencies.itemById(k) for k in ('guide1','guide2'))
                        # This is a programmatic update, not Edit Feature OK/Cancel.
                        # Full native edit acceptance is a separate manual gate.
                        count2=feature.update(custom,replace(read_s,size=.3),read_cfg)
                        healthy(custom)
                        assert count2>0
                        design.computeAll()
                        healthy(custom)
                        return dict(cells=count,updated_cells=count2,area_cm2=area,fast_seconds=renderer.last_seconds)
                    finally: renderer.reset()
                case(layout+'_'+shape+('_trim' if trim else '_whole'),check)

    def live_guides():
        comp=fixture.component(design,'Guide dependency and preview')
        plane=comp.xYConstructionPlane
        a,b=guides(comp,plane)
        cfg=fixture.config(result='feature',guide1=a,guide2=b)
        s=geo.Settings(layout='between_curves',size=.3,gap=.1,margin=.1,distribution_revision=globals().get('revision',1))
        renderer=preview.Renderer()
        try:
            renderer.show(plane,s,cfg)
            before=tuple(renderer.cells)
            a.startSketchPoint.move(adsk.core.Vector3D.create(0,.1,0))
            renderer.show(plane,s,cfg)
            assert tuple(renderer.cells)!=before,'Guide edit did not invalidate preview'
            _,custom,_=feature.build(plane,s,cfg)
            base=next(f for f in custom.features if isinstance(f,adsk.fusion.BaseFeature))
            before_bounds=tuple(base.bodies.item(0).boundingBox.minPoint.asArray())+tuple(base.bodies.item(0).boundingBox.maxPoint.asArray())
            before_volume=base.bodies.item(0).volume
            a.startSketchPoint.move(adsk.core.Vector3D.create(0,.1,0))
            design.computeAll()
            healthy(custom)
            source,stored_s,stored_cfg=feature.read(custom)
            expected=model.layout_settings(stored_s,stored_cfg,geo.rectangle_region(4,3),renderer.frame,comp)
            assert tuple(geo.generate(geo.rectangle_region(4,3),expected))!=before
            # Native recompute must update visible geometry, not just its status.
            body=base.bodies.item(0)
            after_volume=body.volume
            after_bounds=tuple(body.boundingBox.minPoint.asArray())+tuple(body.boundingBox.maxPoint.asArray())
            assert any(abs(a-b)>1e-6 for a,b in zip(before_bounds,after_bounds)), 'Guide recompute did not change output bounds'
            sketches=[f for f in custom.features if isinstance(f,adsk.fusion.Sketch)]
            expected_body,_=feature.make_body(source,stored_s,stored_cfg,sketches[0],sketches[1])
            expected_bounds=tuple(expected_body.boundingBox.minPoint.asArray())+tuple(expected_body.boundingBox.maxPoint.asArray())
            assert abs(body.volume-expected_body.volume)<1e-6
            assert all(abs(a-b)<1e-6 for a,b in zip(after_bounds,expected_bounds))
            return dict(before_volume_cm3=before_volume,after_volume_cm3=after_volume,
                        guide_dependency=custom.dependencies.itemById('guide1').entity.isValid)
        finally: renderer.reset()
    if 'between_curves' in globals().get('layouts', geo.VARIANT_LAYOUTS):
        case('live_guide_preview_dependency',live_guides)
finally:
    doc.close(False)
    if original: original.activate()
    save('complete')
print('PERFORA_LAYOUT_VARIANTS',str(output))
