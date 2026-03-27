# Changelog

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
