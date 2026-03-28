"""Shape validation and repair tools — backed by caid.heal."""

import json
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import require_object, store_object, format_result, _unwrap
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE


def register(mcp: FastMCP) -> None:
    """Register healing tools."""

    @mcp.tool()
    def check_object_valid(name: str) -> str:
        """Run OCCT validity checks on an object.

        Returns detailed validity info: face/edge/vertex counts,
        degenerate faces, bad edges, self-intersections.

        Args:
            name: Name of the object to check.
        """
        try:
            shape = require_object(name)
            result = caid.check_valid(shape)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def heal_object(name: str, precision: float = 0.001) -> str:
        """Attempt to fix degenerate geometry using OCCT's ShapeFix suite.

        Runs ShapeFix_Shape, ShapeFix_Solid, and ShapeUpgrade_UnifySameDomain.
        Stores the healed shape back under the same name.

        Args:
            name: Name of existing object to heal.
            precision: Healing precision (mm). Default 0.001.
        """
        try:
            shape = require_object(name)
            fr = caid.heal(shape, precision)
            msg = format_result(fr, f"Healed '{name}'")
            if fr.shape is not None:
                store_object(name, fr.shape)
                checks = fr.diagnostics.get("checks_after", {})
                if checks:
                    msg += f" | valid={checks.get('is_valid', '?')}, faces={checks.get('n_faces', '?')}"
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def simplify_object(name: str, tolerance: float = 0.01) -> str:
        """Merge coplanar/co-cylindrical faces to simplify geometry after booleans.

        Uses ShapeUpgrade_UnifySameDomain. Stores the simplified shape back.

        Args:
            name: Name of existing object to simplify.
            tolerance: Tolerance for face merging (mm). Default 0.01.
        """
        try:
            shape = require_object(name)

            def _count_faces(s):
                wrapped = _unwrap(s)
                exp = TopExp_Explorer(wrapped, TopAbs_FACE)
                count = 0
                while exp.More():
                    count += 1
                    exp.Next()
                return count

            faces_before = _count_faces(shape)
            fr = caid.simplify(shape, tolerance)
            msg = format_result(fr, f"Simplified '{name}'")
            if fr.shape is not None:
                store_object(name, fr.shape)
                faces_after = _count_faces(fr.shape)
                msg += f" | faces: {faces_before} -> {faces_after}"
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"
