# CAiD MCP Roadmap — Competitive Gap Closure

Status as of 2026-03-29: **113 tools across 22 modules**.
**ALL PHASES COMPLETE.** Surpasses GOLEM-3DMCP (105 tools).

| Phase | Version | Tools |
|-------|---------|-------|
| 1 — Workflow & UX | v0.4.2 | +2 tools, +2 infra |
| 2 — Transform Gaps | v0.4.3 | +3 tools |
| 3 — Advanced Curves | v0.4.5 | +6 tools |
| 4 — Part Library | v0.4.4 | +3 tools |
| 5 — Scene Organization | v0.4.6 | +8 tools |
| 6 — Infrastructure | v0.4.6 | +1 tool, +3 infra |
Goal: close every meaningful gap with GOLEM-3DMCP (Rhino) and adopt the best
UX patterns from openscad-mcp and bertvanbrakel/mcp-cadquery.

---

## Phase 1 — Workflow & UX (no new geometry, big LLM-agent impact) ✅ DONE

These improve how the LLM works with CAiD, not what geometry it can create.
Low risk, high value, can ship independently.

**Completed in v0.4.2.**

### 1.1 Compare Renders (1 tool)
**Source:** openscad-mcp's `compare_renders`
**Tool:** `compare_renders(name, view, label_before, label_after)`
- Renders the current state of an object, stores it as "before"
- After modifications, renders again as "after"
- Returns both images side-by-side for LLM visual diff
- Implementation: save render to temp file keyed by (name, label), composite with PIL/matplotlib
- **Effort:** Low — builds on existing `render_object`

### 1.2 Describe Shape (1 tool)
**Source:** bertvanbrakel/mcp-cadquery's `get_shape_description`
**Tool:** `describe_shape(name)`
- Returns natural language: "The object is a solid occupying 10.0 x 5.0 x 3.0 mm.
  It has 12 faces, 24 edges, 16 vertices. Volume: 127.3 mm³."
- Helps LLM reason about geometry without parsing JSON from `measure_object`
- **Effort:** Trivial — reformat existing `measure_object` output

### 1.3 Quality Presets (infrastructure)
**Source:** openscad-mcp's draft/normal/high presets
- Add `quality` parameter to `render_object`, `render_scene`, `export_stl`
- Map "draft" → coarse tolerance (fast), "normal" → current default, "high" → fine
- LLMs pick strings better than numeric tolerances
- **Effort:** Low — parameter sugar on existing tools

### 1.4 Render Caching (infrastructure)
**Source:** openscad-mcp's SHA-256 render cache
- Hash (object BREP bytes + view + size + color + tolerance) → cached PNG
- Skip re-render if hash matches. LRU eviction at 500MB.
- Saves significant time in iterative design loops
- **Effort:** Medium — need hash computation and cache management in export.py

---

## Phase 2 — Transform Gaps (small tools, close GOLEM parity) ✅ DONE

GOLEM has orient/align/shear that we lack. These are positioning tools
that make assembly and multi-part work much easier.

**Completed in v0.4.3.**

### 2.1 Orient Object (1 tool)
**Source:** GOLEM's `manipulation.orient`
**Tool:** `orient_object(name, from_points, to_points, result_name)`
- Map 1-3 reference points to target points (translation + rotation)
- 1 point = translate only, 2 points = translate + rotate, 3 = full orient
- Uses `gp_Trsf` with point-to-point mapping
- **Effort:** Medium — math for 2/3-point orientation

### 2.2 Align Objects (1 tool)
**Source:** GOLEM's `manipulation.align_objects`
**Tool:** `align_objects(names, axis, alignment)`
- Align multiple objects along an axis: "min", "center", "max"
- Example: align_objects('["bracket", "plate", "bolt"]', axis="X", alignment="center")
- **Effort:** Low — read bounding boxes, compute offsets, translate

### 2.3 Distribute Objects (1 tool)
**Source:** GOLEM's `manipulation.distribute_objects`
**Tool:** `distribute_objects(names, axis, spacing)`
- Evenly space objects along an axis
- Auto-compute spacing or use explicit value
- **Effort:** Low — similar to align

---

## Phase 3 — Advanced Curves & Surfaces (bigger lifts, GOLEM parity) ✅ DONE

These extend the curves toolkit from Phase 0 into proper surface modeling.
CadQuery/OCP supports all of these under the hood.

**Completed in v0.4.5.**

### 3.1 Curve Operations (4 tools)
**Source:** GOLEM's curve manipulation suite
- `extend_curve(name, end, distance)` — extend a curve beyond its endpoint
- `chamfer_curves(name, distance, result_name)` — chamfer corners instead of fillet
- `join_curves(names, result_name)` — join multiple wires into one connected wire
- `reverse_curve(name)` — reverse the direction of a wire

**OCP APIs:** `BRepBuilderAPI_MakeWire` (join), `ShapeAnalysis_Curve` (extend),
existing `BRepFilletAPI_MakeFillet2d` pattern adapted for chamfers.
**Effort:** Medium — 4 small tools

### 3.2 Surface Unroll (1 tool)
**Source:** GOLEM's `surfaces.unroll`
**Tool:** `unroll_surface(name, result_name)`
- Flatten a developable surface (cylinder, cone) into a flat pattern
- Essential for sheet metal, fabric, packaging design
- **OCP API:** `BRepOffsetAPI_MakeOffset` or `ShapeAnalysis_Surface` + custom flattening
- **Effort:** High — complex geometry, limited OCCT support for non-developable surfaces

### 3.3 Extrude Surface (1 tool)
**Source:** GOLEM's `surfaces.extrude_surface`
**Tool:** `extrude_surface(name, direction_x, direction_y, direction_z, distance)`
- Extrude an existing face/surface along a direction (not just curves)
- **OCP API:** `BRepPrimAPI_MakePrism` on face shapes
- **Effort:** Low — already used in `create_extruded_polygon`, just needs face input

---

## Phase 4 — Part Library Ecosystem (new module) ✅ DONE

User-created part libraries with automatic indexing. Stolen from
bertvanbrakel/mcp-cadquery but built for CAiD's architecture.

**Completed in v0.4.4.**

### 4.1 Scan Part Library (1 tool)
**Source:** bertvanbrakel's `scan_part_library`
**Tool:** `scan_part_library(directory)`
- Walk a directory of `.py` CadQuery/CAiD scripts
- Execute each, extract metadata from docstring frontmatter:
  ```
  Name: Hex Standoff
  Description: M3 hex standoff with female threads
  Tags: fastener, standoff, M3, spacer
  Author: Adam
  ```
- Generate SVG/PNG thumbnail preview, cache by file mtime
- Store index as JSON in the library directory
- **Effort:** High — subprocess execution, metadata parsing, thumbnail gen

### 4.2 Search Parts (1 tool)
**Source:** bertvanbrakel's `search_parts`
**Tool:** `search_parts(query, path)`
- Multi-field keyword search with relevance scoring
- Returns: name, description, tags, thumbnail path, script path
- **Effort:** Medium — depends on scan_part_library index

### 4.3 Import Part (1 tool)
**Tool:** `import_part(script_path, name, parameters)`
- Execute a part script with optional parameter overrides
- Store result in scene
- Parameter substitution via `# PARAM` markers (from bertvanbrakel)
- **Effort:** Medium — builds on existing run_cadquery_script

---

## Phase 5 — Scene Organization (GOLEM parity) ✅ DONE

Layers, groups, and object properties. Not critical for modeling but
important for complex multi-part projects.

**Completed in v0.4.6.**

### 5.1 Object Properties (2 tools)
**Source:** GOLEM's `manipulation.set_properties` / metadata
- `set_object_properties(name, color, visible, locked, material)`
- `get_object_properties(name)`
- Store as dict alongside shape in scene
- Used by render tools for per-object color/visibility
- **Effort:** Low-Medium — extend scene dict, update render pipeline

### 5.2 Groups (3 tools)
**Source:** GOLEM's `manipulation.group/ungroup` + `scene.get_groups`
- `create_group(group_name, object_names)`
- `ungroup(group_name)`
- `list_groups()`
- Groups are lightweight — just a name→[names] mapping, not geometry
- **Effort:** Low

### 5.3 Layers (3 tools)
**Source:** GOLEM's layer system
- `create_layer(layer_name, color, visible)`
- `set_object_layer(object_name, layer_name)`
- `list_layers()`
- Objects default to layer "0". Render respects layer visibility.
- **Effort:** Medium — needs to thread through render pipeline

---

## Phase 6 — Infrastructure & Polish ✅ DONE

**Completed in v0.4.6.**

### 6.1 Adaptive Response Size (infrastructure)
**Source:** openscad-mcp
- Estimate token cost of base64-encoded PNG responses
- Auto-compress or save-to-file when response would exceed threshold
- Prevents blowing up the LLM context window
- **Effort:** Medium

### 6.2 Flexible Parameter Parsing (infrastructure)
**Source:** openscad-mcp
- Accept points as `[x,y,z]`, `{"x":1,"y":2,"z":3}`, or `"1,2,3"` strings
- LLMs format parameters inconsistently — forgiveness reduces tool-call failures
- Apply to all tools that accept coordinate inputs
- **Effort:** Medium — shared parser utility, update all tools

### 6.3 Version Check Tool (1 tool)
**Tool:** `server_info()`
- Return version, tool count, output directory, available categories
- Useful for LLM self-orientation at conversation start
- **Effort:** Trivial

---

## Summary — ROADMAP COMPLETE

All phases implemented in v0.4.2 through v0.4.6.

| Phase | Tools | Version | Status |
|-------|-------|---------|--------|
| 1 — Workflow & UX | +2 tools, +2 infra | v0.4.2 | Done |
| 2 — Transform Gaps | +3 tools | v0.4.3 | Done |
| 3 — Advanced Curves | +6 tools | v0.4.5 | Done |
| 4 — Part Library | +3 tools | v0.4.4 | Done |
| 5 — Scene Organization | +8 tools | v0.4.6 | Done |
| 6 — Infrastructure | +1 tool, +3 infra | v0.4.6 | Done |

**Final: 113 tools across 22 modules** — surpasses GOLEM-3DMCP (105 tools).
