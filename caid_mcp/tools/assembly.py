"""Multi-part assembly management tools — backed by caid.assembly."""

from build123d import Vector
from mcp.server.fastmcp import FastMCP
import caid
from caid.assembly import Assembly, Part
from caid_mcp.core import require_object, store_object, assemblies, format_result


def register(mcp: FastMCP) -> None:
    """Register assembly management tools."""

    @mcp.tool()
    def create_assembly(name: str) -> str:
        """Create a new empty assembly.

        Args:
            name: Unique name for this assembly.
        """
        assemblies[name] = Assembly()
        return f"OK Created empty assembly '{name}'"

    @mcp.tool()
    def assembly_add(assembly_name: str, part_name: str) -> str:
        """Add a scene object as a part in an assembly.

        Args:
            assembly_name: Name of the assembly.
            part_name: Name of the scene object to add as a part.
        """
        try:
            asm = assemblies.get(assembly_name)
            if asm is None:
                return f"FAIL Assembly '{assembly_name}' not found"
            shape = require_object(part_name)
            assemblies[assembly_name] = asm.add(Part(part_name, shape))
            return f"OK Added '{part_name}' to assembly '{assembly_name}'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def assembly_move(
        assembly_name: str, part_name: str, x: float = 0, y: float = 0, z: float = 0,
    ) -> str:
        """Translate a part within an assembly.

        Args:
            assembly_name: Name of the assembly.
            part_name: Name of the part to move.
            x: Move distance along X (mm).
            y: Move distance along Y (mm).
            z: Move distance along Z (mm).
        """
        try:
            asm = assemblies.get(assembly_name)
            if asm is None:
                return f"FAIL Assembly '{assembly_name}' not found"
            assemblies[assembly_name] = asm.move(part_name, Vector(x, y, z))
            return f"OK Moved '{part_name}' by ({x}, {y}, {z}) in assembly '{assembly_name}'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def assembly_rotate(
        assembly_name: str, part_name: str,
        axis_x: float = 0, axis_y: float = 0, axis_z: float = 1, angle: float = 0,
    ) -> str:
        """Rotate a part within an assembly.

        Args:
            assembly_name: Name of the assembly.
            part_name: Name of the part to rotate.
            axis_x: X component of rotation axis.
            axis_y: Y component of rotation axis.
            axis_z: Z component of rotation axis.
            angle: Rotation angle in degrees.
        """
        try:
            asm = assemblies.get(assembly_name)
            if asm is None:
                return f"FAIL Assembly '{assembly_name}' not found"
            assemblies[assembly_name] = asm.rotate_part(
                part_name, Vector(0, 0, 0), Vector(axis_x, axis_y, axis_z), angle
            )
            return f"OK Rotated '{part_name}' by {angle} deg in assembly '{assembly_name}'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def assembly_merge(assembly_name: str, result_name: str) -> str:
        """Boolean union all parts in an assembly into a single shape.

        Args:
            assembly_name: Name of the assembly.
            result_name: Name to store the merged result under in the scene.
        """
        try:
            asm = assemblies.get(assembly_name)
            if asm is None:
                return f"FAIL Assembly '{assembly_name}' not found"
            fr = asm.merge_all()
            msg = format_result(fr, f"Merged assembly '{assembly_name}' -> '{result_name}'")
            if fr.shape is not None:
                store_object(result_name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"
