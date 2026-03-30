"""Curve and wireframe creation tools — standalone wires, arcs, splines, and curve operations."""

import json
import math
from typing import Optional
from mcp.server.fastmcp import FastMCP

from OCP.gp import gp_Pnt, gp_Dir, gp_Vec, gp_Ax2, gp_Circ, gp_Pln, gp_Trsf
from OCP.GC import GC_MakeArcOfCircle
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_Transform,
)
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepProj import BRepProj_Projection
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet2d
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX, TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Cone
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Tool

from caid_mcp.core import (
    store_object, require_object, _unwrap, shape_bounding_box,
    shape_volume,
)


def _wire_length(wire) -> float:
    """Total length of all edges in a wire."""
    raw = _unwrap(wire)
    total = 0.0
    exp = TopExp_Explorer(raw, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        curve = BRepAdaptor_Curve(edge)
        total += GCPnts_AbscissaPoint.Length_s(curve)
        exp.Next()
    return total


def _wire_edge_count(wire) -> int:
    """Count edges in a wire."""
    raw = _unwrap(wire)
    count = 0
    exp = TopExp_Explorer(raw, TopAbs_EDGE)
    while exp.More():
        count += 1
        exp.Next()
    return count


def _wire_endpoints(wire):
    """Get first and last points of an open wire."""
    raw = _unwrap(wire)
    edges = []
    exp = TopExp_Explorer(raw, TopAbs_EDGE)
    while exp.More():
        edges.append(TopoDS.Edge_s(exp.Current()))
        exp.Next()
    if not edges:
        return None, None
    c_first = BRepAdaptor_Curve(edges[0])
    c_last = BRepAdaptor_Curve(edges[-1])
    p_start = c_first.Value(c_first.FirstParameter())
    p_end = c_last.Value(c_last.LastParameter())
    return (p_start.X(), p_start.Y(), p_start.Z()), (p_end.X(), p_end.Y(), p_end.Z())


def _format_curve_result(name, wire, description):
    """Standard result formatting for curve tools."""
    length = _wire_length(wire)
    edges = _wire_edge_count(wire)
    bb = shape_bounding_box(wire)
    return (
        f"OK {description} -> '{name}' | "
        f"length={length:.2f}mm, {edges} edge(s), "
        f"bbox={bb['xlen']:.1f}x{bb['ylen']:.1f}x{bb['zlen']:.1f}mm"
    )


def register(mcp: FastMCP) -> None:
    """Register curve and wireframe tools."""

    @mcp.tool()
    def create_line(
        name: str,
        x1: float, y1: float, z1: float,
        x2: float, y2: float, z2: float,
    ) -> str:
        """Create a straight line (edge/wire) between two 3D points.

        Lines can be used as: sweep paths, construction geometry, trim tools,
        or building blocks for polylines and complex wireframes.

        Args:
            name: Unique name for this curve in the scene.
            x1: Start point X coordinate (mm).
            y1: Start point Y coordinate (mm).
            z1: Start point Z coordinate (mm).
            x2: End point X coordinate (mm).
            y2: End point Y coordinate (mm).
            z2: End point Z coordinate (mm).
        """
        try:
            p1 = gp_Pnt(x1, y1, z1)
            p2 = gp_Pnt(x2, y2, z2)
            if p1.IsEqual(p2, 1e-6):
                return "FAIL Start and end points are identical"
            edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
            wire = BRepBuilderAPI_MakeWire(edge).Wire()
            store_object(name, wire)
            length = p1.Distance(p2)
            return f"OK Created line '{name}': ({x1},{y1},{z1}) -> ({x2},{y2},{z2}) | length={length:.2f}mm"
        except Exception as e:
            return f"FAIL Error creating line: {e}"

    @mcp.tool()
    def create_arc(
        name: str,
        x1: float, y1: float, z1: float,
        x2: float, y2: float, z2: float,
        x3: float, y3: float, z3: float,
    ) -> str:
        """Create a circular arc through three 3D points.

        The arc passes through all three points in order: start -> mid -> end.
        Points must not be collinear.

        Args:
            name: Unique name for this curve.
            x1: Start point X (mm).
            y1: Start point Y (mm).
            z1: Start point Z (mm).
            x2: Mid point X (mm).
            y2: Mid point Y (mm).
            z2: Mid point Z (mm).
            x3: End point X (mm).
            y3: End point Y (mm).
            z3: End point Z (mm).
        """
        try:
            p1 = gp_Pnt(x1, y1, z1)
            p2 = gp_Pnt(x2, y2, z2)
            p3 = gp_Pnt(x3, y3, z3)
            arc_handle = GC_MakeArcOfCircle(p1, p2, p3).Value()
            edge = BRepBuilderAPI_MakeEdge(arc_handle).Edge()
            wire = BRepBuilderAPI_MakeWire(edge).Wire()
            store_object(name, wire)
            return _format_curve_result(name, wire, "Created arc through 3 points")
        except Exception as e:
            return f"FAIL Error creating arc: {e}"

    @mcp.tool()
    def create_circle(
        name: str,
        radius: float,
        center_x: float = 0, center_y: float = 0, center_z: float = 0,
        normal_x: float = 0, normal_y: float = 0, normal_z: float = 1,
    ) -> str:
        """Create a circular wire (closed curve, not a solid).

        Unlike create_cylinder, this creates a flat circle wire that can be
        used as: a sweep profile, a loft section, a construction reference,
        or input to extrude/revolve operations.

        Args:
            name: Unique name for this curve.
            radius: Circle radius (mm).
            center_x: Center X coordinate (default 0).
            center_y: Center Y coordinate (default 0).
            center_z: Center Z coordinate (default 0).
            normal_x: Normal vector X (default 0).
            normal_y: Normal vector Y (default 0).
            normal_z: Normal vector Z (default 1 = XY plane).
        """
        try:
            if radius <= 0:
                return "FAIL Radius must be positive"
            center = gp_Pnt(center_x, center_y, center_z)
            normal = gp_Dir(normal_x, normal_y, normal_z)
            ax2 = gp_Ax2(center, normal)
            circ = gp_Circ(ax2, radius)
            edge = BRepBuilderAPI_MakeEdge(circ).Edge()
            wire = BRepBuilderAPI_MakeWire(edge).Wire()
            store_object(name, wire)
            circumference = 2 * math.pi * radius
            return (
                f"OK Created circle '{name}': r={radius}mm at "
                f"({center_x},{center_y},{center_z}) | "
                f"circumference={circumference:.2f}mm"
            )
        except Exception as e:
            return f"FAIL Error creating circle: {e}"

    @mcp.tool()
    def create_polyline(
        name: str, points: str, closed: bool = False,
    ) -> str:
        """Create a polyline (connected straight-line segments) through 3D points.

        Polylines are the most common wireframe primitive. Use closed=True for
        polygonal outlines that can be extruded or used as sweep profiles.

        Args:
            name: Unique name for this curve.
            points: JSON array of [x, y, z] coordinate triples (minimum 2 points).
                    2D shorthand: [x, y] is accepted and treated as [x, y, 0].
                    Example: "[[0,0,0], [10,0,0], [10,10,5], [0,10,5]]"
            closed: If True, connect the last point back to the first (default False).
        """
        try:
            raw_pts = json.loads(points)
            if len(raw_pts) < 2:
                return "FAIL Need at least 2 points"

            # Normalize to 3D
            pts_3d = []
            for p in raw_pts:
                if len(p) == 2:
                    pts_3d.append(gp_Pnt(p[0], p[1], 0.0))
                elif len(p) == 3:
                    pts_3d.append(gp_Pnt(p[0], p[1], p[2]))
                else:
                    return f"FAIL Each point must be [x,y] or [x,y,z], got {len(p)} values"

            wire_builder = BRepBuilderAPI_MakeWire()
            n = len(pts_3d)
            segment_count = n if closed else n - 1
            for i in range(segment_count):
                p1 = pts_3d[i]
                p2 = pts_3d[(i + 1) % n]
                if p1.IsEqual(p2, 1e-6):
                    continue  # skip zero-length segments
                edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
                wire_builder.Add(edge)

            wire = wire_builder.Wire()
            store_object(name, wire)
            kind = "closed polyline" if closed else "polyline"
            return _format_curve_result(name, wire, f"Created {kind} with {n} points")
        except Exception as e:
            return f"FAIL Error creating polyline: {e}"

    @mcp.tool()
    def create_spline(
        name: str, points: str, closed: bool = False,
    ) -> str:
        """Create a smooth BSpline curve through 3D points.

        Splines produce smooth, organic curves ideal for sweep paths,
        freeform profiles, and aesthetic design. Unlike polylines, splines
        have continuous curvature through control points.

        Args:
            name: Unique name for this curve.
            points: JSON array of [x, y, z] coordinate triples (minimum 2 points).
                    2D shorthand: [x, y] is accepted and treated as [x, y, 0].
                    Example: "[[0,0,0], [5,3,0], [10,0,0], [15,-3,0], [20,0,0]]"
            closed: If True, close the spline into a loop (default False).
        """
        try:
            raw_pts = json.loads(points)
            if len(raw_pts) < 2:
                return "FAIL Need at least 2 points"

            # Normalize to 3D
            pts_3d = []
            for p in raw_pts:
                if len(p) == 2:
                    pts_3d.append((p[0], p[1], 0.0))
                elif len(p) == 3:
                    pts_3d.append((p[0], p[1], p[2]))
                else:
                    return f"FAIL Each point must be [x,y] or [x,y,z], got {len(p)} values"

            if closed:
                # Duplicate first point at end to close the curve
                pts_3d.append(pts_3d[0])

            arr = TColgp_Array1OfPnt(1, len(pts_3d))
            for i, (x, y, z) in enumerate(pts_3d):
                arr.SetValue(i + 1, gp_Pnt(x, y, z))

            bspline = GeomAPI_PointsToBSpline(arr).Curve()
            edge = BRepBuilderAPI_MakeEdge(bspline).Edge()
            wire = BRepBuilderAPI_MakeWire(edge).Wire()
            store_object(name, wire)
            kind = "closed spline" if closed else "spline"
            return _format_curve_result(
                name, wire,
                f"Created {kind} through {len(raw_pts)} points"
            )
        except Exception as e:
            return f"FAIL Error creating spline: {e}"

    @mcp.tool()
    def offset_curve(
        name: str, distance: float,
        result_name: Optional[str] = None,
    ) -> str:
        """Offset a planar wire inward or outward by a distance.

        Creates a parallel copy of a wire at a uniform distance. Positive
        distance offsets outward (larger), negative offsets inward (smaller).
        The source wire must be planar and closed.

        Common uses: PCB trace clearance, gasket outlines, tool path offsets,
        nested cutting patterns.

        Args:
            name: Source wire/curve name in the scene.
            distance: Offset distance in mm. Positive = outward, negative = inward.
            result_name: Name for the offset result (default: {name}_offset).
        """
        try:
            wire = require_object(name)
            raw = _unwrap(wire)

            # Build a face from the wire to get the offset reference plane
            face = BRepBuilderAPI_MakeFace(raw).Face()

            offset = BRepOffsetAPI_MakeOffset(face)
            offset.Perform(distance)
            if not offset.IsDone():
                return "FAIL Offset operation failed — wire may not be planar/closed or distance too large"

            result = offset.Shape()
            rname = result_name or f"{name}_offset"
            store_object(rname, result)
            return _format_curve_result(rname, result, f"Offset '{name}' by {distance}mm")
        except Exception as e:
            return f"FAIL Error offsetting curve: {e}"

    @mcp.tool()
    def project_curve(
        curve_name: str, target_name: str,
        direction_x: float = 0, direction_y: float = 0, direction_z: float = -1,
        result_name: Optional[str] = None,
    ) -> str:
        """Project a wire/curve onto a solid's surface.

        Projects the curve along a direction vector onto the target shape.
        The result is a wire that lies on the surface of the target —
        useful for creating trim lines, engraving paths, or split boundaries.

        Args:
            curve_name: Name of the wire/curve to project.
            target_name: Name of the solid/surface to project onto.
            direction_x: Projection direction X (default 0).
            direction_y: Projection direction Y (default 0).
            direction_z: Projection direction Z (default -1 = downward).
            result_name: Name for the projected wire (default: {curve_name}_projected).
        """
        try:
            wire = require_object(curve_name)
            target = require_object(target_name)
            raw_wire = _unwrap(wire)
            raw_target = _unwrap(target)

            direction = gp_Dir(direction_x, direction_y, direction_z)
            proj = BRepProj_Projection(raw_wire, raw_target, direction)

            if not proj.More():
                return "FAIL Projection produced no result — curve may not intersect target in the given direction"

            projected_wire = proj.Current()
            rname = result_name or f"{curve_name}_projected"
            store_object(rname, projected_wire)
            return _format_curve_result(rname, projected_wire, f"Projected '{curve_name}' onto '{target_name}'")
        except Exception as e:
            return f"FAIL Error projecting curve: {e}"

    @mcp.tool()
    def fillet_wire_corners(
        name: str, radius: float,
        result_name: Optional[str] = None,
    ) -> str:
        """Fillet (round) corners of a 2D planar wire.

        Replaces sharp corners where edges meet with smooth circular arcs.
        The wire must be planar and closed. All corners are filleted with
        the same radius.

        Common uses: smooth PCB outline corners, round bracket profiles,
        prepare profiles for extrusion/sweep.

        Args:
            name: Name of the wire/curve in the scene.
            radius: Fillet radius (mm). Must be smaller than the shortest edge.
            result_name: Name for the filleted wire (default: {name}_filleted).
        """
        try:
            wire = require_object(name)
            raw = _unwrap(wire)

            # Build a face from the planar wire — MakeFillet2d works on faces
            face = BRepBuilderAPI_MakeFace(raw).Face()
            fillet = BRepFilletAPI_MakeFillet2d(face)

            # Deduplicate vertices — TopExp_Explorer visits shared vertices
            # multiple times (once per adjacent edge)
            from OCP.BRep import BRep_Tool
            seen_coords = set()
            unique_vertices = []
            exp = TopExp_Explorer(face, TopAbs_VERTEX)
            while exp.More():
                vertex = TopoDS.Vertex_s(exp.Current())
                pt = BRep_Tool.Pnt_s(vertex)
                key = (round(pt.X(), 6), round(pt.Y(), 6), round(pt.Z(), 6))
                if key not in seen_coords:
                    seen_coords.add(key)
                    unique_vertices.append(vertex)
                exp.Next()

            vertex_count = 0
            for vertex in unique_vertices:
                try:
                    fillet.AddFillet(vertex, radius)
                    vertex_count += 1
                except Exception:
                    pass  # Skip vertices where fillet can't be applied

            if vertex_count == 0:
                return "FAIL No corners found to fillet — wire may have no sharp corners"

            fillet.Build()
            if not fillet.IsDone():
                return f"FAIL Fillet operation failed — radius {radius}mm may be too large for the wire geometry"

            result_face = fillet.Shape()

            # Extract the outer wire from the filleted face
            from OCP.BRepTools import BRepTools
            result_wire = BRepTools.OuterWire_s(TopoDS.Face_s(result_face))

            rname = result_name or f"{name}_filleted"
            store_object(rname, result_wire)
            return _format_curve_result(
                rname, result_wire,
                f"Filleted {vertex_count} corners of '{name}' with r={radius}mm"
            )
        except Exception as e:
            return f"FAIL Error filleting curves: {e}"

    # ========================== PHASE 3 — ADVANCED CURVES ======================

    @mcp.tool()
    def extend_curve(
        name: str,
        end: str = "end",
        distance: float = 10.0,
        result_name: Optional[str] = None,
    ) -> str:
        """Extend a curve beyond one of its endpoints by a given distance.

        The extension continues tangent to the curve at the specified endpoint,
        producing a natural continuation of the original shape.

        Args:
            name: Name of the wire/curve in the scene.
            end: Which end to extend — "start", "end", or "both".
            distance: Extension distance in mm (default 10).
            result_name: Name for the extended curve (default: overwrites original).
        """
        try:
            wire = require_object(name)
            raw = _unwrap(wire)

            # Collect edges
            edges = []
            exp = TopExp_Explorer(raw, TopAbs_EDGE)
            while exp.More():
                edges.append(TopoDS.Edge_s(exp.Current()))
                exp.Next()
            if not edges:
                return "FAIL No edges found in curve."

            extensions = []

            if end in ("start", "both"):
                first = edges[0]
                curve = BRepAdaptor_Curve(first)
                u = curve.FirstParameter()
                pt = curve.Value(u)
                # Tangent at start (negate for extension direction)
                du = 0.001
                pt2 = curve.Value(u + du)
                tang = gp_Vec(pt2.X() - pt.X(), pt2.Y() - pt.Y(), pt2.Z() - pt.Z())
                tang.Normalize()
                tang.Reverse()
                ext_pt = gp_Pnt(
                    pt.X() + tang.X() * distance,
                    pt.Y() + tang.Y() * distance,
                    pt.Z() + tang.Z() * distance,
                )
                ext_edge = BRepBuilderAPI_MakeEdge(ext_pt, pt).Edge()
                extensions.insert(0, ext_edge)

            if end in ("end", "both"):
                last = edges[-1]
                curve = BRepAdaptor_Curve(last)
                u = curve.LastParameter()
                pt = curve.Value(u)
                # Tangent at end
                du = 0.001
                pt2 = curve.Value(u - du)
                tang = gp_Vec(pt.X() - pt2.X(), pt.Y() - pt2.Y(), pt.Z() - pt2.Z())
                tang.Normalize()
                ext_pt = gp_Pnt(
                    pt.X() + tang.X() * distance,
                    pt.Y() + tang.Y() * distance,
                    pt.Z() + tang.Z() * distance,
                )
                ext_edge = BRepBuilderAPI_MakeEdge(pt, ext_pt).Edge()
                extensions.append(ext_edge)

            # Build new wire: start extension + original edges + end extension
            wire_builder = BRepBuilderAPI_MakeWire()
            all_edges = []
            if end in ("start", "both") and extensions:
                all_edges.append(extensions[0])
            all_edges.extend(edges)
            if end in ("end", "both") and extensions:
                all_edges.append(extensions[-1])
            for e in all_edges:
                wire_builder.Add(e)

            result = wire_builder.Wire()
            rname = result_name or name
            store_object(rname, result)
            return _format_curve_result(rname, result, f"Extended '{name}' {end} by {distance}mm")
        except Exception as e:
            return f"FAIL Error extending curve: {e}"

    @mcp.tool()
    def chamfer_wire_corners(
        name: str,
        distance: float,
        result_name: Optional[str] = None,
    ) -> str:
        """Chamfer (bevel) corners of a 2D planar wire.

        Replaces sharp corners with straight-line cuts at 45 degrees. Similar
        to fillet_wire_corners but produces flat bevels instead of rounded arcs.
        The wire must be planar and closed.

        Args:
            name: Name of the wire/curve in the scene.
            distance: Chamfer distance from the corner (mm).
            result_name: Name for the chamfered wire (default: {name}_chamfered).
        """
        try:
            wire = require_object(name)
            raw = _unwrap(wire)

            face = BRepBuilderAPI_MakeFace(raw).Face()
            fillet = BRepFilletAPI_MakeFillet2d(face)

            # Collect all edges from the face
            face_edges = []
            edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
            while edge_exp.More():
                face_edges.append(TopoDS.Edge_s(edge_exp.Current()))
                edge_exp.Next()

            # Build vertex → adjacent edges map
            from OCP.TopExp import TopExp
            vert_to_edges: dict[tuple, list] = {}
            for edge in face_edges:
                v1 = TopExp.FirstVertex_s(edge)
                v2 = TopExp.LastVertex_s(edge)
                for v in (v1, v2):
                    pt = BRep_Tool.Pnt_s(v)
                    key = (round(pt.X(), 6), round(pt.Y(), 6), round(pt.Z(), 6))
                    if key not in vert_to_edges:
                        vert_to_edges[key] = []
                    vert_to_edges[key].append(edge)

            vertex_count = 0
            for key, edges_at_vert in vert_to_edges.items():
                if len(edges_at_vert) >= 2:
                    try:
                        fillet.AddChamfer(edges_at_vert[0], edges_at_vert[1], distance, distance)
                        vertex_count += 1
                    except Exception:
                        pass

            if vertex_count == 0:
                return "FAIL No corners found to chamfer."

            fillet.Build()
            if not fillet.IsDone():
                return f"FAIL Chamfer failed — distance {distance}mm may be too large."

            result_face = fillet.Shape()
            result_wire = BRepTools.OuterWire_s(TopoDS.Face_s(result_face))

            rname = result_name or f"{name}_chamfered"
            store_object(rname, result_wire)
            return _format_curve_result(
                rname, result_wire,
                f"Chamfered {vertex_count} corners of '{name}' with d={distance}mm"
            )
        except Exception as e:
            return f"FAIL Error chamfering curves: {e}"

    @mcp.tool()
    def join_curves(
        names: str,
        result_name: str = "joined_wire",
    ) -> str:
        """Join multiple wires/edges into one connected wire.

        Attempts to connect the endpoints of multiple curves into a single
        continuous wire. Curves must be approximately end-to-end connected.

        Args:
            names: JSON array of curve names to join, e.g. '["line1", "arc1", "line2"]'.
            result_name: Name for the joined wire (default: "joined_wire").
        """
        try:
            curve_names = json.loads(names)
            if len(curve_names) < 2:
                return "FAIL Need at least 2 curves to join."

            wire_builder = BRepBuilderAPI_MakeWire()

            for cname in curve_names:
                obj = require_object(cname)
                raw = _unwrap(obj)
                # Add all edges from this object
                exp = TopExp_Explorer(raw, TopAbs_EDGE)
                while exp.More():
                    wire_builder.Add(TopoDS.Edge_s(exp.Current()))
                    exp.Next()

            if not wire_builder.IsDone():
                err = wire_builder.Error()
                return "FAIL Could not join curves — edges may not be connected end-to-end."

            result = wire_builder.Wire()
            store_object(result_name, result)
            return _format_curve_result(
                result_name, result,
                f"Joined {len(curve_names)} curves"
            )
        except json.JSONDecodeError:
            return "FAIL names must be a JSON array, e.g. '[\"line1\", \"arc1\"]'"
        except Exception as e:
            return f"FAIL Error joining curves: {e}"

    @mcp.tool()
    def reverse_curve(
        name: str,
        result_name: Optional[str] = None,
    ) -> str:
        """Reverse the direction of a wire/curve.

        Flips the wire so that the start becomes the end and vice versa.
        Useful before joining curves or when sweep direction matters.

        Args:
            name: Name of the wire/curve in the scene.
            result_name: Name for the reversed wire (default: overwrites original).
        """
        try:
            wire = require_object(name)
            raw = _unwrap(wire)

            reversed_wire = TopoDS.Wire_s(raw.Reversed())

            rname = result_name or name
            store_object(rname, reversed_wire)

            start, end = _wire_endpoints(reversed_wire)
            msg = f"OK Reversed '{name}' -> '{rname}'"
            if start and end:
                msg += f" | start=({start[0]:.1f},{start[1]:.1f},{start[2]:.1f}), end=({end[0]:.1f},{end[1]:.1f},{end[2]:.1f})"
            return msg
        except Exception as e:
            return f"FAIL Error reversing curve: {e}"

    # ========================== PHASE 3 — SURFACES ============================

    @mcp.tool()
    def extrude_surface(
        name: str,
        direction_x: float = 0,
        direction_y: float = 0,
        direction_z: float = 1,
        distance: float = 10.0,
        result_name: Optional[str] = None,
    ) -> str:
        """Extrude a face/surface along a direction to create a solid.

        Unlike the standard solid extrusion tools which work on wire profiles,
        this extrudes an existing face from a solid. Select a face using
        find_faces_near_point first.

        Can also extrude a planar wire into a sheet body (zero-thickness surface).

        Args:
            name: Name of the object containing the face to extrude.
            direction_x: Extrusion direction X component.
            direction_y: Extrusion direction Y component.
            direction_z: Extrusion direction Z component (default 1 = up).
            distance: Extrusion distance in mm.
            result_name: Name for the extruded result (default: {name}_extruded).
        """
        try:
            shape = require_object(name)
            raw = _unwrap(shape)

            vec = gp_Vec(direction_x, direction_y, direction_z)
            vec.Normalize()
            vec.Multiply(distance)

            prism = BRepPrimAPI_MakePrism(raw, vec)
            prism.Build()
            if not prism.IsDone():
                return "FAIL Extrusion failed."

            result = prism.Shape()
            rname = result_name or f"{name}_extruded"

            vol = shape_volume(result)
            store_object(rname, result)

            bb = shape_bounding_box(result)
            dims = f"{bb['xlen']:.1f}x{bb['ylen']:.1f}x{bb['zlen']:.1f}mm"
            return (
                f"OK Extruded '{name}' by {distance}mm along "
                f"({direction_x},{direction_y},{direction_z}) -> '{rname}' | "
                f"{dims}, volume={vol:.1f}mm\u00b3"
            )
        except Exception as e:
            return f"FAIL Error extruding surface: {e}"

    @mcp.tool()
    def unroll_surface(
        name: str,
        face_index: int = 0,
        result_name: Optional[str] = None,
    ) -> str:
        """Unroll (flatten) a developable surface into a flat pattern.

        Works on cylindrical and conical faces. Essential for sheet metal,
        packaging, and fabric design — shows what the flat blank looks like
        before bending.

        Only developable surfaces (cylinders, cones) can be exactly unrolled.
        Other surface types will be rejected.

        Args:
            name: Name of the object containing the surface.
            face_index: Index of the face to unroll (from list_faces output).
            result_name: Name for the flat pattern (default: {name}_unrolled).
        """
        try:
            shape = require_object(name)
            raw = _unwrap(shape)

            # Get the specified face
            faces = []
            exp = TopExp_Explorer(raw, TopAbs_FACE)
            while exp.More():
                faces.append(TopoDS.Face_s(exp.Current()))
                exp.Next()

            if face_index >= len(faces) or face_index < 0:
                return f"FAIL face_index {face_index} out of range (object has {len(faces)} faces)."

            face = faces[face_index]
            surf = BRepAdaptor_Surface(face)
            surf_type = surf.GetType()

            if surf_type == GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                radius = cyl.Radius()

                # Get the UV parameter range
                u_min = surf.FirstUParameter()
                u_max = surf.LastUParameter()
                v_min = surf.FirstVParameter()
                v_max = surf.LastVParameter()

                # Unrolled width = arc length = radius * delta_u
                arc_length = radius * (u_max - u_min)
                height = v_max - v_min

                # Create a flat rectangle representing the unrolled surface
                p1 = gp_Pnt(0, 0, 0)
                p2 = gp_Pnt(arc_length, 0, 0)
                p3 = gp_Pnt(arc_length, height, 0)
                p4 = gp_Pnt(0, height, 0)

                wire_builder = BRepBuilderAPI_MakeWire()
                wire_builder.Add(BRepBuilderAPI_MakeEdge(p1, p2).Edge())
                wire_builder.Add(BRepBuilderAPI_MakeEdge(p2, p3).Edge())
                wire_builder.Add(BRepBuilderAPI_MakeEdge(p3, p4).Edge())
                wire_builder.Add(BRepBuilderAPI_MakeEdge(p4, p1).Edge())
                flat_wire = wire_builder.Wire()
                flat_face = BRepBuilderAPI_MakeFace(flat_wire).Face()

                rname = result_name or f"{name}_unrolled"
                store_object(rname, flat_face)

                return (
                    f"OK Unrolled cylindrical face {face_index} of '{name}' -> '{rname}' | "
                    f"radius={radius:.2f}mm, arc={arc_length:.2f}mm, height={height:.2f}mm, "
                    f"flat size={arc_length:.2f} x {height:.2f} mm"
                )

            elif surf_type == GeomAbs_Cone:
                cone = surf.Cone()
                half_angle = cone.SemiAngle()
                ref_radius = cone.RefRadius()

                u_min = surf.FirstUParameter()
                u_max = surf.LastUParameter()
                v_min = surf.FirstVParameter()
                v_max = surf.LastVParameter()

                # For a cone, the unrolled shape is an annular sector
                # Slant distance from apex
                import math
                cos_a = math.cos(half_angle)
                if abs(cos_a) < 1e-10:
                    return "FAIL Cone has 90-degree half-angle (degenerate)."

                # Radii at v_min and v_max along the cone surface
                r_inner = ref_radius + v_min * math.sin(half_angle)
                r_outer = ref_radius + v_max * math.sin(half_angle)

                if r_inner < 0 or r_outer < 0:
                    return (
                        "FAIL Cone parameter range extends past the apex "
                        f"(r_inner={r_inner:.2f}, r_outer={r_outer:.2f}). "
                        "Select a face that doesn't cross the cone tip."
                    )

                # Slant distances from virtual apex
                if abs(math.sin(half_angle)) < 1e-10:
                    return "FAIL Cone half-angle too small (effectively a cylinder — use cylinder unroll)."

                s_inner = r_inner / math.sin(half_angle)
                s_outer = r_outer / math.sin(half_angle)

                # Unrolled angular span
                delta_u = u_max - u_min
                unrolled_angle = delta_u * math.sin(half_angle)

                # Create annular sector as a polyline approximation
                n_pts = max(32, int(unrolled_angle * 20))
                pts_outer = []
                pts_inner = []
                for i in range(n_pts + 1):
                    theta = -unrolled_angle / 2 + unrolled_angle * i / n_pts
                    pts_outer.append(gp_Pnt(s_outer * math.cos(theta), s_outer * math.sin(theta), 0))
                    pts_inner.append(gp_Pnt(s_inner * math.cos(theta), s_inner * math.sin(theta), 0))
                pts_inner.reverse()

                # Build wire: outer arc -> end line -> inner arc (reversed) -> start line
                wire_builder = BRepBuilderAPI_MakeWire()
                for i in range(len(pts_outer) - 1):
                    wire_builder.Add(BRepBuilderAPI_MakeEdge(pts_outer[i], pts_outer[i + 1]).Edge())
                wire_builder.Add(BRepBuilderAPI_MakeEdge(pts_outer[-1], pts_inner[0]).Edge())
                for i in range(len(pts_inner) - 1):
                    wire_builder.Add(BRepBuilderAPI_MakeEdge(pts_inner[i], pts_inner[i + 1]).Edge())
                wire_builder.Add(BRepBuilderAPI_MakeEdge(pts_inner[-1], pts_outer[0]).Edge())

                flat_wire = wire_builder.Wire()
                flat_face = BRepBuilderAPI_MakeFace(flat_wire).Face()

                rname = result_name or f"{name}_unrolled"
                store_object(rname, flat_face)

                return (
                    f"OK Unrolled conical face {face_index} of '{name}' -> '{rname}' | "
                    f"half_angle={math.degrees(half_angle):.1f}\u00b0, "
                    f"slant={s_inner:.2f}-{s_outer:.2f}mm, "
                    f"unrolled_angle={math.degrees(unrolled_angle):.1f}\u00b0"
                )

            else:
                type_names = {0: "plane", 1: "cylinder", 2: "cone", 3: "sphere",
                              4: "torus", 5: "bezier", 6: "bspline", 7: "revolution", 8: "extrusion"}
                stype = type_names.get(surf_type, f"type_{surf_type}")
                return (
                    f"FAIL Face {face_index} is a {stype} surface — only cylinder and cone "
                    f"surfaces can be exactly unrolled. Planes are already flat, and "
                    f"sphere/torus/bspline surfaces are not developable."
                )
        except Exception as e:
            return f"FAIL Error unrolling surface: {e}"
