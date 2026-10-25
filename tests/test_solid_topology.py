# SPDX-License-Identifier: GPL-3.0-only
"""Actual point-identity implementation, loaded without the Fusion runtime."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest


class SolidTopologyTests(unittest.TestCase):
    def test_copied_kernel_points_match_across_rounding_and_bucket_boundaries(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'Perfora/solid.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PointKeys')
        ns={'math':math};exec(compile(ast.Module(body=[node],type_ignores=[]),'solid.py','exec'),ns)
        index=ns['PointKeys']()
        def point(x,y,z):return SimpleNamespace(asArray=lambda:(x,y,z))
        for x in (.00640625,.14647285846509303,-.10989145242570403):
            a=index.key(point(x,.183573686207,-.22))
            self.assertEqual(a,index.key(point(x-1e-8,.183574681323,-.22)))
            self.assertEqual(a,index.key(point(math.nextafter(x,math.inf),.183573686207,-.22)))
            self.assertNotEqual(a,index.key(point(x+1e-5,.183573686207,-.22)))


if __name__=='__main__':unittest.main()
