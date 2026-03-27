"""Sweep and loft tools — create solids by sweeping or lofting profiles."""

import json
import math
from mcp.server.fastmcp import FastMCP

from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir, gp_Circ
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace,
)
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe, BRepOffsetAPI_ThruSections
from OCP.TopoDS import TopoDS

from caid_mcp.core import store_object, shape_volume, _unwrap


def _make_spline_wire(points_3d):
    """Build a wire from a BSpline through 3D points."""
    arr = TColgp_Array1OfPnt(1, len(points_3d))
    for i, (x, y, z) in enumerate(points_3d):
        arr.SetValue(i + 1, gp_Pnt(x, y, z))
    bspline = GeomAPI_PointsToBSpline(arr).Curve()
    edge = BRepBuilderAPI_MakeEdge(bspline).Edge()
    wire = BRepBuilderAPI_MakeWire(edge).Wire()
    return wire


def _make_polygon_wire(points_2d, z=0.0):
    """Build a closed wire from 2D polygon points at a given Z height."""
    wire_builder = BRepBuilderAPI_MakeWire()
    pts = [gp_Pnt(p[0], p[1], z) for p in points_2d]
    for i in range(len(pts)):
        p1 = pts[i]
        p2 = pts[(i + 1) % len(pts)]
        edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
        wire_builder.Add(edge)
    return wire_builder.Wire()


def _make_circle_wire(radius, z=0.0):
    """Build a circular wire at a given Z height, centered on origin."""
    ax = gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1))
    circ = gp_Circ(ax, radius)
    edge = BRepBuilderAPI_MakeEdge(circ).Edge()
    wire = BRepBuilderAPI_MakeWire(edge).Wire()
    return wire


def _make_rect_wire(length, width, z=0.0):
    """Build a rectangular wire at a given Z height, centered on origin."""
    hl = length / 2
    hw = width / 2
    pts = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
    return _make_polygon_wire(pts, z=z)


def register(mcp: FastMCP) -> None:
    """Register sweep and loft tools."""

    @mcp.tool()
    def sweep_along_path(
        name: str, profile_points: str, path_points: str,
        transition: str = "round", multisection: bool = False,
    ) -> str:
        """Create a solid by sweeping a 2D profile along a 3D path.

        The profile is defined as a polygon on the XY plane at the origin.
        The path is a spline through 3D points starting at the origin.
        For best results, start the path at [0, 0, 0].

        Args:
            name: Unique name for the resulting solid.
            profile_points: JSON array of [x, y] coordinate pairs defining the
                           cross-section profile (minimum 3 points).
                           Example: "[[-5, -5], [5, -5], [5, 5], [-5, 5]]"
            path_points: JSON array of [x, y, z] coordinate pairs defining the
                        sweep path (minimum 2 points).
                        Example: "[[0, 0, 0], [0, 0, 50], [20, 0, 80]]"
            transition: How corners are handled: "round", "transformed", or "right".
                       Default "round".
            multisection: If True, uses multisection sweep (better for complex paths).
        """
        try:
            profile = [tuple(p) for p in json.loads(profile_points)]
            path = [tuple(p) for p in json.loads(path_points)]

            if len(profile) < 3:
                return "FAIL Profile must have at least 3 points"
            if len(path) < 2:
                return "FAIL Path must have at least 2 points"
            if any(len(p) != 3 for p in path):
                return "FAIL Path points must be [x, y, z] (3D coordinates)"

            # Build path wire as spline through 3D points
            path_wire = _make_spline_wire(path)

            # Build profile polygon on XY plane at origin, then make a face
            profile_wire = _make_polygon_wire(profile, z=0.0)
            profile_face = BRepBuilderAPI_MakeFace(profile_wire).Face()

            # Sweep profile along path
            pipe = BRepOffsetAPI_MakePipe(path_wire, profile_face)
            pipe.Build()
            if not pipe.IsDone():
                return "FAIL Sweep operation failed"
            shape = pipe.Shape()

            vol = shape_volume(shape)
            store_object(name, shape)
            return f"OK Swept profile ({len(profile)} pts) along path ({len(path)} pts) -> '{name}' | volume={vol:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def sweep_circle_along_path(
        name: str, radius: float, path_points: str,
    ) -> str:
        """Create a tube/pipe by sweeping a circle along a 3D path.

        Convenience tool for the most common sweep: circular cross-section.
        For best results, start the path at [0, 0, 0].

        Args:
            name: Unique name for the resulting solid.
            radius: Radius of the circular cross-section (mm).
            path_points: JSON array of [x, y, z] coordinate pairs defining the
                        sweep path (minimum 2 points). Uses a spline through points.
                        Example: "[[0, 0, 0], [0, 0, 50], [20, 0, 80]]"
        """
        try:
            path = [tuple(p) for p in json.loads(path_points)]
            if len(path) < 2:
                return "FAIL Path must have at least 2 points"

            path_wire = _make_spline_wire(path)

            # Build circular profile face at origin
            circle_wire = _make_circle_wire(radius, z=0.0)
            circle_face = BRepBuilderAPI_MakeFace(circle_wire).Face()

            pipe = BRepOffsetAPI_MakePipe(path_wire, circle_face)
            pipe.Build()
            if not pipe.IsDone():
                return "FAIL Sweep operation failed"
            shape = pipe.Shape()

            vol = shape_volume(shape)
            store_object(name, shape)
            return f"OK Swept circle (r={radius}) along path ({len(path)} pts) -> '{name}' | volume={vol:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def loft_profiles(
        name: str, profiles: str, ruled: bool = False,
    ) -> str:
        """Create a solid by lofting between two or more 2D profiles at different heights.

        Each profile is a polygon at a specified Z height. The solid smoothly
        transitions between profiles.

        Args:
            name: Unique name for the resulting solid.
            profiles: JSON array of profile objects, each with:
                     - "z": height of this profile
                     - "points": [[x, y], ...] polygon vertices (minimum 3 points)
                     Example: '[
                       {"z": 0,  "points": [[-10,-10],[10,-10],[10,10],[-10,10]]},
                       {"z": 30, "points": [[-5,-5],[5,-5],[5,5],[-5,5]]},
                       {"z": 50, "points": [[-2,-2],[2,-2],[2,2],[-2,2]]}
                     ]'
            ruled: If True, use straight ruled surfaces between profiles.
                  If False (default), smooth interpolation.
        """
        try:
            data = json.loads(profiles)
            if len(data) < 2:
                return "FAIL Need at least 2 profiles to loft"

            # Sort by Z height
            data.sort(key=lambda p: p["z"])

            # Build ThruSections loft
            loft = BRepOffsetAPI_ThruSections(True, ruled)

            for prof in data:
                pts = [tuple(p) for p in prof["points"]]
                if len(pts) < 3:
                    return f"FAIL Profile at z={prof['z']} must have at least 3 points"
                wire = _make_polygon_wire(pts, z=prof["z"])
                loft.AddWire(wire)

            loft.Build()
            if not loft.IsDone():
                return "FAIL Loft operation failed"
            shape = loft.Shape()

            vol = shape_volume(shape)
            store_object(name, shape)
            return (
                f"OK Lofted {len(data)} profiles (z={data[0]['z']} to z={data[-1]['z']}) "
                f"-> '{name}' | volume={vol:.1f}mm3"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def loft_circle_to_rect(
        name: str, radius: float, length: float, width: float,
        height: float, circle_on_top: bool = False,
    ) -> str:
        """Loft from a circle to a rectangle (or vice versa).

        Common transition shape in mechanical design — duct transitions,
        adapters, funnels.

        Args:
            name: Unique name for the resulting solid.
            radius: Radius of the circular end (mm).
            length: Length of the rectangular end along X (mm).
            width: Width of the rectangular end along Y (mm).
            height: Distance between the two ends along Z (mm).
            circle_on_top: If True, circle is at the top. Default: circle at bottom.
        """
        try:
            loft = BRepOffsetAPI_ThruSections(True, False)

            if circle_on_top:
                rect_wire = _make_rect_wire(length, width, z=0.0)
                circle_wire = _make_circle_wire(radius, z=height)
                loft.AddWire(rect_wire)
                loft.AddWire(circle_wire)
            else:
                circle_wire = _make_circle_wire(radius, z=0.0)
                rect_wire = _make_rect_wire(length, width, z=height)
                loft.AddWire(circle_wire)
                loft.AddWire(rect_wire)

            loft.Build()
            if not loft.IsDone():
                return "FAIL Loft operation failed"
            shape = loft.Shape()

            vol = shape_volume(shape)
            store_object(name, shape)
            return f"OK Lofted circle-to-rect '{name}': r={radius}, {length}x{width}, h={height} | volume={vol:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"
