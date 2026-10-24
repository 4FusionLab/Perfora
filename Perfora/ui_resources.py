# SPDX-License-Identifier: GPL-3.0-only
"""Resolve Fusion's own themed UI graphics from its current installation."""
from pathlib import Path

import adsk.core


_contents = next((p for p in Path(adsk.core.__file__).resolve().parents
                  if (p / 'Libraries/Applications/Fusion/Fusion/UI/FusionUI/Resources').is_dir()), None)
_fusion = (_contents / 'Libraries/Applications/Fusion/Fusion/UI/FusionUI/Resources') if _contents else None
_base = (_contents / 'Libraries/Neutron/Neutron/UI/Base/Resources') if _contents else None

_paths = {
    'profiles': ('fusion', 'sketch/Sketch_feature'),
    'extrude': ('fusion', 'solid/extrude'),
    'join': ('fusion', 'Modeling/BooleanAdd'),
    'cut': ('fusion', 'Modeling/BooleanSubtract'),
    'intersect': ('fusion', 'Modeling/BooleanIntersect'),
    'body': ('fusion', 'Modeling/BooleanNewBody'),
    'component': ('fusion', 'Modeling/BooleanNewComponent'),
    'one': ('base', 'Direction/LeftSide'),
    'two': ('fusion', 'Modeling/BothSide'),
    'symmetric': ('base', 'Direction/Symmetric'),
    'distance': ('fusion', 'Modeling/ExtrudeExtents/distance'),
    'object': ('fusion', 'Modeling/ExtrudeExtents/to'),
    'all': ('fusion', 'Modeling/ExtrudeExtents/all'),
    'profile': ('fusion', 'Modeling/ExtrudeFrom/FromSketch'),
    'offset': ('fusion', 'Modeling/ExtrudeFrom/FromOffset'),
    'reverse': ('fusion', 'Modeling/FlipDirection'),
    'staggered': ('fusion', 'pattern/distribution/hex'),
    'rows': ('fusion', 'pattern/distribution/square'),
    'circular': ('base', 'PatternCmd/circular'),
}


def icon(key):
    if key == 'feature':
        return str(Path(__file__).parent / 'resources/toolbar-f692fbb3')
    if key not in _paths:
        return ''
    root_name, relative = _paths[key]
    root = _fusion if root_name == 'fusion' else _base
    folder = root / relative if root else None
    return str(folder) if folder and folder.is_dir() else ''
