# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy in Fusion's Python console with the registered add-in running.

Creates one disposable document and opens Edit Feature with a replacement Start
Point, Spread Radius, Tangential orientation, and Full Preview. Click OK/Cancel,
then call namespace['finish'](True/False). Original document is restored.
"""
import adsk.core, adsk.fusion, builtins, sys, runpy, json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
app=adsk.core.Application.get();original=app.activeDocument
original_design=adsk.fusion.Design.cast(app.activeProduct)
original_timeline=original_design.timeline.count
original_volume=sum(b.volume for b in original_design.rootComponent.bRepBodies)
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design=adsk.fusion.Design.cast(app.activeProduct);comp=design.rootComponent
upstream=comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
anchor=upstream.sketchPoints.add(entry.model.point((.2,-.1)))
replacement=upstream.sketchPoints.add(entry.model.point((-.5,.3)))
fixture=runpy.run_path(str(root/'PerforaSmokeTest/PerforaSmokeTest.py'))
cfg=fixture['config'](result='feature',material='panel',center_point=anchor)
s=entry.Settings(layout='circular',shape='slot',size=.25,slot_length=.65,gap=.15,margin=.1,
    tangential_orientation=True,start_radius=.45,spread_radius=1.3,clip_boundary=True)
_,custom,count=entry.parametric.build(comp.xYConstructionPlane,s,cfg)
volume=sum(b.volume for b in comp.bRepBodies);timeline=design.timeline.count
report={'passed':False};life=[]
output=Path.home()/'Library/Logs/Perfora/origin-edit-ui.json'
class Activate(adsk.core.CommandEventHandler):
 def __init__(self,session):super().__init__();self.s=session;self.done=False
 def notify(self,args):
  if self.done:return
  self.done=True;s=self.s
  assert entry.model.native(s.inputs['center_point'].selection(0).entity)==anchor
  assert s.chosen('orientation',entry.ORIENTATIONS)=='tangential'
  assert abs(s.inputs['spread_radius'].value-1.3)<1e-9
  s.updating=True
  try:
   s.inputs['center_point'].clearSelection();s.inputs['center_point'].addSelection(replacement)
   s.inputs['spread_radius'].expression='9 mm'
   s.inputs['preview_mode'].listItems.item(1).isSelected=True
   s.inputs['preview'].value=True
  finally:s.updating=False
  s.update_visibility();s.command.doExecutePreview()
  report.update(passed=True,stage='ready',restored_point=True,restored_tangential=True)
  output.write_text(json.dumps(report,indent=2))
class Created(adsk.core.CommandCreatedEventHandler):
 def notify(self,args):
  session=entry._sessions[-1];session.inputs['preview'].value=False
  h=Activate(session);life.extend([session,h]);args.command.activate.add(h)
definition=app.userInterface.commandDefinitions.itemById(entry.parametric.EDIT_COMMAND_ID)
h=Created();life.append(h);definition.commandCreated.add(h)
app.userInterface.activeSelections.clear();app.userInterface.activeSelections.add(custom)
def finish(committed=False):
 assert app.userInterface.activeCommand!=definition.id
 try:
  assert report['passed']
  expected=replacement if committed else anchor
  assert entry.model.native(entry.parametric.center_entity(custom))==expected
  assert abs(custom.parameters.itemById('spread_radius').value-(.9 if committed else 1.3))<1e-9
  assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
  assert design.timeline.count==timeline
  if not committed:assert abs(sum(b.volume for b in comp.bRepBodies)-volume)<1e-8
  report.update(transaction='OK' if committed else 'Cancel',transaction_passed=True)
 finally:
  definition.commandCreated.remove(h)
  doc.close(False);original.activate()
  report['original_unchanged']=(original_design.timeline.count==original_timeline and
    abs(sum(b.volume for b in original_design.rootComponent.bRepBodies)-original_volume)<1e-8)
  output.write_text(json.dumps(report,indent=2))
 print('PERFORA_ORIGIN_EDIT_UI',report)
builtins._perfora_origin_edit=globals().copy()
definition.execute()
