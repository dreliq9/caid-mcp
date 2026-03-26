"""Advanced tools: script execution, patterns, and the tool router."""

import json
import subprocess
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Optional

import cadquery as cq
from cadquery import Vector, exporters
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import scene, require_object, store_object, OUTPUT_DIR, log


def _run_script_in_subprocess(
    script: str,
    result_brep_path: Optional[Path] = None,
    timeout: int = 120,
) -> dict:
    """Run a CadQuery script in an isolated subprocess.

    Returns dict with keys: ok (bool), stdout (str), stderr (str), returncode (int).
    If result_brep_path is set, the subprocess wrapper will export the 'result'
    variable as a BREP file at that path.
    """
    # Build a wrapper script that executes user code in a fresh Python process
    export_snippet = ""
    if result_brep_path:
        export_snippet = (
            'if "result" in dir() or "result" in globals():\n'
            '    import cadquery as _cq\n'
            '    from caid.result import ForgeResult as _FR\n'
            '    _obj = result\n'
            '    if isinstance(_obj, _FR):\n'
            '        _obj = _obj.unwrap()\n'
            '    elif isinstance(_obj, _cq.Workplane):\n'
            '        _obj = _obj.val()\n'
            '    from OCP.BRepTools import BRepTools\n'
            f'    BRepTools.Write_s(_obj.wrapped, "{result_brep_path}")\n'
            '    print("__RESULT_EXPORTED__")\n'
        )

    wrapper = (
        "import cadquery as cq\n"
        "from cadquery import Vector, exporters\n"
        "import caid\n"
        "from pathlib import Path\n"
        f"OUTPUT_DIR = Path(\"{OUTPUT_DIR}\")\n"
        "scene = {}\n"
        "\n"
        f"{script}\n"
        "\n"
        f"{export_snippet}"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(OUTPUT_DIR),
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Script timed out after {timeout}s",
            "returncode": -1,
        }


def register(mcp: FastMCP) -> None:
    """Register advanced tools and the tool router."""

    @mcp.tool()
    def run_cadquery_script(script: str, result_name: Optional[str] = None) -> str:
        """Execute CadQuery/CAiD Python code in an isolated subprocess.

        Runs in a separate process so that OCCT segfaults cannot crash the
        MCP server. The subprocess has access to:
        - cq: the cadquery module
        - caid: the CAiD module (validated geometry operations)
        - Vector: cadquery.Vector for convenience
        - OUTPUT_DIR: Path to output directory
        - exporters: CadQuery export module

        Note: the subprocess does NOT have access to the live scene dict.
        To use existing scene objects, import them from STEP/BREP files.

        If the script sets a variable called 'result', it will be stored under
        result_name by exporting as BREP and re-importing in the server process.

        Args:
            script: Python code to execute.
            result_name: If provided, store the 'result' variable under this name.
        """
        brep_path = None
        if result_name:
            brep_path = OUTPUT_DIR / f"_subprocess_result_{result_name}.brep"

        run = _run_script_in_subprocess(script, result_brep_path=brep_path)

        if run["returncode"] == 139 or run["returncode"] == -11:
            log.warning("CadQuery script segfaulted (OCCT crash) — server is safe")
            return (
                "FAIL Script crashed with a segfault (OCCT kernel error). "
                "The MCP server is still running. This typically happens with "
                "complex boolean operations on swept/helical geometry. "
                "Try simplifying the operation or using a different approach."
            )

        if not run["ok"]:
            stderr = run["stderr"].strip()
            if run["returncode"] == -1:
                return f"FAIL {stderr}"
            return f"FAIL Script error (exit {run['returncode']}):\n{stderr}"

        # If we got a result, import the BREP back into the scene
        if result_name and brep_path and brep_path.exists():
            if "__RESULT_EXPORTED__" in run["stdout"]:
                try:
                    fr = caid.from_brep(brep_path)
                    if fr.ok:
                        store_object(result_name, fr.shape)
                        brep_path.unlink(missing_ok=True)
                        stdout_clean = run["stdout"].replace("__RESULT_EXPORTED__", "").strip()
                        msg = f"OK Script executed. Result stored as '{result_name}'."
                        if stdout_clean:
                            msg += f"\nOutput: {stdout_clean}"
                        return msg
                    else:
                        brep_path.unlink(missing_ok=True)
                        return f"FAIL Script ran but result BREP failed to reimport: {fr.diagnostics}"
                except Exception as e:
                    brep_path.unlink(missing_ok=True)
                    return f"FAIL Script ran but result BREP reimport error: {e}"
            else:
                brep_path.unlink(missing_ok=True)

        stdout_clean = run["stdout"].strip()
        msg = "OK Script executed successfully."
        if stdout_clean:
            msg += f"\nOutput: {stdout_clean}"
        return msg

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
