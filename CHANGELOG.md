# Changelog

## v0.6.0 — 2026-04-16

### Structured tool outputs (breaking change for some clients)

Tools in `primitives` and `query` now return Pydantic models instead of formatted
strings or `json.dumps` blobs. FastMCP serializes each model into BOTH:

- `content` (a human-readable text block via `__str__` — old clients still work)
- `structuredContent` (typed JSON the agent can read directly)

Agents no longer have to grep `"OK Created..."` or `json.loads(tool_text)` to pull
volume, bbox, or face counts out of a string.

### What changed

- **New module `caid_mcp/types.py`** — shared Pydantic result models:
  `ShapeResult`, `BoundingBox`, `Point3`, `EdgeInfo`, `FaceInfo`,
  `EdgeListResult`, `FaceListResult`, `DistanceResult`, `InspectResult`,
  `MassResult`, `NearestEdgesResult`, `NearestFacesResult`.
- **`primitives.py`** — all 7 creators return `ShapeResult`. Volume + bbox
  are reported on every successful create (no extra tool call required).
- **`query.py`** — all 7 query tools return typed models. `mass_properties`
  now constrains `material` to a `Literal[...]` of 28 names, so typos
  (`"aluminium"`) are rejected by Pydantic before the tool body runs.
- **Validated parameters** — primitives use `Field(gt=0, ...)` constraints;
  `find_*_near_point` clamps `count` to `[1, 50]`; `create_revolved_profile`
  clamps `angle` to `(0, 360]`.
- **Error semantics** — `mass_properties` raises `ToolError` (sets
  `isError: true`) instead of returning a `"FAIL ..."` string that looks
  like success to clients that only check the error flag.

### Removed parameters (breaking)

- **`inspect_object(format="text"|"json")`** — `format` parameter removed.
  Both representations are returned every call (text via `content`,
  structured via `structuredContent`). Agents pick which to read.

### Dependency updates

- `mcp>=1.25,<2` (was `>=1.2.0`). Current SDK is 1.27; v2 is in development
  with breaking transport changes — the SDK authors' own pinning advice.
- `pydantic>=2.7` added as an explicit dependency.

### Migration

Most agents need no changes — they read the `content` text block and that
still works. If you parse tool results programmatically:

- Replace string regex with `result.structuredContent.volume_mm3` (or your
  client's equivalent typed-access pattern).
- If you called `inspect_object(name, format="json")`, drop the `format`
  argument; structured fields are always present.

---

## v0.5.0 — 2026-03-29

### AI Usability Consolidation (breaking changes)

Reduced tool count from 113 to 107 by removing redundancy, merging overlapping
tools, and adding convenience features. Goal: less LLM decision fatigue.

### Removed tools (−8)

- **preview_object**, **preview_scene** — legacy redirects to render_object/render_scene
  with no quality presets, caching, or multi-view. Traps for LLMs.
- **discover_tools** — MCP protocol already provides tool metadata. Redundant.
- **set_object_layer** — redundant with `set_object_properties(name, layer=...)`.
- **get_object_info** — merged into `inspect_object`.
- **measure_object** — merged into `inspect_object`.
- **describe_shape** — merged into `inspect_object`.
- **export_all_stl** — merged into `export_stl` (omit name to export all).

### New/merged tools (+2)

- **inspect_object(name, format="text"|"json")** — unified replacement for
  get_object_info, measure_object, and describe_shape. One tool for "tell me
  about this object." Text format returns natural language, JSON format returns
  structured data. No more choosing between 5 measurement tools.

- **find_parts(query, user_library)** — searches all three part library systems
  (FreeCAD STEP library, cq_warehouse parametric parts, user script library)
  with one call. Returns combined results grouped by source with hints about
  which import tool to use.

### Merged tools (net 0)

- **export_stl** — now accepts optional `name`. Omit to export all objects.
  Replaces the separate `export_all_stl`.
- **export_brep** — moved from io module to export module. All exports now in
  one place.

### Renamed tools (breaking)

- `fillet_edges` → **fillet_solid_edges** — clarifies target is 3D solid edges
- `chamfer_edges` → **chamfer_solid_edges** — clarifies target is 3D solid edges
- `fillet_curves` → **fillet_wire_corners** — clarifies target is 2D wire corners
- `chamfer_curves` → **chamfer_wire_corners** — clarifies target is 2D wire corners

### Enhanced tools

- All 7 primitive creation tools now accept **center_x, center_y, center_z**
  parameters (default 0). Creates the shape and immediately translates it to
  the specified position. Eliminates the most common two-call pattern
  (create_box → translate_object).

### Stats

- **107 tools** across **22 modules** (down from 113). Fewer tools, less
  decision fatigue, same capabilities.

---

## v0.4.6 — 2026-03-29

### Phase 5 — Scene Organization + Phase 6 — Infrastructure (Roadmap)

Completes the entire competitive gap closure roadmap. Phase 5 adds object
properties, groups, and layers for organizing complex multi-part designs.
Phase 6 adds infrastructure polish: server info, adaptive response compression,
and flexible parameter parsing.

### New tool module: scene_org (8 tools)

- **set_object_properties(name, color, visible, locked, material, layer)** —
  Set display and organizational properties on any object. Per-object color
  overrides the default palette in render_scene. Visibility controls whether
  the object appears in renders (respects both object and layer visibility).

- **get_object_properties(name)** — Read back all properties as JSON.

- **create_group(group_name, object_names)** — Lightweight named grouping.
  Groups are organizational only — no geometry impact.

- **ungroup(group_name)** — Remove a group without affecting its objects.

- **list_groups()** — List all groups with members and detect stale references.

- **create_layer(layer_name, color, visible)** — Create organizational layers.
  Objects default to layer "0". Layer visibility hides/shows all objects on it.

- **set_object_layer(object_name, layer_name)** — Move an object between layers.

- **list_layers()** — List all layers with properties and object counts.

### New tool: server_info (in scene module)

- **server_info()** — Returns version, tool count, module list, output directory,
  and scene statistics. Useful for LLM self-orientation at conversation start.

### Infrastructure

- **Adaptive response compression** — Renders exceeding 200 KB are automatically
  downscaled (75% → 50% → 35% → 25%) until they fit. Prevents blowing up the
  LLM context window with oversized base64-encoded PNGs. Applied to render_object
  and render_scene.

- **Flexible parameter parsing** — New `parse_point()` and `parse_points()` utilities
  in core.py accept multiple coordinate formats: `[x,y,z]` lists, `{"x":1,"y":2,"z":3}`
  dicts, `"1,2,3"` strings, and 2D shorthand `[x,y]`. LLMs format parameters
  inconsistently — this forgiveness reduces tool-call failures.

- **Render pipeline visibility** — render_scene and preview_scene now respect
  object visibility and per-object colors from properties. Hidden objects are
  skipped entirely.

- **clear_scene cleanup** — Now also clears object_properties and groups.

### Stats

- **113 tools** across **22 modules** (up from 104 / 21 in v0.4.5).
- Surpasses GOLEM-3DMCP's 105 tools.
- +9 new tools, +3 infrastructure features.

---

## v0.4.5 — 2026-03-29

### Phase 3 — Advanced Curves & Surfaces (Roadmap)

Extends the curves toolkit into proper curve manipulation and surface operations.
All 6 tools added to `curves.py`.

### New tools (curves)

- **extend_curve(name, end, distance)** — Extend a curve beyond its start, end,
  or both endpoints by a given distance. Extension follows the tangent direction
  at the endpoint. Builds a new wire with the extension segments prepended/appended.

- **chamfer_curves(name, distance)** — Chamfer (bevel) all corners of a planar
  closed wire with straight-line cuts. Uses `BRepFilletAPI_MakeFillet2d.AddChamfer`
  with vertex deduplication (same pattern as existing fillet_curves).

- **join_curves(names, result_name)** — Join multiple wires/edges into one
  continuous wire. Collects all edges from each named object and feeds them to
  `BRepBuilderAPI_MakeWire`. Edges must be approximately end-to-end connected.

- **reverse_curve(name)** — Reverse the direction of a wire using
  `TopoDS_Shape.Reversed()`. Reports new start/end points.

### New tools (surfaces)

- **extrude_surface(name, direction, distance)** — Extrude any shape (face, wire,
  or solid) along a direction vector using `BRepPrimAPI_MakePrism`. Works on
  existing faces from solids, planar wires, or standalone faces.

- **unroll_surface(name, face_index)** — Flatten a developable surface into a
  2D pattern. Supports cylindrical faces (unrolls to rectangle: width = arc length,
  height = axial extent) and conical faces (unrolls to annular sector with polyline
  approximation). Rejects non-developable surfaces (sphere, torus, bspline) with
  a clear error message. Essential for sheet metal and packaging design.

### Stats

- **104 tools** across **21 modules** (up from 98 in v0.4.4).
- +6 new tools in `curves.py` (+450 lines).

---

## v0.4.4 — 2026-03-29

### Phase 4 — Part Library Ecosystem (Roadmap)

New `parts_user` module enabling user-created part libraries with automatic
indexing, search, and parameterized import. Inspired by bertvanbrakel/mcp-cadquery
but built for CAiD's architecture with subprocess isolation.

### New tool module: parts_user (3 tools)

- **scan_part_library(directory)** — Walks a directory of `.py` CAiD scripts,
  executes each in an isolated subprocess, extracts metadata from docstring
  frontmatter (Name, Description, Tags, Author), extracts `# PARAM` markers
  for parameter discovery, generates shaded PNG thumbnails, and stores a
  JSON index (`.caid_parts_index.json`) for fast lookup. Incremental: skips
  scripts whose mtime hasn't changed since last scan. Handles segfaults and
  missing `result` variables gracefully.

- **search_parts(query, directory)** — Multi-field keyword search across the
  part index. Searches name (3x weight), tags (2x), description (1x), and
  author (1x). All keywords must match at least one field. Returns top 10
  results with metadata, parameters, and thumbnail paths.

- **import_part(script_path, name, parameters)** — Executes a part script in
  a subprocess with optional parameter overrides (JSON object). The `# PARAM`
  markers in the script are replaced with override values. Result is exported
  as BREP and reimported into the scene. Reports dimensions and volume.

### Docstring frontmatter format

```
'''
Name: Hex Standoff
Description: M3 hex standoff with female threads
Tags: fastener, standoff, M3, spacer
Author: Adam
'''
```

### Parameter markers

```python
length = 10  # PARAM Length of the standoff in mm
diameter = 3  # PARAM Outer diameter
```

### Stats

- **98 tools** across **21 modules** (up from 95 / 20 in v0.4.3).
- New module: `parts_user.py` (+320 lines).

---

## v0.4.3 — 2026-03-29

### Phase 2 — Transform Gaps (Roadmap)

Closes GOLEM parity for positioning/alignment tools. All three tools added to
`transforms.py` alongside existing translate/rotate/scale/mirror.

### New tools

- **orient_object** — Map 1-3 reference points to target points to precisely
  position and orient an object. 1 point = translate, 2 points = translate +
  rotate (aligns a vector), 3 points = full orientation (aligns a plane).
  Uses OCP's `gp_Trsf` and `BRepBuilderAPI_Transform`. Handles edge cases:
  parallel vectors, 180-degree flips, degenerate planes. Inspired by GOLEM's
  `manipulation.orient`.

- **align_objects** — Align multiple objects along an axis by their bounding
  box min, center, or max. Objects are moved to the average position of the
  group. Example: `align_objects('["bracket","plate","bolt"]', axis="X",
  alignment="center")`. Inspired by GOLEM's `manipulation.align_objects`.

- **distribute_objects** — Evenly space objects along an axis. Auto-computes
  spacing to fill the span between first and last object, or accepts explicit
  center-to-center spacing. Objects are ordered as given in the names array.
  Inspired by GOLEM's `manipulation.distribute_objects`.

### Stats

- **95 tools** across **20 modules** (up from 92 in v0.4.2).
- +3 new tools in `transforms.py`.

---

## v0.4.2 — 2026-03-29

### Phase 1 — Workflow & UX (Roadmap)

Implements all four items from Roadmap Phase 1: workflow and UX improvements
that make the LLM agent more efficient without adding new geometry capabilities.

### New tools

- **compare_renders** — before/after visual diff tool. Call twice with the same
  object name and label: first call saves a "before" snapshot, second call renders
  "after" and composites both into a side-by-side comparison image with labels.
  Uses PIL for compositing. Inspired by openscad-mcp's compare_renders.

- **describe_shape** — natural language geometry summary. Returns plain English
  like: "'bracket' is a solid occupying 40.00 x 20.00 x 5.00 mm. It has 12 faces
  (6 plane, 4 cylinder, 2 bspline), 24 edges, and 16 vertices." Includes face type
  breakdown, volume, surface area, center of mass, and bounding box. Much easier
  for LLMs to reason about than raw JSON from measure_object.
  Inspired by bertvanbrakel/mcp-cadquery's get_shape_description.

### Infrastructure

- **Quality presets** — `render_object`, `render_scene`, and `export_stl` now accept
  a `quality` parameter: "draft" (fast/coarse, tol=0.5), "normal" (default, tol=0.2),
  or "high" (smooth/fine, tol=0.05). Explicit `tolerance` still overrides presets.
  LLMs pick strings better than numeric tolerances. Inspired by openscad-mcp.

- **Render caching** — SHA-256 hash of (BREP bytes + view + size + color + tolerance)
  used to cache rendered PNGs. Cache hit skips tessellation and matplotlib rendering
  entirely, returning the cached image. LRU eviction at 500 MB (evicts down to 80%).
  Cache stored in `~/cadquery-output/.render_cache/`. Inspired by openscad-mcp.

### Stats

- **92 tools** across **20 modules** (up from 90 in v0.4.1).
- +2 new tools, +2 infrastructure features.

---

## v0.4.1 — 2026-03-29

### Competitive analysis & gap closure

Performed full competitive audit against all known CAD MCP servers (GOLEM-3DMCP/Rhino,
bertvanbrakel/mcp-cadquery, quellant/openscad-mcp, Fusion 360 MCP, FreeCAD MCPs,
Blender MCPs, and others). Identified capability gaps and began closing them.

### New tool modules

- **curves** (8 tools) — `create_line`, `create_arc`, `create_circle`, `create_polyline`,
  `create_spline`, `offset_curve`, `project_curve`, `fillet_curves`.
  Standalone wire/curve creation and manipulation. Closes the biggest conceptual gap
  with GOLEM-3DMCP (Rhino, 105 tools) — CAiD is no longer solid-body-only.
  All curves store as wires in the scene and interoperate with existing tools
  (sweep paths, array_on_curve, measure_distance, list_edges, etc.).
  - **Attribution:** Original code. OCP APIs used: `GC_MakeArcOfCircle` (arc through
    3 points), `GeomAPI_PointsToBSpline` (spline fitting — pattern borrowed from
    existing `sweep.py:_make_spline_wire`), `BRepOffsetAPI_MakeOffset` (curve offset),
    `BRepProj_Projection` (curve projection onto solid), `BRepFilletAPI_MakeFillet2d`
    (2D corner filleting with vertex deduplication fix for OCCT's double-visit bug).

- **split** (3 tools) — `split_with_plane`, `split_with_object`, `intersect_curves`.
  Split solids and extract intersection geometry. Fills a real workflow hole —
  previously the only way to divide a body was `boolean_cut` (discards intersection)
  or `section_view` (discards one half).
  - **Attribution:** Original code. `BOPAlgo_Splitter` for solid splitting (OCCT native,
    not available in any other CadQuery MCP). `BRepAlgoAPI_Section` for intersection
    curve extraction. Plane-as-tool pattern inspired by existing `section_view` in
    `view.py` but uses proper `gp_Pln` + `MakeFace` instead of the large-box hack.

### Competitive landscape (for reference)

Servers audited and features compared:

| Server | Stars | Kernel | Tools | Threat level |
|--------|-------|--------|-------|-------------|
| GOLEM-3DMCP (Rhino) | 1 | Rhino 8 | 105 | High (tool count), but requires $1000+ license |
| bertvanbrakel/mcp-cadquery | 15 | CadQuery | ~10 | Low (same kernel, far fewer tools) |
| quellant/openscad-mcp | 58 | OpenSCAD | 15 | Low (different paradigm, good UX ideas) |
| Fusion 360 MCP | 65 | Fusion API | ~3 | Medium (powerful but needs Fusion license) |
| AI Forge (Blender) | 6 | Blender+UE5 | 278 | None (game assets, not engineering CAD) |
| CAD-MCP (AutoCAD) | 286 | AutoCAD COM | ~12 | None (2D drafting only) |

Key ideas identified and sourced from competitors:
- **Compare renders** (from openscad-mcp) — before/after visual diff
- **Part library scan/search/index** (from bertvanbrakel/mcp-cadquery) — user part indexing
- **Render caching** (from openscad-mcp) — SHA-hash based cache with LRU eviction
- **Quality presets** (from openscad-mcp) — draft/normal/high instead of numeric tolerance
- **Natural language shape description** (from bertvanbrakel/mcp-cadquery) — LLM-friendly geometry summary
- **Orient/Align** (from GOLEM-3DMCP) — reference-to-target point mapping transforms

### Stats

- **90 tools** across **20 modules** (up from 79 tools / 18 modules in v0.4.0).
- Curves toolkit: +310 lines in `curves.py`
- Split toolkit: +195 lines in `split.py`

---

## v0.4.0 — 2026-03-26

### Breaking: CadQuery removed — direct OCP backend

CAiD-MCP no longer depends on CadQuery or conda. The entire codebase (all 18 tool
modules, core.py, server.py) was rewritten to use OpenCascade (OCP) directly via
the CAiD library.

**What this means:**
- Install is now `pip install caid caid-mcp` — no conda environment needed.
- All geometry creation uses OCP APIs (`BRepPrimAPI`, `BRepAlgoAPI`, `BRepOffsetAPI`, etc.).
- All geometry queries use OCP explorers (`TopExp_Explorer`, `BRepAdaptor`, `GProp`).
- STL tessellation via `caid.to_stl`, STEP/BREP via OCP writers.
- MCP config simplified — plain `python` command instead of `conda run`.

**Files migrated:** `core.py`, `primitives.py`, `modify.py`, `query.py`, `view.py`,
`export.py`, `sweep.py`, `fasteners.py`, `advanced.py`, `assembly.py`, `compound.py`,
`transforms.py`, `booleans.py`, `server.py`, `pyproject.toml`, `smithery.yaml`.

### New tool modules

- **sweep** (4 tools) — `sweep_along_path`, `sweep_circle_along_path`, `loft_profiles`,
  `loft_circle_to_rect`. Create complex shapes by sweeping profiles along spline paths
  or lofting between cross-sections.
- **fasteners** (7 tools) — `create_bolt`, `create_nut`, `create_washer`, `add_hole`,
  `add_clearance_hole`, `add_tap_hole`, `list_fastener_sizes`. ISO metric fasteners
  (M2–M24) built from OCP primitives (hex prisms + cylinders), with parametric
  clearance and tap hole drilling.
- **history** (4 tools) — `save_snapshot`, `restore_snapshot`, `list_snapshots`, `undo`.
  Full scene state snapshots for nondestructive experimentation. Undo reverts the last
  geometry operation.
- **parts_warehouse** (4 tools) — `create_warehouse_fastener`, `create_warehouse_bearing`,
  `list_warehouse_parts`, `list_warehouse_sizes`. Parametric mechanical parts via
  cq_warehouse (bearings, fastener families).
- **parts_library** (3 tools) — `freecad_library_browse`, `freecad_library_search`,
  `freecad_library_import`. On-demand access to FreeCAD's 2,900+ STEP file library
  — browse categories, search by keyword, import parts directly into the scene.

### New tools in existing modules

- **query** → `mass_properties`: compute mass, center of gravity, and moments of
  inertia with 28 built-in materials (steel, aluminum, copper, ABS, nylon, etc.)
  or custom density input.
- **advanced** → `create_circular_pattern`: polar/radial arrays of objects around
  a center point — specify count, radius, and angular range.

### Subprocess isolation (stability)

Boolean operations and `run_cadquery_script` now execute in isolated subprocesses.
If OCCT segfaults on a complex boolean (a known issue with degenerate geometry),
the subprocess dies but the MCP server stays alive.

- `safe_boolean()` in `core.py` — wraps `boolean_cut`, `boolean_union`, `boolean_intersect`
  in a subprocess with timeout and segfault detection.
- `run_cadquery_script` — subprocess-isolated with segfault-specific error messages.
- `safe_boolean` returns `ForgeResult` on all code paths (previously returned raw `dict`
  on subprocess errors — fixed in QA pass).

### Shaded PNG rendering

New photorealistic rendering via matplotlib's 3D engine, replacing SVG-only output
for visual verification.

- `render_object` — render a single object to shaded PNG. 7 view presets (`front`,
  `top`, `right`, `iso`, `bottom`, `left`, `rear`) plus `multi` for a 2×2 grid
  showing front/top/right/iso simultaneously.
- `render_scene` — render all objects in the scene to a single PNG with per-object
  colors. Same view presets as `render_object`.
- Output saved to `~/caid_output/renders/`.

### Bug fixes

- `safe_boolean` now returns `ForgeResult` on all paths including subprocess errors
  (was returning raw `dict`, breaking downstream validation).
- `compound.py` → `create_array_on_curve` updated for compound return type compatibility.
- Example gallery `quickstart.py` API calls fixed to match current tool signatures.

### Test suite

Complete test suite rewrite — zero CadQuery imports. 72 tests passing in a pure
pip virtualenv (no conda). Old `test_cadquery_mcp.py` (1,055 lines) removed and
replaced by `test_caid_mcp.py`.

### Documentation

- README updated: pip install instructions, no conda references, updated MCP config
  examples, example gallery section with rendered images.
- LLM_GUIDE.md updated to reflect OCP-based architecture.
- CONTRIBUTING.md updated with venv dev setup instructions.
- `smithery.yaml` simplified to use `python` directly.

### Stats

- **79 tools** across **18 modules** (up from 54 tools / 13 modules in v0.3.2).
- **+3,816 lines added**, **−1,101 lines removed** across 33 files.
- **72 tests**, zero CadQuery dependencies.

---

## v0.3.2 — 2026-03-26

- Added MCP Registry verification metadata to README
- Added examples, CONTRIBUTING.md, GitHub Actions CI
- Updated GitHub URLs, license year, attribution

## v0.3.1 — 2026-03-26

**New tool modules:**
- **query** (6 tools) — `list_edges`, `list_faces`, `measure_distance`, `measure_object`, `find_edges_near_point`, `find_faces_near_point`. Lets the LLM inspect geometry before modifying it.
- **view** (2 tools) — `section_view` (cross-section cuts), `exploded_view` (assembly explosion). For verifying internal features and assembly layout.

**Enhanced existing tools:**
- `fillet_edges` and `chamfer_edges` now accept `edge_indices` (JSON array) from `list_edges` output — target specific edges instead of guessing with selector strings.
- `add_hole` and `shell_object` now accept `face_index` from `list_faces` output — drill or shell on any face, not just `>Z`.

**Total: 54 tools across 13 modules.**

## v0.3.0

- Added **heal** module (3 tools) — `check_object_valid`, `heal_object`, `simplify_object`
- Added **io** module (3 tools) — `export_brep`, `import_step`, `import_brep`
- Added **assembly** module (5 tools) — `create_assembly`, `assembly_add`, `assembly_move`, `assembly_rotate`, `assembly_merge`
- Added **compound** module (3 tools) — `create_belt_wire`, `create_array_on_curve`, `create_pulley_assembly`
- Switched validation backend from manual checks to CAiD's ForgeResult system
- All geometry operations now auto-validated with volume tracking and diagnostics

## v0.2.0

- Visual preview via SVG rendering (`preview_object`, `preview_scene`)
- Tool router (`discover_tools`) for category-based tool browsing
- Modular architecture — tools split into separate files
- Test suite (33 tests)
- 32 tools across 7 categories

## v0.1.0

- Initial release
- Basic primitives, booleans, transforms, modifications
- STL and STEP export
