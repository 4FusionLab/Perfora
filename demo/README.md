# Perfora — Pattern playground

[Русская версия](README.ru.md)

A public browser demo and standard bench for quick visual pattern checks. Fusion and the browser use **the same Perfora geometry kernel**. The sources `Perfora/geometry.py`, `organic.py`, `distributions.py`, `distribution_fields.py`, `curves.py`, and `curve_layout.py` are embedded in the page unchanged and executed in Python via Pyodide 0.27.7 in a separate Web Worker. JavaScript handles input, display of completed contours, and links. Export was excluded by user decision. There is no separate JavaScript implementation of layouts. Module composition and SHA-256 values are available in `perforaDemo.source`.

## Features

- Pattern: 12 repeating shapes and 11 Distribution families.
- Noise: Smooth Noise, Reaction Diffusion, Directional Fibers, Topographic, Gyroid Field, Blue Noise, and Voronoi last. Distribution is hidden.
- Running Bond is combined with Staggered; there is no separate Row Shift control.
- Rectangle/Rounded/Circle boundary, panel and hole dimensions, Web Thickness, Edge Offset, orientation, and selected-pattern parameters.
- Cell Size and Web Thickness instead of fill percentage; Voronoi retains Cell Spacing, Irregularity, and Round Corners. Seed/New Pattern and links with parameters are supported.
- Geometry is recalculated in the browser; no compute server or API keys are needed. The first run requires internet access to load the pinned Pyodide version from jsDelivr. The page contains a ready first pattern, so it does not open empty during loading. Panel contours are not sent to a server.

All six noise shapes use the shared Python kernel. Add Bridges applies to the first five fields and is enabled separately from Web Thickness. Ordinary Distributions have no additional bridges.

## Build and run locally

```sh
python3 scripts/build_web_demo.py
python3 -m http.server 8768 --bind 127.0.0.1
```

Open `http://127.0.0.1:8768/demo/`. The only file needed for hosting is `demo/index.html`: styling, logo, Python modules, and initial examples are already embedded. It can be hosted in a GitHub Pages artifact or another static HTTPS host. An HTTP server is preferred locally; `file://`, Web Worker, and clipboard restrictions vary by browser. Preparing the page is not publication: push, Pages setup, and deployment are performed only on separate user instruction.

The builder does not modify the Fusion installation, require third-party Python packages, or download dependencies. The Pyodide version is pinned in `worker.js`; repeat real browser validation when changing it. [Pyodide](https://github.com/pyodide/pyodide) is loaded separately and retains its own license terms.

## Checking changes

1. Change algorithms in the shared Python kernel. Explicitly version a new pattern; existing Features continue using their previous revision.
2. Run `python3 -m unittest discover -s tests -v` and rebuild the page. `tests/test_web_demo.py` checks real contours, every shape and family, hidden fields, limits, and exact source embedding.
3. Open the freshly built page. `browser-smoke.js` contains a Playwright scenario covering every Distribution and shape, parameter changes, link restoration, invalid input, Reset, and a narrow screen. It creates a separate tab and returns parameters and hashes of the resulting contours. Compare hashes/coordinates with `demo.engine.compute()` for the same inputs. Visually inspect affected patterns and both ordinary and narrow screens.
4. Then perform the CAD acceptance relevant to the change from [CONTRIBUTING.md](../CONTRIBUTING.md). A web check does not establish BRep, operations, curved-surface seams, native dialog behavior, transactions, or Custom Feature recompute in Fusion.

Planar version 2 currently supports whole holes; partial BRep trimming and curved-surface display remain native integration stages. For other shapes, version 2 conservatively checks clearance using circumscribed circles; circles and slots use exact capsule distance. The demo is a visual bench and does not create production files. Open area is a geometric estimate for the displayed holes. With rounded Voronoi, the estimate uses the original polygon and may be slightly high.

## Page sources

- `engine.py` — input and display adaptation over the shared kernel.
- `app.html`, `style.css`, `app.js` — interface.
- `worker.js` — isolated Python execution.
- `scripts/build_web_demo.py` — build, examples, and provenance checks.

The project code is licensed under PolyForm Noncommercial 1.0.0. Derived HTML pages retain the project license; embedded source code is available within the file.
