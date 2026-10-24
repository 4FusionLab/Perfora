# SPDX-License-Identifier: GPL-3.0-only
"""Offline 2D timings only. Does not import adsk or contact Fusion."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from Perfora.geometry import Settings, VARIANT_LAYOUTS, rectangle_region
from Perfora.cache import GeometryCache


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.repeat<=20: parser.error('repeat must be between 1 and 20')
    results=[]
    region=rectangle_region(8,6)
    for shape in ('circle','hexagon','slot'):
        for layout in VARIANT_LAYOUTS:
            settings=Settings(layout=layout,shape=shape,size=.3,slot_length=.7,gap=.12,margin=.15,
                              shape_angle=.47,limit=5000,contour_tolerance=.04,
                              guide1=((-3,-2),(0,-1.5),(3,-2)),guide2=((-3,2),(0,2.3),(3,2)))
            cache=GeometryCache()
            cold=[]
            for _ in range(args.repeat):
                cache.clear()
                started=perf_counter()
                cells=cache.resolve(region,settings)
                cold.append(perf_counter()-started)
            started=perf_counter()
            for _ in range(100): cache.resolve(region,settings)
            warm=(perf_counter()-started)/100
            results.append(dict(layout=layout,shape=shape,cells=len(cells),
                                cold_median_seconds=statistics.median(cold),cold_samples_seconds=cold,
                                warm_mean_seconds=warm))
    result=dict(scope='offline pure 2D; not Fusion timing or CAD acceptance',
                python=platform.python_version(),os=platform.platform(),repeat=args.repeat,
                source_sha256={name:hashlib.sha256((ROOT/'Perfora'/name).read_bytes()).hexdigest()
                               for name in ('geometry.py','distributions.py','curves.py','cache.py')},
                results=results)
    data=json.dumps(result,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(data+'\n',encoding='utf-8')
    print(data)


if __name__=='__main__': main()
