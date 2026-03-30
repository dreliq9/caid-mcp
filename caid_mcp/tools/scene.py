"""Scene management tools (list, delete, clear, duplicate, info, server_info)."""

import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import (
    scene, require_object, store_object, object_summary,
    _unwrap, shape_bounding_box,
    OUTPUT_DIR, groups, layers, object_properties,
)

_DEFAULT_LAYERS = {"0": {"color": "#4a90d9", "visible": True}}
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
    def delete_object(name: str) -> str:
        """Remove an object from the scene.

        Args:
            name: Name of the object to delete.
        """
        if name in scene:
            del scene[name]
            object_properties.pop(name, None)
            for members in groups.values():
                if name in members:
                    members.remove(name)
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
        object_properties.clear()
        groups.clear()
        layers.clear()
        layers.update(_DEFAULT_LAYERS)
        return f"OK Cleared scene ({count} objects removed)"

    @mcp.tool()
    def server_info() -> str:
        """Get CAiD MCP server information.

        Returns version, tool count, output directory, scene statistics,
        and available tool categories. Useful for LLM self-orientation
        at the start of a conversation.
        """
        categories = [
            "primitives", "modify", "transforms", "booleans", "scene",
            "export", "advanced", "heal", "io", "assembly", "compound",
            "query", "view", "sweep", "fasteners", "history",
            "parts_warehouse", "parts_library", "parts_user",
            "curves", "split", "scene_org",
        ]
        info = {
            "server": "CAiD MCP",
            "version": "0.5.0",
            "tools": 107,
            "modules": len(categories),
            "categories": categories,
            "output_directory": str(OUTPUT_DIR),
            "scene": {
                "objects": len(scene),
                "groups": len(groups),
                "layers": len(layers),
            },
        }
        return json.dumps(info, indent=2)
