"""Advanced tools: script execution, patterns, and the tool router."""

import json
import traceback
from typing import Optional

import cadquery as cq
from cadquery import Vector, exporters
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import scene, require_object, store_object, OUTPUT_DIR


def register(mcp: FastMCP) -> None:
    """Register advanced tools and the tool router."""

    @mcp.tool()
    def run_cadquery_script(script: str, result_name: Optional[str] = None) -> str:
        """Execute arbitrary CadQuery/CAiD Python code for advanced operations.

        The script has access to:
        - cq: the cadquery module
        - caid: the CAiD module (validated geometry operations)
        - Vector: cadquery.Vector for convenience
        - scene: the scene dict (shapes, not Workplanes)
        - OUTPUT_DIR: Path to output directory
        - exporters: CadQuery export module

        If the script sets a variable called 'result', it will be stored under result_name.
        The result can be a raw Shape, a cq.Workplane, or a caid.ForgeResult.

        Args:
            script: Python code to execute.
            result_name: If provided, store the 'result' variable under this name.
        """
        try:
            exec_globals = {
                "cq": cq, "caid": caid, "Vector": Vector,
                "scene": scene, "OUTPUT_DIR": OUTPUT_DIR, "exporters": exporters,
            }
            exec(script, exec_globals)
            if result_name and "result" in exec_globals:
                store_object(result_name, exec_globals["result"])
                return f"OK Script executed. Result stored as '{result_name}'."
            return "OK Script executed successfully."
        except Exception:
            return f"FAIL Script error:\n{traceback.format_exc()}"

    @mcp.tool()
    def create_linear_pattern(
        name: str, count_x: int = 1, count_y: int = 1,
        spacing_x: float = 10, spacing_y: float = 10,
        result_name: Optional[str] = None,
    ) -> str:
        """Create a rectangular grid pattern of an existing object.

        Args:
            name: Source object to pattern.
            count_x: Number of copies along X.
            count_y: Number of copies along Y.
            spacing_x: Distance between copies along X (mm).
            spacing_y: Distance between copies along Y (mm).
            result_name: Name for the combined result (default: {name}_pattern).
        """
        try:
            base_shape = require_object(name)
            result_shape = base_shape
            for ix in range(count_x):
                for iy in range(count_y):
                    if ix == 0 and iy == 0:
                        continue
                    moved = caid.translate(base_shape, Vector(ix * spacing_x, iy * spacing_y, 0))
                    if moved.shape is not None:
                        fr = caid.boolean_union(result_shape, moved.shape)
                        if fr.shape is not None:
                            result_shape = fr.shape
            rname = result_name or f"{name}_pattern"
            store_object(rname, result_shape)
            return f"OK Created {count_x}x{count_y} pattern -> '{rname}'"
        except Exception as e:
            return f"FAIL Error: {e}"

    # ========================== TOOL ROUTER ==================================

    @mcp.tool()
    def discover_tools(category: Optional[str] = None) -> str:
        """Discover available tools by category.

        Call with no arguments to see all categories.
        Call with a category name to see tools in that category.

        Args:
            category: Options: "primitives", "modify", "transforms", "booleans",
                      "scene", "export", "advanced", "heal", "io", "assembly",
                      "compound", "query", "view".
        """
        catalog = {
            "primitives": {
                "description": "Create basic 3D shapes",
                "tools": [
                    "create_box — rectangular box/cuboid",
                    "create_cylinder — cylinder",
                    "create_sphere — sphere",
                    "create_cone — cone or frustum",
                    "create_torus — torus/donut",
                    "create_extruded_polygon — extrude a 2D polygon",
                    "create_revolved_profile — revolve a 2D profile (lathe)",
                ],
            },
            "modify": {
                "description": "Modify existing geometry",
                "tools": [
                    "add_hole — drill a hole through a face",
                    "fillet_edges — round edges (optional edge_selector)",
                    "chamfer_edges — bevel edges (optional edge_selector)",
                    "shell_object — hollow out a solid",
                ],
            },
            "transforms": {
                "description": "Move, rotate, scale, and mirror objects",
                "tools": [
                    "translate_object — move by offset",
                    "rotate_object — rotate around an axis",
                    "scale_object — uniform scale",
                    "mirror_object — reflect across a plane",
                ],
            },
            "booleans": {
                "description": "Combine or subtract solids (auto-validated)",
                "tools": [
                    "boolean_union — combine two objects",
                    "boolean_cut — subtract one from another",
                    "boolean_intersect — keep only overlap",
                    "combine_objects — merge multiple objects",
                ],
            },
            "scene": {
                "description": "Manage the workspace",
                "tools": [
                    "list_objects — see all objects with dimensions",
                    "get_object_info — detailed geometry + validity info",
                    "delete_object — remove an object",
                    "duplicate_object — copy an object",
                    "clear_scene — remove everything",
                ],
            },
            "export": {
                "description": "Export files and render previews",
                "tools": [
                    "preview_object — render SVG preview of one object",
                    "preview_scene — render SVG preview of entire scene",
                    "export_stl — export to STL for 3D printing",
                    "export_step — export to STEP (lossless CAD format)",
                    "export_all_stl — batch export all objects as STL",
                ],
            },
            "advanced": {
                "description": "Scripting, patterns, and power-user tools",
                "tools": [
                    "run_cadquery_script — execute CadQuery/CAiD Python code",
                    "create_linear_pattern — rectangular grid pattern",
                    "discover_tools — this tool (browse available tools)",
                ],
            },
            "heal": {
                "description": "Shape validation and repair",
                "tools": [
                    "check_object_valid — run OCCT validity checks",
                    "heal_object — attempt to fix degenerate geometry",
                    "simplify_object — merge coplanar faces after booleans",
                ],
            },
            "io": {
                "description": "Import/export additional formats",
                "tools": [
                    "export_brep — export to native OCCT BREP format",
                    "import_step — import geometry from a STEP file",
                    "import_brep — import geometry from a BREP file",
                ],
            },
            "assembly": {
                "description": "Multi-part assembly management",
                "tools": [
                    "create_assembly — create a new named assembly",
                    "assembly_add — add a scene object as a part",
                    "assembly_move — translate a part within the assembly",
                    "assembly_rotate — rotate a part within the assembly",
                    "assembly_merge — boolean union all parts into one shape",
                ],
            },
            "compound": {
                "description": "Belt/pulley systems and curve arrays",
                "tools": [
                    "create_belt_wire — belt/track wire around pulleys",
                    "create_array_on_curve — stamp copies along a wire path",
                    "create_pulley_assembly — swept solid around pulley system",
                ],
            },
            "query": {
                "description": "Geometry inspection and measurement",
                "tools": [
                    "list_edges — all edges with index, endpoints, length, type",
                    "list_faces — all faces with index, area, center, normal, type",
                    "measure_object — volume, surface area, center of mass, bounding box",
                    "measure_distance — min distance between two objects",
                    "find_edges_near_point — nearest edges to a 3D point",
                    "find_faces_near_point — nearest faces to a 3D point",
                ],
            },
            "view": {
                "description": "Section cuts and exploded views",
                "tools": [
                    "section_view — cut object with a plane, preview cross-section",
                    "exploded_view — push assembly parts outward for inspection",
                ],
            },
        }

        if category is None:
            lines = ["Available tool categories:\n"]
            for cat, info in catalog.items():
                lines.append(f"  {cat} ({len(info['tools'])} tools) — {info['description']}")
            lines.append(f"\nTotal: {sum(len(v['tools']) for v in catalog.values())} tools")
            lines.append("\nCall discover_tools(category='<name>') to see tools in a category.")
            return "\n".join(lines)

        cat = category.lower().strip()
        if cat not in catalog:
            return f"FAIL Unknown category '{cat}'. Valid: {', '.join(catalog.keys())}"

        info = catalog[cat]
        lines = [f"{cat}: {info['description']}\n"]
        for tool_desc in info["tools"]:
            lines.append(f"  - {tool_desc}")
        return "\n".join(lines)
