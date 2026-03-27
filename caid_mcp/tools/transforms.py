"""Spatial transformation tools — backed by caid."""

from caid.vector import Vector
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import require_object, store_object, format_result


def register(mcp: FastMCP) -> None:
    """Register all transform tools."""

    @mcp.tool()
    def translate_object(name: str, x: float = 0, y: float = 0, z: float = 0) -> str:
        """Move an object by a given offset.

        Args:
            name: Name of existing object.
            x: Move distance along X (mm).
            y: Move distance along Y (mm).
            z: Move distance along Z (mm).
        """
        try:
            shape = require_object(name)
            fr = caid.translate(shape, Vector(x, y, z))
            msg = format_result(fr, f"Translated '{name}' by ({x}, {y}, {z})")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def rotate_object(
        name: str, axis_x: float = 0, axis_y: float = 0, axis_z: float = 1, angle: float = 0,
    ) -> str:
        """Rotate an object around an axis through the origin.

        Args:
            name: Name of existing object.
            axis_x: X component of rotation axis.
            axis_y: Y component of rotation axis.
            axis_z: Z component of rotation axis.
            angle: Rotation angle in degrees.
        """
        try:
            shape = require_object(name)
            fr = caid.rotate(shape, Vector(0, 0, 0), Vector(axis_x, axis_y, axis_z), angle)
            msg = format_result(fr, f"Rotated '{name}' by {angle} deg around ({axis_x}, {axis_y}, {axis_z})")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def scale_object(name: str, factor: float) -> str:
        """Uniformly scale an object.

        Args:
            name: Name of existing object.
            factor: Scale factor (e.g., 2.0 = double size, 0.5 = half size).
        """
        try:
            shape = require_object(name)
            fr = caid.scale(shape, factor)
            msg = format_result(fr, f"Scaled '{name}' by factor {factor}")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def mirror_object(name: str, new_name: str, plane: str = "YZ") -> str:
        """Mirror (reflect) an object across a plane, creating a new object.

        Args:
            name: Name of the source object.
            new_name: Name for the mirrored copy.
            plane: Mirror plane — "YZ" (across X), "XZ" (across Y), or "XY" (across Z).
        """
        try:
            shape = require_object(name)
            normal_map = {
                "YZ": Vector(1, 0, 0),
                "XZ": Vector(0, 1, 0),
                "XY": Vector(0, 0, 1),
            }
            normal = normal_map.get(plane.upper())
            if normal is None:
                return f"FAIL Unknown plane '{plane}'. Use YZ, XZ, or XY."
            fr = caid.mirror(shape, Vector(0, 0, 0), normal)
            msg = format_result(fr, f"Mirrored '{name}' across {plane} -> '{new_name}'")
            if fr.shape is not None:
                store_object(new_name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"
