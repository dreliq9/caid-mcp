"""Geometry query and measurement tools — lets the LLM see what it built."""

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP
import cadquery as cq
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from caid_mcp.core import scene, require_object


def _edge_info(idx: int, edge) -> dict:
    """Extract useful info from a single Edge."""
    verts = edge.Vertices()
    start = verts[0].Center() if len(verts) > 0 else None
    end = verts[1].Center() if len(verts) > 1 else verts[0].Center()
    mid = edge.Center()
    return {
        "index": idx,
        "length_mm": round(edge.Length(), 3),
        "start": [round(start.x, 3), round(start.y, 3), round(start.z, 3)] if start else None,
        "end": [round(end.x, 3), round(end.y, 3), round(end.z, 3)],
        "midpoint": [round(mid.x, 3), round(mid.y, 3), round(mid.z, 3)],
        "type": edge.geomType(),
    }


def _face_info(idx: int, face) -> dict:
    """Extract useful info from a single Face."""
    center = face.Center()
    bb = face.BoundingBox()
    # Normal at center of face
    try:
        normal = face.normalAt(face.Center())
        normal_vec = [round(normal.x, 3), round(normal.y, 3), round(normal.z, 3)]
    except Exception:
        normal_vec = None
    return {
        "index": idx,
        "area_mm2": round(face.Area(), 3),
        "center": [round(center.x, 3), round(center.y, 3), round(center.z, 3)],
        "normal": normal_vec,
        "type": face.geomType(),
        "bounds": {
            "x": [round(bb.xmin, 3), round(bb.xmax, 3)],
            "y": [round(bb.ymin, 3), round(bb.ymax, 3)],
            "z": [round(bb.zmin, 3), round(bb.zmax, 3)],
        },
        "num_edges": len(face.Edges()),
    }


def register(mcp: FastMCP) -> None:
    """Register geometry query and measurement tools."""

    @mcp.tool()
    def list_edges(name: str, face_selector: Optional[str] = None) -> str:
        """List all edges of an object with index, endpoints, length, and type.

        Use this to understand the geometry before applying fillet/chamfer.
        Each edge gets a stable index you can reference in select_edges.

        Args:
            name: Name of the object.
            face_selector: Optional CadQuery face selector to limit to edges of a
                          specific face (e.g. ">Z" for top face, "<Z" for bottom).
                          If omitted, lists all edges on the solid.
        """
        try:
            shape = require_object(name)
            if face_selector:
                wp = cq.Workplane("XY").add(shape)
                faces = wp.faces(face_selector).vals()
                edges = []
                for f in faces:
                    edges.extend(f.Edges())
            else:
                edges = shape.Edges()

            if not edges:
                return f"No edges found on '{name}'" + (f" with selector '{face_selector}'" if face_selector else "")

            result = [_edge_info(i, e) for i, e in enumerate(edges)]
            return json.dumps({
                "object": name,
                "face_selector": face_selector,
                "count": len(result),
                "edges": result,
            }, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def list_faces(name: str) -> str:
        """List all faces of an object with index, area, center, normal, and type.

        Use this to understand which faces are where before shelling, drilling,
        or selecting edges on a specific face.

        Args:
            name: Name of the object.
        """
        try:
            shape = require_object(name)
            faces = shape.Faces()
            result = [_face_info(i, f) for i, f in enumerate(faces)]
            return json.dumps({
                "object": name,
                "count": len(result),
                "faces": result,
            }, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def measure_distance(name_a: str, name_b: str) -> str:
        """Measure the minimum distance between two objects.

        Args:
            name_a: First object name.
            name_b: Second object name.
        """
        try:
            shape_a = require_object(name_a)
            shape_b = require_object(name_b)
            dist_calc = BRepExtrema_DistShapeShape(shape_a.wrapped, shape_b.wrapped)
            dist_calc.Perform()
            dist = dist_calc.Value()
            return json.dumps({
                "object_a": name_a,
                "object_b": name_b,
                "min_distance_mm": round(dist, 4),
            }, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def measure_object(name: str) -> str:
        """Get comprehensive measurements: volume, surface area, center of mass,
        bounding box, and counts of faces/edges/vertices.

        Args:
            name: Name of the object.
        """
        try:
            shape = require_object(name)
            bb = shape.BoundingBox()
            com = shape.Center()
            info = {
                "name": name,
                "volume_mm3": round(shape.Volume(), 3),
                "surface_area_mm2": round(shape.Area(), 3),
                "center_of_mass": [round(com.x, 3), round(com.y, 3), round(com.z, 3)],
                "bounding_box": {
                    "min": [round(bb.xmin, 3), round(bb.ymin, 3), round(bb.zmin, 3)],
                    "max": [round(bb.xmax, 3), round(bb.ymax, 3), round(bb.zmax, 3)],
                    "size": [round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)],
                },
                "num_faces": len(shape.Faces()),
                "num_edges": len(shape.Edges()),
                "num_vertices": len(shape.Vertices()),
            }
            return json.dumps(info, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def find_edges_near_point(
        name: str, x: float, y: float, z: float, count: int = 3
    ) -> str:
        """Find the edges closest to a given point. Returns the nearest edges
        sorted by distance, with their index and geometry.

        Use this when you know roughly WHERE on the object you want to
        fillet/chamfer but don't know the edge index.

        Args:
            name: Name of the object.
            x: X coordinate of the target point.
            y: Y coordinate of the target point.
            z: Z coordinate of the target point.
            count: Number of nearest edges to return (default 3).
        """
        try:
            shape = require_object(name)
            target = cq.Vector(x, y, z)
            edges = shape.Edges()

            scored = []
            for i, edge in enumerate(edges):
                mid = edge.Center()
                dist = (target - cq.Vector(mid.x, mid.y, mid.z)).Length
                scored.append((dist, i, edge))

            scored.sort(key=lambda t: t[0])
            nearest = scored[:count]

            result = []
            for dist, idx, edge in nearest:
                info = _edge_info(idx, edge)
                info["distance_to_point"] = round(dist, 3)
                result.append(info)

            return json.dumps({
                "object": name,
                "query_point": [x, y, z],
                "nearest_edges": result,
            }, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def find_faces_near_point(
        name: str, x: float, y: float, z: float, count: int = 3
    ) -> str:
        """Find the faces closest to a given point. Returns the nearest faces
        sorted by distance, with their index and geometry.

        Args:
            name: Name of the object.
            x: X coordinate of the target point.
            y: Y coordinate of the target point.
            z: Z coordinate of the target point.
            count: Number of nearest faces to return (default 3).
        """
        try:
            shape = require_object(name)
            target = cq.Vector(x, y, z)
            faces = shape.Faces()

            scored = []
            for i, face in enumerate(faces):
                center = face.Center()
                dist = (target - cq.Vector(center.x, center.y, center.z)).Length
                scored.append((dist, i, face))

            scored.sort(key=lambda t: t[0])
            nearest = scored[:count]

            result = []
            for dist, idx, face in nearest:
                info = _face_info(idx, face)
                info["distance_to_point"] = round(dist, 3)
                result.append(info)

            return json.dumps({
                "object": name,
                "query_point": [x, y, z],
                "nearest_faces": result,
            }, indent=2)
        except Exception as e:
            return f"FAIL Error: {e}"
