# SPDX-License-Identifier: GPL-3.0-only
"""One self-contained HTML visual regression from the actual geometry kernel.

python3 scripts/visual_distribution_test.py --output /path/distributions.html
No Fusion, browser, network or optional raster dependencies are required.
"""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studies.build_distribution_demo import main

if __name__=='__main__':main()
