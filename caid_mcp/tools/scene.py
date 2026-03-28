"""Scene management tools (list, delete, clear, duplicate, info)."""

import json
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import (
    scene, require_object, store_object, object_summary,
    _unwrap, shape_volume, shape_area, shape_bounding_box,
)
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shape


def register(mcp: FastMCP) -> None:
    """Register all scene management tools."""

    @mcp.tool()
    def list_objects() -> str:
        """List all objects currently in the scene with their bounding box dimensions."""
        if not scene:
            return "Scene is empty. Create objects first."
        lines = [f"  - {object_summary(n, o)}" for n, o in scene.items()]
        return f"Scene ({len(scene)} objects):\n" + "\n".join(lines)

    @mcp.tool()
    def get_object_info(name: str) -> str:
        """Get detailed geometric information about an object.

        Args:
            name: Name of the object.
        """
        try:
            shape = require_object(name)
            bb = shape_bounding_box(shape)
            validity = caid.check_valid(shape)

            def _count_topo(topo_type):
                wrapped = _unwrap(shape)
                exp = TopExp_Explorer(wrapped, topo_type)
                count = 0
                while exp.More():
                    count += 1
                    exp.Next()
                return count

            info = {
                "name": name,
                "bounding_box": {
                    "x_min": round(bb["xmin"], 3), "x_max": round(bb["xmax"], 3),
                    "y_min": round(bb["ymin"], 3), "y_max": round(bb["ymax"], 3),
                    "z_min": round(bb["zmin"], 3), "z_max": round(bb["zmax"], 3),
                    "dimensions": f"{bb['xlen']:.2f} x {bb['ylen']:.2f} x {bb['zlen']:.2f} mm",
                },
                "volume_mm3": round(shape_volume(shape), 3),
                "num_faces": _count_topo(TopAbs_FACE),
                "num_edges": _count_topo(TopAbs_EDGE),
                "num_vertices": _count_topo(TopAbs_VERTEX),
                "is_valid": validity.get("is_valid", "unknown"),
            }
            return json.dumps(info, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def delete_object(name: str) -> str:
        """Remove an object from the scene.

        Args:
            name: Name of the object to delete.
        """
        if name in scene:
            del scene[name]
            return f"OK Deleted '{name}'"
        return f"FAIL Object '{name}' not found"

    @mcp.tool()
    def duplicate_object(name: str, new_name: str) -> str:
        """Create a copy of an existing object with a new name.

        Args:
            name: Source object name.
            new_name: Name for the copy.
        """
        try:
            shape = require_object(name)
            # Deep copy via BREP serialization to avoid shared references
            import tempfile
            from pathlib import Path
            wrapped = _unwrap(shape)
            tmp = Path(tempfile.mktemp(suffix=".brep"))
            try:
                BRepTools.Write_s(wrapped, str(tmp))
                builder = BRep_Builder()
                copy_shape = TopoDS_Shape()
                BRepTools.Read_s(copy_shape, str(tmp), builder)
                from caid._backend import get_backend
                store_object(new_name, get_backend().wrap_shape(copy_shape))
            finally:
                tmp.unlink(missing_ok=True)
            return f"OK Duplicated '{name}' -> '{new_name}'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def clear_scene() -> str:
        """Remove all objects from the scene."""
        count = len(scene)
        scene.clear()
        return f"OK Cleared scene ({count} objects removed)"
