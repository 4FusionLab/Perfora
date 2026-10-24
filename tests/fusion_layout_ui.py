# SPDX-License-Identifier: GPL-3.0-only
"""Focused native UI acceptance for the 50 mm square and pointed cone.

Launch via the Fusion Python console, click real OK/Cancel, then call finish().
All model changes stay in a separate unsaved document.
"""
import json
import math
from pathlib import Path
import sys
import traceback
import adsk.core
import adsk.fusion

app=adsk.core.Application.get()
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==
    str(Path(__file__).resolve().parents[1]/'Perfora/Perfora.py'))
original=app.activeDocument
original_design=adsk.fusion.Design.cast(app.activeProduct)
original_revision=(original_design.timeline.count,sum(b.volume for b in original_design.rootComponent.bRepBodies))
kind=globals().get('kind','plane')
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
doc.name='Perfora Layout Acceptance'
design=adsk.fusion.Design.cast(app.activeProduct)
comp=design.rootComponent
manager=adsk.fusion.TemporaryBRepManager.get()
if kind=='plane':
    temp=manager.createBox(adsk.core.OrientedBoundingBox3D.create(adsk.core.Point3D.create(0,0,-.1),
        adsk.core.Vector3D.create(1,0,0),adsk.core.Vector3D.create(0,1,0),5.,5.,.2))
else:
    temp=manager.createCylinderOrCone(adsk.core.Point3D.create(),2.5,
        adsk.core.Point3D.create(0,0,9.),.088457268)
base=comp.features.baseFeatures.add();base.startEdit();comp.bRepBodies.add(temp,base);base.finishEdit()
body=base.bodies.item(0)
face=(max((f for f in body.faces if isinstance(f.geometry,adsk.core.Plane)),key=lambda f:f.pointOnFace.z)
    if kind=='plane' else next(f for f in body.faces if isinstance(f.geometry,adsk.core.Cone)))
timeline=design.timeline.count
volume=body.volume
report=dict(kind=kind,passed=False)
output=Path.home()/('Library/Logs/Perfora/layout-ui-'+kind+'.json')
output.parent.mkdir(parents=True,exist_ok=True)
lifetime=[]
def save():output.write_text(json.dumps(report,indent=2),encoding='utf-8')

class Activate(adsk.core.CommandEventHandler):
    def __init__(self,s):super().__init__();self.s=s;self.done=False
    def notify(self,args):
        if self.done:return
        self.done=True
        s=self.s
        try:
            s.updating=True
            try:
                s.inputs['preview'].value=False
                for key,options,value in (('result',entry.RESULTS,'feature'),('shape',entry.SHAPES,'circle'),
                    ('layout',entry.LAYOUTS,'circular' if kind=='plane' else 'rows'),
                    ('surface_layout',entry.SURFACE_LAYOUTS,'rows'),('material',entry.MATERIALS,'cells'),
                    ('preview_mode',entry.PREVIEW_MODES,'fast')):
                    s.inputs[key].listItems.item(next(i for i,p in enumerate(options) if p[0]==value)).isSelected=True
                for key,value in dict(size='5 mm',gap='1.5 mm',margin='3 mm',distance1='2 mm',
                    offset_x='0 mm',offset_y='0 mm',grid_angle='0 deg',shape_angle='0 deg',start_radius='0 mm',
                    cylinder_start='0 deg',cylinder_sweep='360 deg',axial_start='0 mm',axial_length='0 mm').items():
                    s.inputs[key].expression=value
                s.sync_dimensions('size')
                s.inputs['center_point'].clearSelection()
                s.inputs['clip_boundary'].value=False
                s.inputs['source'].clearSelection();s.inputs['source'].addSelection(face)
            finally:s.updating=False
            s.update_visibility()
            s.inputs['preview'].value=True
            args.command.doExecutePreview()
            report.update(passed=True,stage='ready')
            camera=app.activeViewport.camera
            camera.eye=adsk.core.Point3D.create(0,-14,5 if kind=='cone' else 6)
            camera.target=adsk.core.Point3D.create(0,0,4.5 if kind=='cone' else 0)
            camera.upVector=adsk.core.Vector3D.create(0,0,1)
            if kind=='plane':
                camera.eye=adsk.core.Point3D.create(0,0,10)
                camera.upVector=adsk.core.Vector3D.create(0,1,0)
            camera.isFitView=True;app.activeViewport.camera=camera
        except Exception:report.update(error=traceback.format_exc())
        save()
class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self,args):
        s=entry._sessions[-1]
        handler=Activate(s);lifetime.extend((s,handler));args.command.activate.add(handler)

def check_preview():
    s=entry._sessions[-1]
    assert not s.preview_error,s.preview_error
    cells=s.renderer.cells
    if kind=='plane':
        # The test box's sketch axes may be translated; measure about the same
        # automatic boundary center used by the command.
        center=entry.surface.geo.placement_center(s.renderer.region,s.read()[1])
        points={(round(c.center[0]-center[0],7),round(c.center[1]-center[1],7)) for c in cells}
        assert points=={(-x,-y) for x,y in points}
        inner=[p for p in points if abs(math.hypot(*p)-.65)<1e-6]
        assert len(inner)==6,len(inner)
        report.update(central_symmetry=True,first_ring_holes=len(inner))
    else:assert len(cells)>=120,len(cells)
    report.update(holes=len(cells),status=s._status_text)
    save();return report

def finish(created=False):
    try:
        assert app.userInterface.activeCommand!=entry.COMMAND_ID
        assert report['passed'],report
        if created:
            custom=comp.features.customFeatures.item(0)
            assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            assert sum(b.volume for b in comp.bRepBodies)<volume
        else:assert design.timeline.count==timeline and abs(comp.bRepBodies.item(0).volume-volume)<1e-8
        assert comp.customGraphicsGroups.count==0
        report.update(transaction='created' if created else 'cancelled',transaction_passed=True)
    except Exception:report.update(passed=False,error=traceback.format_exc())
    finally:
        definition.commandCreated.remove(handler)
        doc.close(False);original.activate()
        report['original_unchanged']=(original_design.timeline.count,sum(b.volume for b in original_design.rootComponent.bRepBodies))==original_revision
        save()
    return report

definition=app.userInterface.commandDefinitions.itemById(entry.COMMAND_ID)
handler=Created();lifetime.append(handler);definition.commandCreated.add(handler)
definition.execute()
