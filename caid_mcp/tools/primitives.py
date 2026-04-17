"""Primitive 3D shape creation tools — backed by caid and direct OCP.

Returns Pydantic ShapeResult models so clients get both human-readable text
(via __str__) and structured fields (volume_mm3, bbox, ok, reason). See
`caid_mcp.types` for the shared result models.
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any

from pydantic import Field

import caid
from caid.vector import Vector
from mcp.server.fastmcp import FastMCP

from caid_mcp.core import (
    store_object,
    require_object,
    shape_volume,
    shape_bounding_box,
)
from caid_mcp.types import BoundingBox, ShapeResult

from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.gp import gp_Pnt, gp_Vec, gp_Ax1, gp_Dir


def _polygon_wire(pts_2d, z: float = 0.0):
    """Build a closed OCP wire from a list of (x, y) 2D points on the given Z plane."""
    wb = BRepBuilderAPI_MakeWire()
    n = len(pts_2d)
    for i in range(n):
        x1, y1 = pts_2d[i]
        x2, y2 = pts_2d[(i + 1) % n]
        wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(x1, y1, z), gp_Pnt(x2, y2, z)).Edge())
    return wb.Wire()


def _finalize(name: str, kind: str, fr_or_shape: Any,
              cx: float, cy: float, cz: float) -> ShapeResult:
    """Common path: store the shape, optionally translate, measure, return ShapeResult.

    Accepts either a ForgeResult (from caid.* primitives) or a raw OCP shape
    (from BRepPrimAPI). On failure, returns ShapeResult(ok=False) with the
    diagnostic reason and hint from the ForgeResult.
    """
    if hasattr(fr_or_shape, "ok"):  # ForgeResult
        fr = fr_or_shape
        if fr.shape is None:
            return ShapeResult(
                ok=False, name=name, kind=kind,
                reason=fr.diagnostics.get("reason", "unknown error"),
                hint=fr.diagnostics.get("hint"),
            )
        store_object(name, fr.shape)
    else:
        store_object(name, fr_or_shape)

    if cx or cy or cz:
        shape = require_object(name)
        fr = caid.translate(shape, Vector(cx, cy, cz))
        if fr.shape is not None:
            store_object(name, fr.shape)

    shape = require_object(name)
    bb = shape_bounding_box(shape)
    return ShapeResult(
        ok=True,
        name=name,
        kind=kind,
        volume_mm3=round(shape_volume(shape), 3),
        bbox=BoundingBox(**{k: round(v, 3) for k, v in bb.items()}),
    )


def register(mcp: FastMCP) -> None:
    """Register all primitive creation tools."""

    @mcp.tool()
    def create_box(
        name: Annotated[str, Field(description="Unique scene-local name")],
        length: Annotated[float, Field(gt=0, description="Size along X axis (mm)")],
        width:  Annotated[float, Field(gt=0, description="Size along Y axis (mm)")],
        height: Annotated[float, Field(gt=0, description="Size along Z axis (mm)")],
        centered: Annotated[bool, Field(description="Center on origin if True, else corner at origin")] = True,
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a rectangular box (cuboid) and store it under `name`."""
        try:
            if centered:
                fr = caid.box(length, width, height,
                              origin=Vector(-length / 2, -width / 2, -height / 2))
            else:
                fr = caid.box(length, width, height)
            return _finalize(name, "box", fr, center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="box", reason=str(e))

    @mcp.tool()
    def create_cylinder(
        name: Annotated[str, Field(description="Unique scene-local name")],
        radius: Annotated[float, Field(gt=0, description="Cylinder radius (mm)")],
        height: Annotated[float, Field(gt=0, description="Cylinder height (mm)")],
        centered: Annotated[bool, Field(description="Center on origin if True")] = True,
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a cylinder along the Z axis and store it under `name`."""
        try:
            if centered:
                fr = caid.cylinder(radius, height, origin=Vector(0, 0, -height / 2))
            else:
                fr = caid.cylinder(radius, height)
            return _finalize(name, "cylinder", fr, center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="cylinder", reason=str(e))

    @mcp.tool()
    def create_sphere(
        name: Annotated[str, Field(description="Unique scene-local name")],
        radius: Annotated[float, Field(gt=0, description="Sphere radius (mm)")],
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a sphere centered at the given point."""
        try:
            return _finalize(name, "sphere", caid.sphere(radius),
                             center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="sphere", reason=str(e))

    @mcp.tool()
    def create_cone(
        name: Annotated[str, Field(description="Unique scene-local name")],
        radius1: Annotated[float, Field(ge=0, description="Bottom radius (mm)")],
        radius2: Annotated[float, Field(ge=0, description="Top radius (mm); 0 for a pointed cone")],
        height:  Annotated[float, Field(gt=0, description="Cone height (mm)")],
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a cone or truncated cone (frustum)."""
        try:
            return _finalize(name, "cone", caid.cone(radius1, radius2, height),
                             center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="cone", reason=str(e))

    @mcp.tool()
    def create_torus(
        name: Annotated[str, Field(description="Unique scene-local name")],
        major_radius: Annotated[float, Field(gt=0, description="Center-to-tube-center distance (mm)")],
        minor_radius: Annotated[float, Field(gt=0, description="Tube radius (mm)")],
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a torus (donut shape)."""
        try:
            return _finalize(name, "torus", caid.torus(major_radius, minor_radius),
                             center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="torus", reason=str(e))

    @mcp.tool()
    def create_extruded_polygon(
        name: Annotated[str, Field(description="Unique scene-local name")],
        points: Annotated[str, Field(description='JSON array of [x,y] pairs, e.g. "[[0,0],[10,0],[10,10]]"')],
        height: Annotated[float, Field(gt=0, description="Extrusion height (mm)")],
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a 3D solid by extruding a 2D polygon along Z."""
        try:
            pts = [tuple(p) for p in json.loads(points)]
            wire = _polygon_wire(pts)
            face = BRepBuilderAPI_MakeFace(wire).Face()
            shape = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape()
            return _finalize(name, "extruded_polygon", shape,
                             center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="extruded_polygon", reason=str(e))

    @mcp.tool()
    def create_revolved_profile(
        name: Annotated[str, Field(description="Unique scene-local name")],
        points: Annotated[str, Field(description='JSON array of [x,z] pairs in the XZ plane')],
        angle: Annotated[float, Field(gt=0, le=360, description="Revolution angle in degrees")] = 360.0,
        center_x: Annotated[float, Field(description="X position offset (mm)")] = 0,
        center_y: Annotated[float, Field(description="Y position offset (mm)")] = 0,
        center_z: Annotated[float, Field(description="Z position offset (mm)")] = 0,
    ) -> ShapeResult:
        """Create a solid of revolution by rotating a 2D profile around the Z axis.

        Profile points are in the XZ plane (first coord = X/radial,
        second coord = Z/axial).
        """
        try:
            pts = [tuple(p) for p in json.loads(points)]
            wb = BRepBuilderAPI_MakeWire()
            n = len(pts)
            for i in range(n):
                x1, z1 = pts[i]
                x2, z2 = pts[(i + 1) % n]
                wb.Add(BRepBuilderAPI_MakeEdge(
                    gp_Pnt(x1, 0, z1), gp_Pnt(x2, 0, z2)).Edge())
            face = BRepBuilderAPI_MakeFace(wb.Wire()).Face()
            axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
            shape = BRepPrimAPI_MakeRevol(face, axis, math.radians(angle)).Shape()
            return _finalize(name, "revolved_profile", shape,
                             center_x, center_y, center_z)
        except Exception as e:
            return ShapeResult(ok=False, name=name, kind="revolved_profile", reason=str(e))
