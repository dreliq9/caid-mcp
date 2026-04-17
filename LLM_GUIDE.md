# CAiD MCP Server

MCP server giving you (Claude) validated 3D modeling via CAiD — a validation layer on top of OCP (OpenCASCADE). 107 tools across 22 categories. Output goes to `~/cadquery-output/`.

Every geometry operation returns a ForgeResult with volume tracking and diagnostics. If an operation silently fails (common with OCCT booleans), the validation layer catches it and tells you what went wrong.

## Critical: Order of operations
Build geometry in this sequence or operations will fail:
1. Create primitives
2. Position with transforms (translate/rotate)
3. Boolean combine/cut
4. Drill holes
5. Shell (hollow out)
6. Fillet/chamfer edges (ALWAYS LAST)

Reversing steps 5 and 6 is the #1 cause of failures. If fillet/chamfer fails, try `heal_object` first then retry with a smaller radius.

## Reading tool results (v0.6.0+)

Tools in `primitives` and `query` return **structured outputs**. Every response
has both:

- A human-readable text block (the same kind of "OK Created box 'lid' | volume=...")
- A typed JSON `structuredContent` payload with the same data as fields

Examples of fields you can rely on instead of regex-parsing the text:

| Tool | Structured fields |
|------|-------------------|
| `create_*` | `ok`, `name`, `kind`, `volume_mm3`, `bbox.{xlen,ylen,zlen,...}`, `reason`, `hint` |
| `inspect_object` | `volume_mm3`, `surface_area_mm2`, `center_of_mass.{x,y,z}`, `bounding_box`, `num_faces`, `num_edges`, `num_vertices`, `face_types` |
| `mass_properties` | `mass_grams`, `mass_kg`, `weight_newtons`, `density_g_per_cm3`, `volume_cm3` |
| `list_edges` / `list_faces` | `count`, `edges[].{index, length_mm, start, end, midpoint, type}` etc. |
| `measure_distance` | `min_distance_mm` |
| `find_edges_near_point` / `find_faces_near_point` | `nearest_*[].distance_to_point` |

Failures from `mass_properties` (missing material/density, or unknown material)
now surface as proper tool errors (`isError: true`) instead of `"FAIL ..."`
strings — use the error message directly, don't string-match.

## Query before modify
Before applying fillets, chamfers, or holes to specific locations:
1. Use `list_edges` or `list_faces` to see all geometry with indices
2. Use `find_edges_near_point` if you know the approximate location
3. Use `inspect_object` to check dimensions and verify the shape
4. Pass `edge_indices` or `face_index` to target exactly what you want

This avoids guessing with selector strings like `">Z"` and getting the wrong edge.

## Scene stores raw OCP shapes
Objects in the scene are raw `TopoDS_Shape` objects (Solid/Compound), not workplane wrappers. When using `run_cadquery_script`, you work directly with OCP shapes from the scene dict. The `store_object` function auto-extracts from ForgeResult, so scripts can return either type.

## Parameter gotchas
- `add_hole` takes **radius**, but doubles it internally for the diameter-based hole operation. For metric screws: M2=r1.0, M2.5=r1.25, M3=r1.5, M4=r2.0, M5=r2.5, M6=r3.0
- `create_extruded_polygon` and `create_revolved_profile` take `points` as a **JSON string**, not a native array. Always pass: `points='[[0,0],[10,0],[10,10]]'`
- `create_revolved_profile` revolves around the **Z axis**. Profile points are in the XZ plane.
- Primitives now reject zero/negative dimensions at the schema layer (Pydantic `gt=0`). Don't bother passing them — fix the value before the call.
- `mass_properties` `material` is a fixed enum of 28 names (see CHANGELOG / source). British spellings (`"aluminium"`) are rejected — use the US spelling (`"aluminum"`).
- `inspect_object` no longer takes a `format` parameter — both text and structured forms are returned every call.
- `fillet_solid_edges` and `chamfer_solid_edges` accept either `edge_selector` (string like `">Z"`, `"|X"`) or `edge_indices` (JSON array like `"[0, 3, 7]"` from `list_edges`). Indices override the selector.
- `fillet_solid_edges` radius must be **less than half the shortest edge**. Use `list_edges` to check edge lengths first.
- `add_hole` accepts either `face_selector` (string) or `face_index` (int from `list_faces`). Default is `">Z"` (top face in global coordinates).
- `shell_object` accepts either `face_to_remove` (string) or `face_index` (int). Default removes top face.
- `shell_object` thickness is applied inward. Just pass a positive number.

## Boolean behavior
- Booleans are **auto-validated**: volume is checked before/after. If a union doesn't increase volume, you get a warning with a hint (shapes may not overlap).
- `boolean_union/cut/intersect` store the result under `result_name` but **do not delete the originals**. Clean up with `delete_object`.
- If two objects share an exact coplanar face, offset one by 0.001mm to break coincidence.
- Booleans that produce a shape but fail validation return the shape with a WARN — you can still use it.

## Healing workflow
When operations fail (especially fillet/chamfer on complex shapes):
1. Run `check_object_valid` to see what's wrong
2. Run `heal_object` to attempt automatic repair
3. Run `simplify_object` to clean up unnecessary face boundaries from booleans
4. Retry the failed operation

## Assembly workflow
1. Create objects in the scene as usual
2. `create_assembly` to start a named assembly
3. `assembly_add` to add scene objects as parts
4. `assembly_move` / `assembly_rotate` to position parts
5. `assembly_merge` to boolean-union all parts into one shape
6. `exploded_view` to generate an exploded diagram for verification

## Section views
Use `section_view` to cut through objects and verify internal features:
- `section_view("part", axis="X", offset=5.0)` — cut at X=5mm
- `keep="below"` (default) shows the negative side, `keep="above"` shows the positive side
- `save_result="half_part"` optionally stores the sectioned shape

## Previews
- SVG previews return inline XML text. You cannot actually see the image — but you can verify it was generated and check the reported dimensions.
- Use `render_object` on individual objects rather than `render_scene` for reliability.
- Preview before export to catch dimension mistakes early.

## Import/export
- `export_stl`, `export_step`, `export_brep` — all validated via ForgeResult
- `import_step`, `import_brep` — load external geometry into the scene
- STL tolerance: 0.1 for most parts, 0.01 for small/detailed, never below 0.001

## Escape hatch: run_cadquery_script
The tool name `run_cadquery_script` is kept for API compatibility — it actually runs CAiD/OCP code. The script environment has access to:
- `caid` — the CAiD module (validated operations)
- `Vector` — from `caid.vector` (not cadquery)
- `scene` — the scene dict (raw `TopoDS_Shape` objects)
- `OUTPUT_DIR` — Path to output directory
- OCP modules can be imported directly (e.g., `from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox`)

Scripts can return raw `TopoDS_Shape` or ForgeResult — both handled by `store_object`.

```python
script = """
from caid.vector import Vector
# Work with scene objects directly
shape = scene["base"]
result = caid.make_box(20, 20, 10)
"""
# Call with result_name="base" to update the object in-scene
```

## Performance
- Keep `create_linear_pattern` under 10x10 (100 copies).
- STL export: tolerance=0.1 for most parts.
- Complex operations (many booleans, fine fillets) can take 30+ seconds.

## Common metric hardware reference
| Screw | Clearance hole radius | Tap hole radius |
|-------|----------------------|-----------------|
| M2    | 1.1mm                | 0.8mm           |
| M2.5  | 1.4mm                | 1.0mm           |
| M3    | 1.6mm                | 1.25mm          |
| M4    | 2.2mm                | 1.65mm          |
| M5    | 2.7mm                | 2.1mm           |
| M6    | 3.3mm                | 2.5mm           |
