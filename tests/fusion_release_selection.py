# SPDX-License-Identifier: GPL-3.0-only
"""Native preselection test. Keep returned namespace; click actual Cancel then finish()."""
import json
from pathlib import Path
import runpy
import sys
import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
fixture=runpy.run_path(str(root/'tests/fusion_release_integration.py'),init_globals={'only_cases':('__fixtures_only__',)})
app=adsk.core.Application.get();original=app.activeDocument
mixed=globals().get('mixed',True)
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
component=adsk.fusion.Design.cast(app.activeProduct).rootComponent
body1,first=fixture['face_fixture'](component,'cylinder')
body2,second=fixture['face_fixture'](component,'cone' if mixed else 'cylinder',4)
baseline=(component.parentDesign.timeline.count,tuple(b.volume for b in (body1,body2)))
report=dict(passed=False,mixed=mixed,fusion=app.version)
output=Path.home()/'Library/Logs/Perfora'/('selection-mixed.json' if mixed else 'selection-same-kind.json')

def check():
    s=entry._sessions[-1]
    source=s.inputs['source']
    kinds=[entry.multi_region.source_kind(source.selection(i).entity) for i in range(source.selectionCount)]
    assert source.selectionCount==(1 if mixed else 2),(source.selectionCount,kinds)
    assert set(kinds)=={'cylinder'},kinds
    report.update(selection_passed=True,selected=source.selectionCount,kinds=kinds)
    output.write_text(json.dumps(report,indent=2));return report

def finish():
    try:
        assert app.userInterface.activeCommand!=entry.COMMAND_ID
        assert report.get('selection_passed')
        assert component.parentDesign.timeline.count==baseline[0]
        assert all(abs(b.volume-v)<1e-8 for b,v in zip((body1,body2),baseline[1]))
        report.update(passed=True,cancel_passed=True)
    finally:
        doc.close(False);original.activate()
        output.write_text(json.dumps(report,indent=2))
    return report

ui=app.userInterface;ui.activeSelections.clear()
assert ui.activeSelections.add(first)
assert ui.activeSelections.add(second)
ui.commandDefinitions.itemById(entry.COMMAND_ID).execute()
