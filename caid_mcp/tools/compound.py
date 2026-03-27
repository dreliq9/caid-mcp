"""Compound geometry tools — belt/pulley systems and curve arrays."""

import json
from typing import Optional
from caid.vector import Vector
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import require_object, store_object, format_result


def register(mcp: FastMCP) -> None:
    """Register compound geometry tools."""

    @mcp.tool()
    def create_belt_wire(name: str, pulleys: str, closed: bool = True) -> str:
        """Create a belt/track wire around a set of pulleys.

        The wire follows the outer tangent path connecting the pulleys.
        Pulley centers are assumed coplanar in the XY plane.

        Args:
            name: Name to store the resulting wire.
            pulleys: JSON array of [x, y, z, radius] arrays.
                     Example: '[[0,0,0,10], [50,0,0,15], [25,30,0,8]]'
            closed: If True, create a closed belt loop (default True).
        """
        try:
            data = json.loads(pulleys)
            pulley_list = [(Vector(p[0], p[1], p[2]), p[3]) for p in data]
            fr = caid.belt_wire(pulley_list, closed=closed)
            msg = format_result(fr, f"Created belt wire '{name}' with {len(pulley_list)} pulleys")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def create_array_on_curve(
        source_name: str, path_name: str, count: int,
        start: float = 0.0, end: float = 1.0, align_to_curve: bool = True,
        result_name: Optional[str] = None,
    ) -> str:
        """Stamp copies of a shape along a wire path.

        Args:
            source_name: Name of the shape to copy.
            path_name: Name of a wire/edge object in the scene to use as the path.
            count: Number of copies to place along the path.
            start: Start position on path (0.0 = beginning).
            end: End position on path (1.0 = end).
            align_to_curve: If True, rotate each copy to follow the curve tangent.
            result_name: Name for the result (default: {source_name}_array).
        """
        try:
            shape = require_object(source_name)
            path_wire = require_object(path_name)
            fr = caid.array_on_curve(shape, path_wire, count, start, end, align_to_curve)
            rname = result_name or f"{source_name}_array"
            msg = format_result(fr, f"Array of {count} copies -> '{rname}'")
            if fr.shape is not None:
                if isinstance(fr.shape, list):
                    for i, s in enumerate(fr.shape):
                        store_object(f"{rname}_{i}", s)
                    msg += f" | stored as {rname}_0 through {rname}_{len(fr.shape)-1}"
                else:
                    store_object(rname, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def create_pulley_assembly(name: str, pulleys: str, profile_name: str) -> str:
        """Create a swept solid belt around a pulley system.

        Calls belt_wire internally, then sweeps a 2D profile along the belt path.

        Args:
            name: Name for the resulting swept belt solid.
            pulleys: JSON array of [x, y, z, radius] arrays.
            profile_name: Name of a scene object to use as the sweep cross-section profile.
        """
        try:
            data = json.loads(pulleys)
            pulley_list = [(Vector(p[0], p[1], p[2]), p[3]) for p in data]
            profile = require_object(profile_name)
            fr = caid.pulley_assembly(pulley_list, profile)
            msg = format_result(fr, f"Created pulley assembly '{name}'")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"
