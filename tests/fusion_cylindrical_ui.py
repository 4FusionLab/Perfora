# SPDX-License-Identifier: GPL-3.0-only
"""Compatibility entry point for the common curved-face UI acceptance."""
from pathlib import Path
import runpy

_options={k:globals()[k] for k in ('mode','shape','result_type') if k in globals()}
globals().update(runpy.run_path(str(Path(__file__).with_name('fusion_surface_ui.py')),init_globals=_options))
