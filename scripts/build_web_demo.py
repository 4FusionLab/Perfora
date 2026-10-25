# SPDX-License-Identifier: GPL-3.0-only
"""Build one static HTML playground with the actual Perfora Python kernel.

No JS geometry port, build dependencies, external services or publication.
Pyodide is downloaded by the browser on first use, on a pinned version.
"""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from demo.engine import compute,LAYOUTS
from Perfora.geometry import VARIANT_LAYOUTS, ORGANIC_SHAPES
from Perfora.organic import LABELS as ORGANIC_LABELS

SHAPES=(('circle','Circle'),('hexagon','Hexagon'),('square','Square'),('slot','Slot'),
        ('triangle','Triangle'),('rectangle','Rectangle'),('diamond','Diamond'),('ellipse','Ellipse'),
        ('pentagon','Pentagon'),('octagon','Octagon'),('cross','Cross'),('star','Star')) + tuple(zip(ORGANIC_SHAPES,ORGANIC_LABELS)) + (('voronoi','Voronoi'),)
LABELS={'staggered':'Staggered','rows':'Rectangular','circular':'Circular','path':'Along Path','contour':'Contour',
        'fan':'Fan','phyllotaxis':'Phyllotaxis','poisson':'Poisson Disk','wave':'Wave','chevron':'Chevron','between_curves':'Between Curves'}
MODULES=('Perfora/__init__.py','Perfora/geometry.py','Perfora/curves.py','Perfora/curve_layout.py',
         'Perfora/distributions.py','Perfora/distribution_fields.py','Perfora/organic.py','studies/__init__.py',
         'studies/source_fixtures.py','demo/__init__.py','demo/engine.py')


def build():
    sources={name:(ROOT/name).read_text(encoding='utf-8') for name in MODULES}
    try:
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError,subprocess.CalledProcessError):
        base_commit=None  # Extracted source ZIPs still carry exact module hashes.
    source=dict(base_commit=base_commit,
                sha256={name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()})
    initial=compute({'layout':'wave','shape':'slot','size':1.7})
    gallery=[]
    for name in LAYOUTS:
        boundary='rounded' if name=='contour' else 'disk' if name=='phyllotaxis' else 'rectangle'
        result=compute({'layout':name,'shape':'circle','boundary':boundary,'width':60,'height':50,
                        'size':3.5,'gap':1.4,'margin':1.5,'amplitude':3.5,'wavelength':30,'rays':15,'guide_rows':7})
        x,y,w,h=result['box'];pad=max(w,h)*.04
        svg=f'<svg viewBox="{x-pad} {y-pad} {w+2*pad} {h+2*pad}" aria-hidden="true"><path d="{result["outer"]} {result["holes"]}" fill="#46534b" fill-rule="evenodd"/></svg>'
        gallery.append(f'<button type="button" class="pattern-tile" data-layout="{name}" aria-pressed="false">{svg}<span>{LABELS[name]}</span></button>')
    bundle=dict(sources=sources,source=source,worker=(ROOT/'demo/worker.js').read_text(),initial=initial,variants=VARIANT_LAYOUTS)
    data=json.dumps(bundle,separators=(',',':')).replace('<','\\u003c')
    template=(ROOT/'demo/app.html').read_text()
    options=''.join(f'<option value="{key}"'+(' selected' if key=='slot' else '')+f'>{label}</option>' for key,label in SHAPES)
    replacements={'__STYLES__':(ROOT/'demo/style.css').read_text(),'__APP_SCRIPT__':(ROOT/'demo/app.js').read_text(),
                  '__BUNDLE__':data,'__GALLERY__':''.join(gallery),'__SHAPE_OPTIONS__':options,
                  '__LOGO__':'data:image/png;base64,'+base64.b64encode((ROOT/'Perfora/resources/toolbar-f692fbb3/64x64.png').read_bytes()).decode()}
    for key,value in replacements.items():template=template.replace(key,value)
    return template


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'demo/index.html')
    args=parser.parse_args()
    text=build();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(text,encoding='utf-8')
    print(str(args.output))
    print(f'{len(text.encode()):,} bytes; {len(LAYOUTS)} Distribution families; {len(SHAPES)} hole shapes; shared Python kernel.')


if __name__=='__main__':main()
