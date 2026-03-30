"""Scene organization tools — object properties, groups, and layers."""

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP

from caid_mcp.core import (
    scene, require_object, object_properties, groups, layers,
)


def register(mcp: FastMCP) -> None:
    """Register scene organization tools."""

    # ========================== OBJECT PROPERTIES ==============================

    @mcp.tool()
    def set_object_properties(
        name: str,
        color: Optional[str] = None,
        visible: Optional[bool] = None,
        locked: Optional[bool] = None,
        material: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> str:
        """Set display and organization properties on an object.

        Properties control how the object appears in renders and how it's
        organized. Only provided properties are changed — omit a property
        to leave it unchanged.

        Args:
            name: Name of the object.
            color: Display color as hex string (e.g. "#ff0000" for red).
                  Used by render_scene for per-object coloring.
            visible: If False, object is hidden from renders.
            locked: If True, object is protected from modification.
            material: Material label (for reference/display, e.g. "aluminum").
            layer: Layer name to assign this object to.
        """
        try:
            require_object(name)  # verify it exists
            props = object_properties.get(name, {})

            if color is not None:
                props["color"] = color
            if visible is not None:
                props["visible"] = visible
            if locked is not None:
                props["locked"] = locked
            if material is not None:
                props["material"] = material
            if layer is not None:
                if layer not in layers:
                    return f"FAIL Layer '{layer}' does not exist. Create it first with create_layer."
                props["layer"] = layer

            object_properties[name] = props

            summary = ", ".join(f"{k}={v}" for k, v in props.items())
            return f"OK Properties for '{name}': {summary}"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def get_object_properties(name: str) -> str:
        """Get all display and organization properties of an object.

        Args:
            name: Name of the object.
        """
        try:
            require_object(name)
            props = object_properties.get(name, {})
            result = {
                "name": name,
                "color": props.get("color", None),
                "visible": props.get("visible", True),
                "locked": props.get("locked", False),
                "material": props.get("material", None),
                "layer": props.get("layer", "0"),
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    # ========================== GROUPS =========================================

    @mcp.tool()
    def create_group(group_name: str, object_names: str) -> str:
        """Create a named group containing multiple objects.

        Groups are lightweight organizational containers — they don't affect
        geometry. Use them to logically organize parts of a design.

        Args:
            group_name: Name for the new group.
            object_names: JSON array of object names to include,
                         e.g. '["bracket", "bolt1", "bolt2"]'.
        """
        try:
            names = json.loads(object_names)
            if not names:
                return "FAIL Provide at least one object name."

            # Verify all objects exist
            missing = [n for n in names if n not in scene]
            if missing:
                return f"FAIL Objects not found: {', '.join(missing)}"

            groups[group_name] = list(names)
            return f"OK Created group '{group_name}' with {len(names)} objects: {', '.join(names)}"
        except json.JSONDecodeError:
            return "FAIL object_names must be a JSON array, e.g. '[\"a\", \"b\"]'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def ungroup(group_name: str) -> str:
        """Remove a group (does not delete the objects, only the grouping).

        Args:
            group_name: Name of the group to remove.
        """
        if group_name in groups:
            members = groups.pop(group_name)
            return f"OK Removed group '{group_name}' (objects {', '.join(members)} are still in the scene)"
        return f"FAIL Group '{group_name}' not found."

    @mcp.tool()
    def list_groups() -> str:
        """List all groups and their members."""
        if not groups:
            return "No groups defined."
        lines = []
        for gname, members in groups.items():
            # Check which members still exist
            existing = [m for m in members if m in scene]
            missing = [m for m in members if m not in scene]
            line = f"  {gname}: {', '.join(existing)}"
            if missing:
                line += f" (missing: {', '.join(missing)})"
            lines.append(line)
        return f"Groups ({len(groups)}):\n" + "\n".join(lines)

    # ========================== LAYERS =========================================

    @mcp.tool()
    def create_layer(
        layer_name: str,
        color: str = "#888888",
        visible: bool = True,
    ) -> str:
        """Create a new layer for organizing objects.

        Objects default to layer "0". Assign objects to layers with
        set_object_properties(name, layer="layer_name"). Layer visibility
        controls whether objects on that layer appear in renders.

        Args:
            layer_name: Name for the new layer.
            color: Default display color for objects on this layer (hex string).
            visible: Whether objects on this layer are visible in renders.
        """
        if layer_name in layers:
            return f"FAIL Layer '{layer_name}' already exists. Delete it first or choose another name."
        layers[layer_name] = {"color": color, "visible": visible}
        vis = "visible" if visible else "hidden"
        return f"OK Created layer '{layer_name}' (color={color}, {vis})"

    @mcp.tool()
    def list_layers() -> str:
        """List all layers with their properties and object counts."""
        if not layers:
            return "No layers defined."

        lines = []
        for lname, lprops in layers.items():
            # Count objects on this layer
            count = sum(
                1 for name in scene
                if object_properties.get(name, {}).get("layer", "0") == lname
            )
            vis = "visible" if lprops.get("visible", True) else "hidden"
            lines.append(f"  {lname}: color={lprops.get('color', 'default')}, {vis}, {count} objects")
        return f"Layers ({len(layers)}):\n" + "\n".join(lines)
