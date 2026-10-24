# SPDX-License-Identifier: GPL-3.0-only
"""Exact selected body snapshot, disposable CAD, compact per-face pass/fail.

Pass source_body_name when diagnosing a particular open design. This script
never changes or saves that design. The clean_extrusion option reconstructs an unperforated Z extrusion from
the bottom profile for spacing and cutting checks on the original shape.
"""
import importlib.util
from importlib import import_module
import json
from pathlib import Path
import sys
import traceback
from time import perf_counter
import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
package='_perfora_surface_face_test'
for key in tuple(sys.modules):
    if key==package or key.startswith(package+'.'):
        del sys.modules[key]
spec=importlib.util.spec_from_file_location(package,root/'Perfora/__init__.py',submodule_search_locations=[str(root/'Perfora')])
module=importlib.util.module_from_spec(spec);sys.modules[package]=module;spec.loader.exec_module(module)
surface=import_module(package+'.surface');geo=import_module(package+'.geometry')
app=adsk.core.Application.get();original=app.activeDocument
original_design=adsk.fusion.Design.cast(app.activeProduct)
manager=adsk.fusion.TemporaryBRepManager.get()
name=globals().get('source_body_name')
source=(original_design.rootComponent.bRepBodies.itemByName(name) if name else
        max(original_design.rootComponent.bRepBodies,key=lambda b:sum(f.area for f in b.faces if isinstance(f.geometry,adsk.core.NurbsSurface))))
revision=source.revisionId;timeline=original_design.timeline.count
snapshot=manager.copy(source)
if globals().get('clean_extrusion'):
    solid=import_module(package+'.solid')
    low=source.boundingBox.minPoint.z;high=source.boundingBox.maxPoint.z
    bottom=max((f for f in source.faces if isinstance(f.geometry,adsk.core.Plane) and abs(f.boundingBox.maxPoint.z-low)<1e-7),key=lambda f:f.area)
    sheet=manager.copy(bottom);transform=adsk.core.Matrix3D.create();transform.translation=adsk.core.Vector3D.create(0,0,-low);manager.transform(sheet,transform)
    snapshot=solid.extrude([sheet],0,high-low)
    transform.translation=adsk.core.Vector3D.create(0,0,low);manager.transform(snapshot,transform)
report=dict(document=original.name,body=source.name,tests=[])
output=Path.home()/'Library/Logs/Perfora/surface-face-regression.json'
doc=None
try:
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design=adsk.fusion.Design.cast(app.activeProduct);comp=design.rootComponent
    base=comp.features.baseFeatures.add();base.startEdit()
    comp.bRepBodies.add(snapshot,base);base.finishEdit()
    body=base.bodies.item(0)
    faces=sorted((f for f in body.faces if surface.supported(f) and f.area>8 and f.loops.count<20),key=lambda f:-f.area)[:4]
    for face in faces[:globals().get('face_limit',len(faces))]:
        if globals().get('face_type') and face.geometry.objectType.split('::')[-1]!=face_type:continue
        started=perf_counter()
        item=dict(area=round(face.area,4),type=face.geometry.objectType.split('::')[-1],loops=face.loops.count,point=face.pointOnFace.asArray())
        try:
            settings=geo.Settings(size=.5,gap=.15,margin=.3,staggered=True,limit=globals().get('hole_limit',1500))
            config=dict(surface=True,result='extrude',operation='cut',material='cells',distance1='2 mm')
            chart=surface.Chart(face)
            item['chart']=dict(width=chart.width,height=chart.height,minimum_metric=getattr(chart,'minimum_metric',None),normal_rate=getattr(chart,'normal_rate',None))
            if globals().get('chart_only'):
                item.update(passed=True,seconds=perf_counter()-started)
                report['tests'].append(item)
                continue
            if chart.kind!='freeform':config['cylinder_sweep']=chart.sweep
            prepared=surface.prepare(face,settings,config,chart)
            assert len(prepared.sections)>10,'A regular large face must not be starved by a remote sharp bend'
            rows={}
            for section in prepared.sections:
                x,y=chart.chart_point(section.frame[0]);rows.setdefault(round(y,5),[]).append(x)
            gaps=[b-a for row in rows.values() for a,b in zip(sorted(row),sorted(row)[1:])]
            if gaps:item['row_pitch']=dict(min=min(gaps),max=max(gaps),skipped=sum(g>min(gaps)*1.5 for g in gaps),pairs=len(gaps))
            coordinates=prepared.coordinates
            step=max(3,(len(coordinates)//100//3)*3)
            for i in range(0,len(coordinates),step):
                assert face.isPointOnFace(adsk.core.Point3D.create(*coordinates[i:i+3]),1e-6),'Preview lies outside the trimmed source'
            if globals().get('build'):
                target_comp=comp.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
                target_base=target_comp.features.baseFeatures.add();target_base.startEdit()
                target_comp.bRepBodies.add(snapshot,target_base);target_base.finishEdit()
                target_body=target_base.bodies.item(0)
                target_face=min((f for f in target_body.faces if f.geometry.objectType==face.geometry.objectType),key=lambda f:abs(f.area-face.area))
                before=target_body.volume
                _,feature,count=surface.build(target_face,settings,config)
                result=feature.bodies.item(0)
                assert count==len(prepared.sections) and result.isSolid and result.volume<before
                for i in range(0,len(coordinates),step):
                    assert result.pointContainment(adsk.core.Point3D.create(*coordinates[i:i+3]))==adsk.fusion.PointContainment.PointOnPointContainment,'Preview disagrees with the actual cut'
                item['cut_verified']=True
            item.update(passed=True,holes=len(prepared.sections))
        except Exception:
            item.update(passed=False,error=traceback.format_exc())
        item['seconds']=perf_counter()-started;report['tests'].append(item)
finally:
    if doc and doc.isValid:doc.close(False)
    original.activate()
    report['original_unchanged']=source.revisionId==revision and original_design.timeline.count==timeline
    output.write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(body=report['body'],original_unchanged=report['original_unchanged'],tests=[dict(area=t['area'],type=t['type'],passed=t['passed'],detail=t.get('row_pitch',t.get('chart')),holes=t.get('holes'),error=t.get('error','').splitlines()[-1:]) for t in report['tests']])))
