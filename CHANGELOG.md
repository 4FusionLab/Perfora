# Changelog

## 1.0.0 — 2026-10-24

First stable release of Perfora. Published as a normal GitHub release and marked Latest.

### Pattern, placement, and usability

- Add six Fast Preview colors, defaulting to Gold, and thicker contours; color selection reuses prepared geometry. Fusion selection highlighting can still tint/cover contours.
- Select Feature by default on initial command activation; retain later user changes.

- Fix face-backed sketch profiles: resolve their support at the correct timeline position, restore the caller marker, and infer Objects from the supporting body for Cut/Intersect (and Feature Join). Split Face is not required.

### Performance

- Filter nearby boundary edges before exact clearance checks; keep a direct path for tiny patterns and preserve enclosed-void checks.
- Skip no-op Voronoi half-plane clipping without changing neighbor order, Seed, cleanup, or corner-rounding predicates.
- Share one immutable cell layout between Fast Preview and final construction; key it by the full Region, resolved Settings, and plane frame, with fresh source reads before building.
- Defer panel-only clipping Booleans until Panel is requested, and publish a cached panel only after all operations succeed.
- Cache source, inset, and radial spread separately; invalidate preview source data when native body/sketch revisions or the plane basis change.

### Parametric placement

- Add Spread Radius (0 = full boundary) for all distributions with bounded candidate generation, exact circular trimming, and a native model parameter on new Feature nodes.

- Retain the selected center as a Feature dependency with recompute, replacement, and clearing in Edit Feature.
- Add global Start Point selection for all distributions using sketch points, vertices, and construction points, shared by Fast/Full Preview and final geometry.
- Add explicit Tangential orientation alongside Fixed and Radial.

- Restore defaults for all 36 numeric inputs when left empty, including integer fields; preserve explicit zeros, valid replacement text, Fusion unit/parameter expressions, and nonempty validation errors.
- Normalize implicit field units before passing expressions to native Extrude and release pending default callbacks when the command closes.
- Add Circular distribution for the 12 repeating hole shapes, with automatic concentric rings, Start Radius, and Fixed/Radial orientation.
- Preserve minimum web with chord spacing and conservative enclosing bounds, including the closing ring seam; keep exact trimming, previews, and native Extrude operations.
- Circular placement offsets move the center in sketch axes without periodic wrapping; Voronoi retains its own distribution.

### Documentation and validation

- Add real Fusion gallery screenshots for circular orientation, point-based spread, face-backed profiles without Split Face, and radius-driven Feature recompute.
- Publish reproducible benchmark scenarios and measured results, separating pure Python generation from native Fusion preview/build.
- Preserve the stable command ID, manifest UUID, document attributes, and GPL-3.0-only licensing.
- Native CAD acceptance is recorded for Fusion 2706.1.14 on macOS 27.0.1. Windows CI covers Python and packaging; native Windows CAD is not claimed as tested.

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
