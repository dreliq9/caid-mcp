"""Primitive 3D shape creation tools — backed by caid."""

import json
from build123d import Vector
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import store_object, format_result


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
            from build123d import BuildPart, BuildSketch, Polyline, make_face, extrude as b123d_extrude
            with BuildPart() as part:
                with BuildSketch():
                    Polyline(*pts, pts[0])
                    make_face()
                b123d_extrude(amount=height)
            shape = part.part.solids()[0]
            store_object(name, shape)
            return f"OK Created extruded polygon '{name}': {len(pts)} vertices, h={height} mm | volume={shape.volume:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def create_revolved_profile(name: str, points: str, angle: float = 360.0) -> str:
        """Create a solid of revolution by rotating a 2D profile around the Y axis.

        Args:
            name: Unique name for this object.
            points: JSON array of [x, y] coordinate pairs defining the profile.
                    Example: "[[0,0], [5,0], [5,10], [3,12], [0,12]]"
            angle: Angle of revolution in degrees (default 360 for full revolution).
        """
        try:
            pts = [tuple(p) for p in json.loads(points)]
            from build123d import BuildPart, BuildSketch, Polyline, make_face, revolve as b123d_revolve, Axis, Plane
            with BuildPart() as part:
                with BuildSketch(Plane.XZ):
                    Polyline(*pts, pts[0])
                    make_face()
                b123d_revolve(axis=Axis.Y, revolution_arc=angle)
            shape = part.part.solids()[0]
            store_object(name, shape)
            return f"OK Created revolved solid '{name}': {len(pts)} profile points, {angle} deg | volume={shape.volume:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"
