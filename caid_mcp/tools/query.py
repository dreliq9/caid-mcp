"""Geometry query and measurement tools — lets the LLM see what it built."""

import json
import math
from typing import Optional
from mcp.server.fastmcp import FastMCP

from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_BSplineCurve, GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BSplineSurface

from caid_mcp.core import (
    scene, require_object,
    shape_volume, shape_area, shape_center, shape_bounding_box, _unwrap,
)


# ---------------------------------------------------------------------------
# Material density library (g/cm3)
# ---------------------------------------------------------------------------

MATERIAL_DENSITIES = {
    # Metals
    "steel": 7.85,
    "stainless_steel": 8.00,
    "aluminum": 2.70,
    "copper": 8.96,
    "brass": 8.50,
    "titanium": 4.51,
    "cast_iron": 7.20,
    "zinc": 7.13,
    "magnesium": 1.74,
    "nickel": 8.90,
    "tungsten": 19.25,
    "lead": 11.34,
    "gold": 19.32,
    "silver": 10.49,
    # Plastics
    "nylon": 1.14,
    "abs": 1.05,
    "pla": 1.24,
    "petg": 1.27,
    "delrin": 1.41,
    "ptfe": 2.15,
    "polycarbonate": 1.20,
    "acrylic": 1.18,
    "hdpe": 0.95,
    "pp": 0.90,
    # Wood (approximate)
    "wood_oak": 0.75,
    "wood_pine": 0.50,
    "wood_plywood": 0.60,
    # Other
    "carbon_fiber": 1.60,
    "fiberglass": 1.85,
    "concrete": 2.40,
    "rubber": 1.20,
}


# ---------------------------------------------------------------------------
# Curve/surface type name mapping
# ---------------------------------------------------------------------------

_CURVE_TYPE_NAMES = {
    GeomAbs_Line: "LINE",
    GeomAbs_Circle: "CIRCLE",
    GeomAbs_Ellipse: "ELLIPSE",
    GeomAbs_BSplineCurve: "BSPLINE",
}

_SURFACE_TYPE_NAMES = {
    GeomAbs_Plane: "PLANE",
    GeomAbs_Cylinder: "CYLINDER",
    GeomAbs_Cone: "CONE",
    GeomAbs_Sphere: "SPHERE",
    GeomAbs_Torus: "TORUS",
    GeomAbs_BSplineSurface: "BSPLINE",
}


def _get_edges(shape):
    """Collect all edges from a shape using TopExp_Explorer."""
    raw = _unwrap(shape)
    edges = []
    exp = TopExp_Explorer(raw, TopAbs_EDGE)
    while exp.More():
        edges.append(TopoDS.Edge_s(exp.Current()))
        exp.Next()
    return edges


def _get_faces(shape):
    """Collect all faces from a shape using TopExp_Explorer."""
    raw = _unwrap(shape)
    faces = []
    exp = TopExp_Explorer(raw, TopAbs_FACE)
    while exp.More():
        faces.append(TopoDS.Face_s(exp.Current()))
        exp.Next()
    return faces


def _get_vertices(shape):
    """Collect all vertices from a shape using TopExp_Explorer."""
    raw = _unwrap(shape)
    verts = []
    exp = TopExp_Explorer(raw, TopAbs_VERTEX)
    while exp.More():
        verts.append(TopoDS.Vertex_s(exp.Current()))
        exp.Next()
    return verts


def _edge_length(edge) -> float:
    """Get length of an edge."""
    curve = BRepAdaptor_Curve(edge)
    return GCPnts_AbscissaPoint.Length_s(curve)


def _edge_midpoint(edge):
    """Get midpoint of an edge as (x, y, z)."""
    curve = BRepAdaptor_Curve(edge)
    u_min = curve.FirstParameter()
    u_max = curve.LastParameter()
    u_mid = (u_min + u_max) / 2.0
    pt = curve.Value(u_mid)
    return (pt.X(), pt.Y(), pt.Z())


def _edge_endpoints(edge):
    """Get start and end points of an edge as ((x,y,z), (x,y,z))."""
    curve = BRepAdaptor_Curve(edge)
    p1 = curve.Value(curve.FirstParameter())
    p2 = curve.Value(curve.LastParameter())
    return (
        (p1.X(), p1.Y(), p1.Z()),
        (p2.X(), p2.Y(), p2.Z()),
    )


def _edge_type(edge) -> str:
    """Get the geometric type of an edge."""
    curve = BRepAdaptor_Curve(edge)
    return _CURVE_TYPE_NAMES.get(curve.GetType(), "OTHER")


def _face_area(face) -> float:
    """Get area of a face."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def _face_center(face):
    """Get center of mass of a face as (x, y, z)."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def _face_normal(face):
    """Get normal vector at center of face as (x, y, z) or None."""
    try:
        surf = BRepAdaptor_Surface(face)
        u_mid = (surf.FirstUParameter() + surf.LastUParameter()) / 2.0
        v_mid = (surf.FirstVParameter() + surf.LastVParameter()) / 2.0
        slprops = BRepLProp_SLProps(surf, u_mid, v_mid, 1, 1e-6)
        if slprops.IsNormalDefined():
            n = slprops.Normal()
            return (n.X(), n.Y(), n.Z())
    except Exception:
        pass
    return None


def _face_type(face) -> str:
    """Get the geometric type of a face."""
    surf = BRepAdaptor_Surface(face)
    return _SURFACE_TYPE_NAMES.get(surf.GetType(), "OTHER")


def _face_bbox(face) -> dict:
    """Get bounding box of a face."""
    bbox = Bnd_Box()
    BRepBndLib.Add_s(face, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return {
        "x": [round(xmin, 3), round(xmax, 3)],
        "y": [round(ymin, 3), round(ymax, 3)],
        "z": [round(zmin, 3), round(zmax, 3)],
    }


def _edge_info(idx: int, edge) -> dict:
    """Extract useful info from a single edge."""
    start, end = _edge_endpoints(edge)
    mid = _edge_midpoint(edge)
    return {
        "index": idx,
        "length_mm": round(_edge_length(edge), 3),
        "start": [round(v, 3) for v in start],
        "end": [round(v, 3) for v in end],
        "midpoint": [round(v, 3) for v in mid],
        "type": _edge_type(edge),
    }


def _face_info(idx: int, face) -> dict:
    """Extract useful info from a single face."""
    center = _face_center(face)
    normal = _face_normal(face)
    normal_vec = [round(v, 3) for v in normal] if normal else None
    face_edges = []
    exp = TopExp_Explorer(face, TopAbs_EDGE)
    while exp.More():
        face_edges.append(exp.Current())
        exp.Next()
    return {
        "index": idx,
        "area_mm2": round(_face_area(face), 3),
        "center": [round(v, 3) for v in center],
        "normal": normal_vec,
        "type": _face_type(face),
        "bounds": _face_bbox(face),
        "num_edges": len(face_edges),
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
            face_selector: Optional — not currently supported (CQ selectors removed).
                          If provided, it will be ignored and all edges returned.
        """
        try:
            shape = require_object(name)
            edges = _get_edges(shape)

            if not edges:
                return f"No edges found on '{name}'"

            result = [_edge_info(i, e) for i, e in enumerate(edges)]
            return json.dumps({
                "object": name,
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
            faces = _get_faces(shape)
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
            dist_calc = BRepExtrema_DistShapeShape(_unwrap(shape_a), _unwrap(shape_b))
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
    def inspect_object(name: str, format: str = "text") -> str:
        """Get a complete description of an object — dimensions, volume, topology,
        validity, and bounding box. The ONE tool for "tell me about this object."

        Args:
            name: Name of the object.
            format: Output format — "text" for natural language (default, best for
                   reasoning), or "json" for structured data (best for calculations).
        """
        try:
            shape = require_object(name)
            bb = shape_bounding_box(shape)
            com = shape_center(shape)
            vol = shape_volume(shape)
            area = shape_area(shape)
            faces = _get_faces(shape)
            edges = _get_edges(shape)
            verts = _get_vertices(shape)

            if format.lower() == "json":
                info = {
                    "name": name,
                    "volume_mm3": round(vol, 3),
                    "surface_area_mm2": round(area, 3),
                    "center_of_mass": [round(com[0], 3), round(com[1], 3), round(com[2], 3)],
                    "bounding_box": {
                        "min": [round(bb["xmin"], 3), round(bb["ymin"], 3), round(bb["zmin"], 3)],
                        "max": [round(bb["xmax"], 3), round(bb["ymax"], 3), round(bb["zmax"], 3)],
                        "size": [round(bb["xlen"], 3), round(bb["ylen"], 3), round(bb["zlen"], 3)],
                    },
                    "num_faces": len(faces),
                    "num_edges": len(edges),
                    "num_vertices": len(verts),
                }
                return json.dumps(info, indent=2)

            # Text format — natural language
            face_types: dict[str, int] = {}
            for f in faces:
                ft = _face_type(f)
                face_types[ft] = face_types.get(ft, 0) + 1
            type_summary = ", ".join(
                f"{count} {ftype.lower()}" for ftype, count in
                sorted(face_types.items(), key=lambda x: -x[1])
            )

            lines = [
                f"'{name}' is a solid occupying {bb['xlen']:.2f} x {bb['ylen']:.2f} x {bb['zlen']:.2f} mm.",
                f"It has {len(faces)} faces ({type_summary}), {len(edges)} edges, and {len(verts)} vertices.",
                f"Volume: {vol:.2f} mm\u00b3. Surface area: {area:.2f} mm\u00b2.",
                f"Center of mass: ({com[0]:.2f}, {com[1]:.2f}, {com[2]:.2f}).",
                f"Bounding box: ({bb['xmin']:.2f}, {bb['ymin']:.2f}, {bb['zmin']:.2f}) to ({bb['xmax']:.2f}, {bb['ymax']:.2f}, {bb['zmax']:.2f}).",
            ]
            dims = sorted([bb["xlen"], bb["ylen"], bb["zlen"]], reverse=True)
            if dims[0] < 0.01:
                lines.append("The object is essentially a point or degenerate shape.")
            elif max(dims) / max(dims[2], 0.001) > 20:
                lines.append("The object is very thin or elongated.")

            return "\n".join(lines)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def mass_properties(
        name: str, material: Optional[str] = None,
        density: Optional[float] = None,
    ) -> str:
        """Calculate mass properties for an object given a material or density.

        Returns mass, weight, volume, surface area, center of mass, and
        bounding box. Essential for mechanical design weight estimates.

        Args:
            name: Name of the object.
            material: Material name from built-in library (28 materials).
                     Metals: steel, stainless_steel, aluminum, copper, brass,
                     titanium, cast_iron, zinc, magnesium, nickel, tungsten,
                     lead, gold, silver.
                     Plastics: nylon, abs, pla, petg, delrin, ptfe,
                     polycarbonate, acrylic, hdpe, pp.
                     Other: wood_oak, wood_pine, wood_plywood, carbon_fiber,
                     fiberglass, concrete, rubber.
                     Ignored if density is provided.
            density: Material density in g/cm3 (overrides material lookup).
                    Example: 7.85 for mild steel.
        """
        try:
            shape = require_object(name)
            vol_mm3 = shape_volume(shape)
            vol_cm3 = vol_mm3 / 1000.0  # 1 cm3 = 1000 mm3
            area_mm2 = shape_area(shape)
            com = shape_center(shape)
            bb = shape_bounding_box(shape)

            # Determine density
            rho = density
            mat_name = None
            if rho is None and material:
                mat_key = material.lower().strip()
                rho = MATERIAL_DENSITIES.get(mat_key)
                if rho is None:
                    return (
                        f"FAIL Unknown material '{material}'. Available: "
                        + ", ".join(sorted(MATERIAL_DENSITIES.keys()))
                    )
                mat_name = mat_key
            elif rho is None:
                return (
                    "FAIL Provide either a material name or a density value. "
                    "Example: material='aluminum' or density=2.70"
                )

            mass_g = vol_cm3 * rho
            mass_kg = mass_g / 1000.0
            weight_n = mass_kg * 9.81

            info = {
                "name": name,
                "material": mat_name or f"custom (rho={rho} g/cm3)",
                "density_g_per_cm3": rho,
                "volume_mm3": round(vol_mm3, 3),
                "volume_cm3": round(vol_cm3, 4),
                "surface_area_mm2": round(area_mm2, 3),
                "mass_grams": round(mass_g, 3),
                "mass_kg": round(mass_kg, 6),
                "weight_newtons": round(weight_n, 4),
                "center_of_mass": [round(com[0], 3), round(com[1], 3), round(com[2], 3)],
                "bounding_box": {
                    "min": [round(bb["xmin"], 3), round(bb["ymin"], 3), round(bb["zmin"], 3)],
                    "max": [round(bb["xmax"], 3), round(bb["ymax"], 3), round(bb["zmax"], 3)],
                    "size": [round(bb["xlen"], 3), round(bb["ylen"], 3), round(bb["zlen"], 3)],
                },
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
            edges = _get_edges(shape)

            scored = []
            for i, edge in enumerate(edges):
                mx, my, mz = _edge_midpoint(edge)
                dist = math.sqrt((x - mx) ** 2 + (y - my) ** 2 + (z - mz) ** 2)
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
            faces = _get_faces(shape)

            scored = []
            for i, face in enumerate(faces):
                cx, cy, cz = _face_center(face)
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2)
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
