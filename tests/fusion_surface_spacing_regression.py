# SPDX-License-Identifier: GPL-3.0-only
"""Read-only physical row-spacing audit on large NURBS faces in the open design."""
import importlib.util
from importlib import import_module
import json
from pathlib import Path
import sys
import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1];package='_perfora_spacing_test'
for key in tuple(sys.modules):
    if key==package or key.startswith(package+'.'):del sys.modules[key]
spec=importlib.util.spec_from_file_location(package,root/'Perfora/__init__.py',submodule_search_locations=[str(root/'Perfora')])
module=importlib.util.module_from_spec(spec);sys.modules[package]=module;spec.loader.exec_module(module)
surface=import_module(package+'.surface')
app=adsk.core.Application.get();design=adsk.fusion.Design.cast(app.activeProduct)
results=[]
for body in design.rootComponent.bRepBodies:
    for face in body.faces:
        if not isinstance(face.geometry,adsk.core.NurbsSurface) or face.area<8:continue
        chart=surface.Chart(face)
        for fraction in (.2,.5,.8):
            y=chart.height*fraction;lengths=[]
            uv=[]
            for i in range(17):
                p=surface.point(chart.frame(chart.width*i/16,y)[0])
                ok,q=face.evaluator.getParameterAtPoint(p)
                assert ok
                uv.append(q.asArray())
            for a,b in zip(uv,uv[1:]):
                previous=None;total=0.
                for i in range(129):
                    q=adsk.core.Point2D.create(*(a[j]+(b[j]-a[j])*i/128 for j in (0,1)))
                    ok,p=face.evaluator.getPointAtParameter(q);assert ok
                    if previous:total+=p.distanceTo(previous)
                    previous=p
                lengths.append(total)
            relative=(max(lengths)-min(lengths))/(sum(lengths)/len(lengths))
            results.append(dict(body=body.name,face=face.tempId,row=fraction,min_cm=min(lengths),max_cm=max(lengths),variation=relative,passed=relative<.002))
report=dict(passed=bool(results) and all(r['passed'] for r in results),rows=results)
(Path.home()/'Library/Logs/Perfora/surface-spacing.json').write_text(json.dumps(report,indent=2))
print(json.dumps(dict(passed=report['passed'],rows=len(results),worst_variation=max((r['variation'] for r in results),default=0))))
