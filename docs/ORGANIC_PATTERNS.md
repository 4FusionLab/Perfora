# Perfora organic patterns

[Русская версия](ORGANIC_PATTERNS.ru.md)

Perfora 1.1.0 groups six noise fields and Voronoi under Noise. Existing shape identifiers, command ID, manifest UUID, attributes, and Feature schemas 1/2 are preserved.

## Shapes and algorithms

| Field | Pattern and behavior | Main controls |
| --- | --- | --- |
| Smooth Noise | Two-dimensional gradient noise with quintic interpolation and an additional octave; irregular rounded openings | Cell Size, Pattern Angle, Seed |
| Reaction Diffusion | Actual iterative Gray–Scott reaction–diffusion; coral-like and maze-like slots | Cell Size, Pattern Angle, Seed |
| Directional Fibers | Anisotropic gradient noise with smooth warping; elongated slots with cross bridges | Cell Size, Pattern Angle, Seed |
| Ridged Noise / Topographic | Periodic levels of low-frequency terrain with an absolute-value noise field; nested arcs and strips joined by material | Cell Size, Pattern Angle, Seed |
| Gyroid Field | Cross-section of `sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x)` by a plane normal to (1,1,1), with phase determined by Seed | Cell Size, Pattern Angle, Seed |
| Blue Noise / Size Gradient | Reproducible packing of variable-radius circles, checking the sum of both radii and Web Thickness | Maximum Diameter, Size Variation, Size Gradient, Direction, Seed |

Gyroid Field produces planar contours for straight tools, not a volumetric TPMS lattice. Blue Noise complements the existing Poisson Disk: the latter retains equal shape and size, while the new mode varies radii. Spectral blue-noise optimization is not claimed.

Gray–Scott is calculated on a periodic 128×128 grid: 1,000 steps, dt=1, Du=1, Dv=0.5, feed=0.04, kill=0.06. The nine-point Laplacian uses weights −1 at the center, 0.2 at the sides, and 0.05 on diagonals. Seed determines the initial disturbances. Immutable fields for the last three Seeds are cached in a bounded numeric cache without Fusion objects. The solver's base period is 128/12 Cell Size. Smooth nonperiodic coordinate warping removes literal tile repetition; similar motifs may still be recognizable over a large area. Changes to scale, threshold, or direction reuse the field already calculated for the same Seed.

Algorithm references: [Ken Perlin's gradient noise](https://cs.nyu.edu/~perlin/noise/) and [Karl Sims' explanation of Gray–Scott](https://www.karlsims.com/rd.html). The implementation is independent, in standard Python, without third-party runtime dependencies.

## Controls

**Add Bridges** is a separate checkbox, off by default. It adds local cross connections to long slots; without it the field's natural pattern remains. Mandatory material-connectivity and Web Thickness protection remains active. The checkbox is hidden for Blue Noise, stored in Feature, and restored in Edit Feature and when opening F3D.

Cell Size is the physical field scale in length units, not the uniform width of every opening. Web Thickness sets the minimum web. The internal field threshold depends on the shape; the old Field Fill is retained only for existing Feature compatibility. Thickened webs, bridges, rounded ends, offsets, and trimming reduce the final open area.

For Blue Noise, Maximum Diameter is the largest diameter. Size Variation of 65% permits diameters from 35% to 100% of that value; at 0% sizes are equal. Size Gradient from −100% to +100% controls directional size variation: 0% gives random sizes, +100% increases along Direction, and −100% reverses that direction. Intermediate values mix the gradient with random variation.

Pattern Angle rotates the complete motif; Seed / New Pattern are reproducible for the same source and settings. Distribution and Hole Angle are hidden: these shapes define their own field and do not combine with Circular, Along Path, or the eight additional Distributions. Switching back to a repeating shape restores the selected layout. An API call with an incompatible combination is rejected explicitly, without substituting an algorithm.

Start Point and X/Y Offset preserve the field phase in its own axes. Multiple planar regions use common component axes and origin, as in the shared command. Threshold, bridge topology, and final packing are resolved separately within each region's window; neighboring windows are not crops of one infinite completed grid. Changing source bounds may change openings and their count. Overlapping regions are prohibited.

## Webs, contours, and cost

Material on the grid is connected using a minimum spanning forest of shortest raster paths. With Add Bridges enabled, long slots are further divided by bridges; cross cuts do not impose one regular grid on the entire panel. Euclidean distance then thickens the material with allowance for grid diagonals and approximation. A bounded signed distance field is smoothed, rounding ends and removing needle-like protrusions. A bridge crosses only one local slot branch, not an entire row of openings. Contours are uniformly resampled and adaptively approximated with cubic curves with matched tangents. In Fusion these are exact cubic NURBS; the same curves feed Fast Preview, trimming, Sketch, and straight extrusion.

Closure, self-intersections, and distances between final contours are checked. When a narrow slot splits into multiple openings, the new webs are checked separately: a narrow connection is thickened locally and contours are extracted again. Only remaining conflicting small fragments are omitted after a bounded number of refinements. Enclosing bounds do not replace this planar check. Whole openings account for the outer edge and inner cutouts; their selection is conservative within curve-sampling tolerance. Trim to Boundary retains safe partial openings with the active exact Edge Offset. Selecting an organic shape in a new command automatically enables trimming; returning to a repeating shape restores the previous toggle. This initial behavior does not override saved Features.

With Edge Offset near zero, an exact material check rejects a local opening fragment that would create a separate island: it remains material. A positive offset is not silently increased to Web Thickness. Connectivity is a geometric safeguard, not a strength, fatigue, or manufacturing calculation.

Sampling step is Cell Size / 16 for previously permitted regions; on large regions it adapts up to Cell Size / 8, retaining the node limit and physical field scale. Curve approximation tolerance is 0.22 of a step. Details smaller than the resolution may disappear. The field budget is 120,000 nodes including a protective halo; accepted contours have a budget of 16,000 edges plus a bounded preliminary budget. Maximum Holes remains 1–5,000, counted across regions. An overly dense request ends with an actionable error suggesting a larger scale or smaller region. CAD time also depends on edge count, boundary complexity, and curvature.

## Surfaces and results

| Source | Placement and limitations |
| --- | --- |
| Planar face, planar profile, Construction Plane | All six fields in physical plane coordinates; exact trimming with inner contours |
| Cylinder | Circumference/axis map; centers wrap periodically, seam duplicates are removed; finite tools are separated through depth |
| Cone | Centers adapt to local circumference; tools retain size; areas near the axis/apex and slots too long for Distance are skipped locally |
| Freeform | Existing adapter's physical map, local normals, and the same exact mask; singularities and unsuitable local areas do not exclude the rest of the face |

On a curved face, Direction 0° corresponds to the circumferential/first map axis; 90° corresponds to the cylinder axis, cone meridian, or second freeform-map axis. Fibers can run along or across the axis. Separating planes can shorten organic contours and make the pattern sparser at high curvature. A web is preserved at the seam; continuous random-field continuation across an arbitrary circumference is not guaranteed. These are straight finite tools, not geodesic slots or a planar sketch wrapped onto the surface.

Slots too long for local projection are omitted. If no openings remain, build or recompute fails. Reduce Cell Size, enable Add Bridges, or increase Distance within permitted limits.

Sketch produces fixed contours, using the existing 3D-contour path on curved surfaces. Extrude produces a fixed native Extrude on a plane or Base Feature/Combine on a curved surface. Feature retains settings and native parameters, dependencies, Edit Feature, and recompute. Existing restrictions on Distance, zero Taper, operations, and fixed sources/Objects remain. New fields on old nodes receive defaults; if a node predates those native parameters, editable numeric values are kept in a snapshot. Recreate Feature to obtain new expression dependencies.

Selection of up to 32 regions remains homogeneous by surface type. Planes, cylinders, cones, and freeform surfaces cannot be mixed. The existing conservative finite-tool check applies between curved regions.

## Validation

UI validation recorded on 2026-10-25: Pattern/Noise sections, all 19 shapes, Voronoi last in Noise, and default Magenta were checked in the loaded copy of Fusion 2706.1.14 on macOS. Thirty-six browser scenarios passed, including switching sections with settings restored and a 360 px mobile width. A Feature recompute failure was fixed: Objects are retained through upstream faces and references are bound before a Boolean can remove the selected face. The timeline after Edit Feature is restored through `commandTerminated`.

The loaded copy was used to check creation and Cell Size changes for all six fields and Voronoi on copies of a selected Box face. Smooth Noise was also checked on a cylinder, cone, and freeform face; a planar Feature recomputed after reopening a local F3D. Real Edit Feature OK/Cancel and Undo/Redo for both the complete command and editing passed. Multiple regions were checked with Cut, Join, Intersect, and New Body. An old node with a reproduced cyclic dependency was recovered and checked by changing size and source thickness. Original user documents were not modified. This was macOS validation; it does not establish cloud-save or Windows CAD behavior.

Local invariants: `python3 -m unittest discover -s tests -v`. `test_organic.py` checks six different reproducible fields, actual contour clearances, the material-connection graph, Euclidean distance, radii/gradient, directions/phase, offsets/inner cutouts, budgets, cache, and versioned parameters. `test_solid_topology.py` checks matching kernel-point copies near rounding boundaries; stitching is additionally checked in real Fusion.

`fusion_organic_regression.py` uses the actually loaded copy: plane/cylinder/cone/freeform, all six shapes, Sketch/Extrude/Feature, Trim on/off, matching Fast/final counts, body validity and no new lumps, and actual volume change after recompute. `archive=True` exports separate local F3Ds, reopens them, and recomputes again; `capture=True` saves real images.

`fusion_organic_ui.py` checks native control visibility, Fast/Full Preview, real OK/Cancel, Edit Feature OK/Cancel, and Undo/Redo in a separate document. Only a successful check after pressing the button counts as transaction acceptance. Temporary reports, images, archives, and timings stay outside the repository and ZIP. This validation does not establish cloud-save, Windows CAD, or arbitrary imported-surface behavior.

In the interface, **Pattern Type → Noise** groups these six fields with **Voronoi** last. The main controls for new noise fields are Cell Size (8 mm), Web Thickness (0.8 mm), Edge Offset, and Seed. Fill percentage is hidden; the previous value is retained only for compatibility with existing Features. Additional settings are grouped under Field Options. Fast Preview defaults to Magenta.

`fusion_feature_dependency_regression.py` reproduces the old late BRepBody binding, checks node recovery and source-thickness changes. `fusion_selected_noise_regression.py` checks real Features on copies of a selected body: healthy status, restored Objects, and volume change after changing Cell Size.
