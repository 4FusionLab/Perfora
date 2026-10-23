# Changelog

## 0.2.0 — 2026-10-23

- Voronoi as the thirteenth hole shape, with reproducible seeds, irregularity, minimum web, exact trimming, and optional tangent corner rounding.
- Experimental Feature output: a parametric Perfora timeline node with editable pattern parameters, upstream dependencies, and a custom compute handler. Sketch and native Extrude remain available.
- All 13 shapes, exact trimming, rounded Voronoi holes, cached Fast and transactional Full Preview; straight Distance extrusion with Join, Cut, Intersect, and New Body.
- Edit Feature restores pattern settings and expressions, with Cancel and Undo/Redo. Autodesk Preview API requires the add-in to remain running.
- Exclude Fusion-generated `.vscode` configuration from installation and ZIP archives.
- Native Fusion acceptance on macOS: all 13 shapes, recompute, Edit Feature, Full Preview rollback, Undo/Redo, and F3D archive reopen. Restart Fusion when switching linked copies from different folders; native Windows CAD acceptance remains outstanding.

## 0.1.5 — 2026-10-23

First public experimental release of Perfora by 4FusionLab.

- Twelve hole shapes, rectangular and staggered distribution, web thickness, edge offsets, independent rotations, and placement offsets.
- Exact trimming of boundary cells, including clearance around inner openings.
- Sketch profiles and perforated panels; native Join, Cut, Intersect, New Body, and New Component Extrude operations.
- Cached contour previews and optional full CAD previews.
- English dialog with native Fusion terminology and operation icons.
- Project artwork, macOS/Windows installer with backups, portable ZIP, SHA-256 checksum, and automated release checks.
- Stable command ID and document attribute namespace for installations previously named Perforator.

### Known limits

Planar geometry only. No custom parametric feature to regenerate the complete pattern. Windows CAD behavior, complex assemblies, and document save/reopen still need acceptance testing. Use experimental builds on copies of working designs.
