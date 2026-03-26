# Changelog

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
