"""Primitive 3D shape creation tools — backed by caid and direct OCP."""

import json
import math
from caid.vector import Vector
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import store_object, format_result, shape_volume, _unwrap

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.gp import gp_Pnt, gp_Vec, gp_Ax1, gp_Dir


def _polygon_wire(pts_2d, z=0.0):
    """Build a closed OCP wire from a list of (x, y) 2D points on the given Z plane."""
    wire_builder = BRepBuilderAPI_MakeWire()
    n = len(pts_2d)
    for i in range(n):
        x1, y1 = pts_2d[i]
        x2, y2 = pts_2d[(i + 1) % n]
        edge = BRepBuilderAPI_MakeEdge(gp_Pnt(x1, y1, z), gp_Pnt(x2, y2, z)).Edge()
        wire_builder.Add(edge)
    return wire_builder.Wire()


def register(mcp: FastMCP) -> None:
    """Register all primitive creation tools."""

    @mcp.tool()
    def create_box(
        name: str, length: float, width: float, height: float, centered: bool = True,
    ) -> str:
        """Create a rectangular box (cuboid).

        Args:
            name: Unique name for this object in the scene.
            length: Size along X axis (mm).
            width: Size along Y axis (mm).
            height: Size along Z axis (mm).
            centered: If True, center on origin. If False, corner at origin.
        """
        try:
            if centered:
                fr = caid.box(length, width, height,
                              origin=Vector(-length / 2, -width / 2, -height / 2))
            else:
                fr = caid.box(length, width, height)
            msg = format_result(fr, f"Created box '{name}': {length} x {width} x {height} mm")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error creating box: {e}"

    @mcp.tool()
    def create_cylinder(
        name: str, radius: float, height: float, centered: bool = True,
    ) -> str:
        """Create a cylinder.

        Args:
            name: Unique name for this object.
            radius: Radius of the cylinder (mm).
            height: Height of the cylinder (mm).
            centered: If True, center on origin.
        """
        try:
            if centered:
                fr = caid.cylinder(radius, height,
                                   origin=Vector(0, 0, -height / 2))
            else:
                fr = caid.cylinder(radius, height)
            msg = format_result(fr, f"Created cylinder '{name}': r={radius}, h={height} mm")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error creating cylinder: {e}"

    @mcp.tool()
    def create_sphere(name: str, radius: float) -> str:
        """Create a sphere centered at the origin.

        Args:
            name: Unique name for this object.
            radius: Radius of the sphere (mm).
        """
        try:
            fr = caid.sphere(radius)
            msg = format_result(fr, f"Created sphere '{name}': r={radius} mm")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error creating sphere: {e}"

    @mcp.tool()
    def create_cone(name: str, radius1: float, radius2: float, height: float) -> str:
        """Create a cone or truncated cone (frustum).

        Args:
            name: Unique name for this object.
            radius1: Bottom radius (mm).
            radius2: Top radius (mm). Use 0 for a pointed cone.
            height: Height of the cone (mm).
        """
        try:
            fr = caid.cone(radius1, radius2, height)
            msg = format_result(fr, f"Created cone '{name}': r1={radius1}, r2={radius2}, h={height} mm")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error creating cone: {e}"

    @mcp.tool()
    def create_torus(name: str, major_radius: float, minor_radius: float) -> str:
        """Create a torus (donut shape).

        Args:
            name: Unique name for this object.
            major_radius: Distance from center of torus to center of tube (mm).
            minor_radius: Radius of the tube (mm).
        """
        try:
            fr = caid.torus(major_radius, minor_radius)
            msg = format_result(fr, f"Created torus '{name}': R={major_radius}, r={minor_radius} mm")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error creating torus: {e}"

    @mcp.tool()
    def create_extruded_polygon(name: str, points: str, height: float) -> str:
        """Create a 3D solid by extruding a 2D polygon.

        Args:
            name: Unique name for this object.
            points: JSON array of [x, y] coordinate pairs defining the polygon.
                    Example: "[[0,0], [10,0], [10,10], [5,15], [0,10]]"
            height: Extrusion height (mm).
        """
        try:
            pts = [tuple(p) for p in json.loads(points)]
            wire = _polygon_wire(pts)
            face = BRepBuilderAPI_MakeFace(wire).Face()
            shape = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape()
            store_object(name, shape)
            vol = shape_volume(shape)
            return f"OK Created extruded polygon '{name}': {len(pts)} vertices, h={height} mm | volume={vol:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def create_revolved_profile(name: str, points: str, angle: float = 360.0) -> str:
        """Create a solid of revolution by rotating a 2D profile around the Y axis.

        The profile is defined in the XZ plane (first coord = X/radial,
        second coord = Z/axial). It is revolved around the Z axis, which
        matches the CadQuery XZ-workplane convention of revolving around
        the local Y direction mapped to world Z.

        Args:
            name: Unique name for this object.
            points: JSON array of [x, z] coordinate pairs defining the profile.
                    Example: "[[0,0], [5,0], [5,10], [3,12], [0,12]]"
            angle: Angle of revolution in degrees (default 360 for full revolution).
        """
        try:
            pts = [tuple(p) for p in json.loads(points)]
            wire_builder = BRepBuilderAPI_MakeWire()
            n = len(pts)
            for i in range(n):
                x1, z1 = pts[i]
                x2, z2 = pts[(i + 1) % n]
                edge = BRepBuilderAPI_MakeEdge(
                    gp_Pnt(x1, 0, z1), gp_Pnt(x2, 0, z2)
                ).Edge()
                wire_builder.Add(edge)
            wire = wire_builder.Wire()
            face = BRepBuilderAPI_MakeFace(wire).Face()
            axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
            shape = BRepPrimAPI_MakeRevol(face, axis, math.radians(angle)).Shape()
            store_object(name, shape)
            vol = shape_volume(shape)
            return f"OK Created revolved solid '{name}': {len(pts)} profile points, {angle} deg | volume={vol:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"
