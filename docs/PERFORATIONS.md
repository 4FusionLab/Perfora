# Perforation shapes

[Русская версия](PERFORATIONS.ru.md)

> **Historical development reference.** This document combines Perfora 1.0.0 behavior with development notes; statements that features are unreleased or untested describe their original stage. For the released 1.1.0 scope and recorded acceptance, see the [release notes](releases/v1.1.0.md) and [integration report](RELEASE_INTEGRATION.md).

Based on manufacturer catalogs checked on 23 October 2026.

Perforation is determined by more than hole shape: size, web, pitch, straight, staggered or circular arrangement, rotation, offset, and open-area ratio all matter. In the add-in, cell shape is separate from grid placement and the Extrude operation.

| Type | Variants | Support in Perfora 1.0.0 |
| --- | --- | --- |
| Basic openings | Circle, square, hexagon | Diameter, side length, or across-flats size |
| Slotted | Rectangular slot and slot with rounded ends | Rectangle and slot; width and full length |
| Geometric | Triangle, diamond, ellipse, pentagon, octagon | Separate rotatable shapes |
| Decorative | Stars, crosses, clover, floral and mixed patterns | Cross with arm width; star with 3–12 points and inner radius |
| Formed | Louvered, drawn and embossed openings | Require a separate 3D operation; a planar outline and Extrude do not reproduce this geometry |
| Patterns and variable density | Multiple sizes/shapes, images made of holes | A possible separate extension; the current command repeats one shape and size |

## Circular layout

Distribution → Circular is available for the 12 repeating shapes; Voronoi uses its own distribution. Holes are placed in concentric rings, with each ring's count chosen by chord spacing. In the development branch, rings contain opposite pairs; odd capacity is rounded down to an even number while preserving the minimum web. The first ordinary ring contains six holes regardless of boundary shape. The central circle remains single. Ring spacing equals the diameter of the circle enclosing a hole plus Web Thickness. This preserves the minimum web with Fixed, Radial, and Tangential Orientation, but packing is conservative for elongated and angular shapes.

Start Radius is measured to centers of the first ring; 0 adds one central hole. Holes may extend inside that radius. Radial rotates holes along the radius; Tangential follows the circumference. Hole Angle adds rotation in all modes. Pattern Angle rotates the pattern around the outer boundary's bounding-box center; X/Y Offset shifts that center in sketch axes without periodicity. Trim to Boundary and Edge Offset also apply to inner cutouts; ring radii are set before trimming. On a plane, exact equality with the offset is allowed: no hidden 0.001 mm allowance is added to Edge Offset. A cell touching the offset boundary is retained whole; an actual intersection requires trimming.

## Dimensions of new cells

In the developing multi-planar-region mode, dimensions and shapes are shared across sources. The layout is anchored to the projection of the component origin and axes: coplanar regions share a phase, including Voronoi and Circular. Start Point is projected onto each plane. Edge Offset applies near each separate boundary and its inner cutouts; neighboring regions are not merged. Overlapping filled regions are rejected. Maximum Holes is counted across all regions, including separate trimmed fragments of one cell in different regions. Earlier descriptions of the automatic center apply to a single source. At that stage the feature was unreleased and had not passed CAD acceptance; see [MULTI_REGION.md](MULTI_REGION.md).

- Triangle: side of the equilateral triangle.
- Rectangle: width and length.
- Diamond: vertical and horizontal diagonals before rotation.
- Ellipse: full minor and major axes; the major axis must exceed the minor. This is an exact ellipse, not a slot with semicircular ends.
- Pentagon: diameter of the circumscribed circle.
- Octagon: distance between opposite faces.
- Cross: overall width/height and arm width.
- Star: diameter through outer vertices, number of points, and inner radius as a percentage of the outer radius.

For additional shapes, grid pitch is selected from the rotated shape's bounds so the web does not fall below the specified value. This is a safe layout; densest alternating-orientation triangle packing and mixed tilings are not implemented. Ellipse clearance checks use a circumscribed polygon, conservatively selecting whole cells. The resulting sketch contains exact ellipses and elliptical arcs.

## Voronoi

Irregular convex polygons are constructed using a Voronoi diagram. Seed points are displaced relative to a square grid; density across the area is constant. This thirteenth shape has been available since 0.2.0.

- **Cell Spacing** is nominal seed-point pitch, not hole diameter. Smaller spacing creates more cells; their actual sizes vary.
- **Irregularity (%)** ranges from 0 to 100%. At 0% cells are square; higher values produce more varied polygons.
- **Seed** is an integer from 0 to 2147483647. Identical source, Seed and settings produce the same layout in preview and final model.
- **New Pattern** increments Seed by one while retaining the other settings.
- **Round Corners** rounds cell corners with tangent circular arcs; off by default. **Corner Radius** is the maximum radius, 0.5 mm by default. Very short chamfers are absorbed by rounding instead of producing microscopic arcs; radius is reduced only when hole width is insufficient. The contour is built by offsetting the polygon inward and expanding it with a circle of the same radius. It remains inside the original cell and does not reduce the web.
- **Web Thickness** is the minimum web. Each cell is inset by half this value; a thick web can absorb small cells entirely.
- **Edge Offset**, **Trim to Boundary**, **Pattern Angle**, and X/Y offsets work as with the other shapes. Separate **Hole Angle** and ordinary **Distribution** are hidden because polygons are defined by the overall diagram.

The grid position is measured from the region's bounding-box center in the Pattern Angle frame. Offsets are periodic with Cell Spacing. Changing the boundary can move the layout center; Seed alone does not fix it in world coordinates.

Fast/Full Preview, ordinary profiles, all Extrude operations, the border, and existing inner cutouts are supported. Contours have straight sides and, with Round Corners, exact circular arcs. After trimming, new convex corners at straight/circular-arc junctions are additionally rounded. Radius is limited locally, and a temporary BRep check confirms the opening has not expanded. Original concave corners, inner closed contours, and elliptical and spline boundary segments are preserved. In whole-hole mode selection remains conservative against the original polygon. An overly dense layout is rejected before CAD construction; the hole limit remains shared across all shapes.

## Manufacturer sources

- [Graepels — Standard Perforations](https://www.graepels.com/wp-content/uploads/2024/10/standard-perforation-sizes.pdf): round, square, two slot types, diamond, hexagonal and triangular holes.
- [SCHÄFER — Perforation patterns](https://www.schaefer-lochbleche.com/en/offer/perforated-metal-from-stock/perforation-pattern/): shape, pitch, web, orientation, open area and straight/staggered arrangement.
- [Hengda — Perforated metal](https://perforated-metal.net/perforatedmetal/aboutus.html): offered shapes include diamonds, rectangles, crosses, octagons, triangles, stars and ovals.
- [Dillinger — Special perforations](https://www.df-perforatedsheets.com/en/embossed-panels-special-perforations/special-perforations-embossed-plates): star, floral and clover ornaments and formed openings.
- [Perfopol — Other perforation](https://www.perfopol.com/Other_perforation): clover, louvered, mixed and other special variants.

Catalog information describes industrial products. Add-in parameters are geometric model settings, not recommendations for strength, acoustics or manufacturing processes.

### Start Point and orientation

**Start Point** selects a sketch point, vertex, or construction point with native Select. A point outside the plane is projected onto Profiles. Without a selected point, the automatic center is used. X/Y Offset adds a shift in layout axes for grids/Voronoi and sketch axes for Circular. **Fixed**, **Radial**, and **Tangential** set hole orientation; Hole Angle adds rotation. Orientation is hidden for circles and ring settings for Voronoi. Start Point is available for all layouts.

### Limiting the area

Spread Radius was removed from the dialog. New layouts fill the selected boundary; the area is specified by a selected face, profile, or Boundary. Old Features retain the Spread Radius parameter and recompute for compatibility.

### Curved faces (development)

Shape dimensions refer to the planar cross-section of a straight tool along the surface normal. On a cylinder X follows the circumference and Y the axis; on a cone Y follows the generator with physical spacing, and each row's hole count depends on local circumference and tool depth. Rectangular retains the initial angular direction; Staggered shifts alternate rows by half the local angular pitch. Holes are added toward the base; individual columns branch as the cell count changes. On a freeform surface, local tangent axes, physical cross-section length, and inverse length-to-UV mapping are used. Repeating-shape pitch conservatively accounts for tools approaching through depth; uniformity in every direction is not guaranteed on double curvature. Hole Angle rotates the section. For example, Diameter 5 mm means tool diameter, not a constant hole arc length on the surface.

Voronoi retains Cell Spacing, Irregularity, Seed/New Pattern, and Round Corners. On a cylinder points are periodic across 360°. Separating planes between finite tools protect Web Thickness through depth, including convergence near an almost closed sector. Repeating shapes are not reduced in size: conflicting points are skipped. These are straight tools, not a geodesic surface diagram.

Trim to Boundary retains partial openings; Edge Offset applies to the original boundary, zone, and existing cutouts. Exact curve projections are preserved in the mask. A concave/degenerate offset uses conservative subtraction of strips along the boundary with an additional 0.002 mm clearance. Offset in the local projection is not geodesic. Circular and Pattern Angle are available only for planar sources; X/Y Offset remains on curved surfaces as pattern phase.

Distance, Offset, Flip Direction, One Side, Two Sides, and Symmetric define a bounded straight tool. The bottom of a blind hole is flat, not at constant depth from the surface. For a through hole, set Distance slightly greater than wall thickness and inspect Full Preview. A cylindrical/conical tool must not cross the axis. All, To Object, Taper, and Perforated Panel are unavailable on a curved face.

Sketch creates fixed 3D contours, Extrude creates fixed Base Feature/Combine, and Feature creates a parametric node with dependencies, recompute, and Edit Feature. See both READMEs for details. Spheres, tori, mesh, and transitions across multiple faces are excluded.

NURBS faces with a degenerate boundary at a single point are checked using interior parameters. Areas with an undefined local basis and trim regions containing that point are skipped separately; the remainder of the face stays available. Maximum Holes still applies and must be explicitly increased for large areas.

## New Distributions in the working branch

Contour, Fan, Phyllotaxis, Poisson Disk, Wave, Chevron, Running Bond, and Between Curves use the existing 12 repeating shapes and their dimensions. They do not combine with Voronoi. Minimum web is checked against the circumscribed circles of actual shapes regardless of rotation; this is conservative packing and may skip candidates. Along Spacing/Row Spacing at 0 are automatic; smaller spacing is raised to a safe minimum. The new generators are connected to shared trimming and Edge Offset paths.

Contour uses approximate inner-distance levels with an explicit tolerance, not an exact CAD offset. Between Curves is a bounded contract for two open planar guides in one component; complex, intersecting, or nonplanar strips are not claimed. **Current CAD/UI acceptance is recorded in [RELEASE_INTEGRATION.md](RELEASE_INTEGRATION.md).** Full control semantics, tolerances, and checks: [LAYOUT_VARIANTS.md](LAYOUT_VARIANTS.md).

## Along Path layout — in development

Along Path uses one line, arc, circle, or spline in the source plane. Path Spacing is center-to-center distance along the curve, independent of hole size and Web Thickness. Minimum web is checked between all nearby holes, including turns and the seam: exactly for circles, and using circumscribed circles for other shapes. Noncircular shapes may therefore require greater spacing than with exact contour checks. Conflicts produce an error; holes are not automatically thinned.

Start Offset, End Offset, and Position are measured to centers, not hole edges. Closed Path does not duplicate the seam; fixed spacing is not redistributed, so a short seam remainder may require parameter changes. The complete region, its inner cutouts, Edge Offset, and exact Trim to Boundary retain their existing meaning. At this stage the feature was unreleased and had not been tested in Fusion; [detailed contract and planned acceptance](CURVE_LAYOUT.md).

## Compatibility of layouts and multiple surfaces

The current matrix is in both READMEs and [RELEASE_INTEGRATION.md](RELEASE_INTEGRATION.md). Running Bond and Poisson Disk were added on cylinders; Running Bond with local row capacity on cones; and Running Bond, Poisson Disk, Wave, and Chevron on freeform surfaces. Centered layouts and planar guides remain limited to planar sources. Unsupported combinations are rejected explicitly without substituting another grid.

Multiple regions must have one surface type: planar, cylindrical, conical, or freeform. This is checked during selection and Feature construction/recompute. Maximum Holes is shared. All regions are prepared before modifying the body; webs between curved regions are checked using finite tools. Conflicting holes are not reduced in size.

## Organic fields in the working branch

Smooth Noise, Reaction Diffusion, Directional Fibers, Ridged Noise / Topographic, Gyroid Field, and Blue Noise / Size Gradient are in Hole Shape before the final Voronoi. The first five create bounded smooth fields with Pattern Scale, Field Fill, Direction, and Seed; Blue Noise produces circles of different radii with Maximum Diameter, Size Variation, and signed Size Gradient. Field Fill sets the initial quantile, not the measured open area of the finished body.

These are independent fields: Circular, Along Path, and additional Distributions do not combine with them. All six use shared Fast/Full Preview, trimming/Edge Offset, and Sketch/Extrude/Feature paths on planes, cylinders, cones, and regular freeform areas. Material islands are joined with bridges; the actual web between finished contours is checked separately. On curved surfaces a web is maintained between finite straight tools, with possible local omissions and thinning near seams, the apex, and high curvature. Multiple regions must have one surface type.

[Full contract for algorithms, dimensions, tolerances, cost, compatibility, and validation](ORGANIC_PATTERNS.md). These features were not published in 1.0.1.
