"""Scene management tools (list, delete, clear, duplicate, info)."""

import json
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import scene, require_object, store_object, object_summary


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
            bb = shape.BoundingBox()
            validity = caid.check_valid(shape)
            info = {
                "name": name,
                "bounding_box": {
                    "x_min": round(bb.xmin, 3), "x_max": round(bb.xmax, 3),
                    "y_min": round(bb.ymin, 3), "y_max": round(bb.ymax, 3),
                    "z_min": round(bb.zmin, 3), "z_max": round(bb.zmax, 3),
                    "dimensions": f"{bb.xlen:.2f} x {bb.ylen:.2f} x {bb.zlen:.2f} mm",
                },
                "center": f"({bb.center.x:.2f}, {bb.center.y:.2f}, {bb.center.z:.2f})",
                "volume_mm3": round(shape.Volume(), 3),
                "num_faces": len(shape.Faces()),
                "num_edges": len(shape.Edges()),
                "num_vertices": len(shape.Vertices()),
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
            store_object(new_name, shape)
            return f"OK Duplicated '{name}' -> '{new_name}'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def clear_scene() -> str:
        """Remove all objects from the scene."""
        count = len(scene)
        scene.clear()
        return f"OK Cleared scene ({count} objects removed)"
