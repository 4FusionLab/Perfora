# SPDX-License-Identifier: GPL-3.0-only
"""Actual kernel parity and static package checks for the browser playground."""
import hashlib
import json
import math
from pathlib import Path
import re
import unittest
from demo.engine import compute,prepare,LAYOUTS,cell_path
from Perfora.geometry import generate,SHAPE_IDS,dist

ROOT=Path(__file__).resolve().parents[1]


class WebDemoTests(unittest.TestCase):
    def test_all_distribution_families_use_actual_shared_cells(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                data={'layout':layout,'shape':'slot','size':1.7}
                region,settings,guides=prepare(data)
                actual=generate(region,settings)
                result=compute(data)
                self.assertEqual(result['count'],len(actual))
                self.assertEqual(result['holes'],' '.join(cell_path(c) for c in actual))
                self.assertEqual(result['first_center'],actual[0].center)

    def test_all_hole_shapes_generate_real_preview_geometry(self):
        for shape in SHAPE_IDS:
            with self.subTest(shape=shape):
                result=compute({'shape':shape,'layout':'chevron','arm_width':.8,'size':7 if shape=='voronoi' else 5 if shape in ('smooth_noise','reaction_diffusion','directional_fibers','topographic','gyroid','blue_noise') else 2.5})
                self.assertGreater(result['count'],5)
                self.assertTrue(0<result['open_area']<100)
                self.assertTrue(result['holes'].startswith('M'))

    def test_settings_change_geometry_and_circular_center_is_preserved(self):
        a=compute({'layout':'wave','shape':'slot','size':1.7})
        b=compute({'layout':'wave','shape':'slot','size':1.7,'amplitude':10})
        self.assertNotEqual(a['holes'],b['holes'])
        region,s,guides=prepare({'layout':'circular'})
        self.assertEqual(sum(dist(c.center,(0,0))<1e-8 for c in generate(region,s)),1)

    def test_hidden_invalid_fields_do_not_block_another_layout(self):
        a=compute({'layout':'rows','shape':'circle'})
        b=compute({'layout':'rows','shape':'circle','star_ratio':'bad','amplitude':'bad','length':-10,'angle':'bad'})
        self.assertEqual(a['holes'],b['holes'])

    def test_invalid_or_unbounded_inputs_are_rejected(self):
        for data in ({'width':float('inf')},{'shape':'unknown'},{'layout':'running_bond'},
                     {'layout':'wave','amplitude':-3},{'gap':0}):
            with self.subTest(data=data),self.assertRaises(ValueError):compute(data)

    def test_generated_demo_embeds_exact_sources_without_local_paths(self):
        from scripts.build_web_demo import build,MODULES
        html=build()
        data=json.loads(re.search(r'<script id="demo-bundle" type="application/json">(.*?)</script>',html,re.S).group(1))
        for name in MODULES:
            self.assertEqual(data['sources'][name],(ROOT/name).read_text())
            self.assertEqual(data['source']['sha256'][name],hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
        self.assertNotIn('/Users/',html)
        self.assertNotIn('__BUNDLE__',html)
        self.assertNotIn('study-shift',html)
        self.assertNotIn('Additional Bridges',html)
        self.assertNotIn('export-svg',html)
        self.assertNotIn('export-png',html)
        self.assertEqual(html.count('class="pattern-tile"'),11)
