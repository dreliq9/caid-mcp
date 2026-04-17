"""Geometry query and measurement tools — lets the LLM see what it built.

Returns Pydantic models defined in `caid_mcp.types`. Clients get both
human-readable text (via __str__) and structured fields they can read
directly without parsing JSON out of a string.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Optional

from pydantic import Field
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

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
from OCP.GeomAbs import (
    GeomAbs_Line, GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_BSplineCurve,
    GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere,
    GeomAbs_Torus, GeomAbs_BSplineSurface,
)

from caid_mcp.core import (
    require_object,
    shape_volume, shape_area, shape_center, shape_bounding_box, _unwrap,
)
from caid_mcp.types import (
    BoundingBox, Point3,
    EdgeInfo, FaceInfo,
    EdgeListResult, FaceListResult, DistanceResult,
    InspectResult, MassResult,
    NearestEdgesResult, NearestFacesResult,
)


# ---------------------------------------------------------------------------
# Material density library (g/cm3)
# ---------------------------------------------------------------------------

MATERIAL_DENSITIES = {
    "steel": 7.85, "stainless_steel": 8.00, "aluminum": 2.70, "copper": 8.96,
    "brass": 8.50, "titanium": 4.51, "cast_iron": 7.20, "zinc": 7.13,
    "magnesium": 1.74, "nickel": 8.90, "tungsten": 19.25, "lead": 11.34,
    "gold": 19.32, "silver": 10.49,
    "nylon": 1.14, "abs": 1.05, "pla": 1.24, "petg": 1.27, "delrin": 1.41,
    "ptfe": 2.15, "polycarbonate": 1.20, "acrylic": 1.18, "hdpe": 0.95, "pp": 0.90,
    "wood_oak": 0.75, "wood_pine": 0.50, "wood_plywood": 0.60,
    "carbon_fiber": 1.60, "fiberglass": 1.85, "concrete": 2.40, "rubber": 1.20,
}

Material = Literal[
    "steel", "stainless_steel", "aluminum", "copper", "brass", "titanium",
    "cast_iron", "zinc", "magnesium", "nickel", "tungsten", "lead", "gold", "silver",
    "nylon", "abs", "pla", "petg", "delrin", "ptfe", "polycarbonate", "acrylic",
    "hdpe", "pp",
    "wood_oak", "wood_pine", "wood_plywood",
    "carbon_fiber", "fiberglass", "concrete", "rubber",
]


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


# ---------------------------------------------------------------------------
# OCP traversal helpers
# ---------------------------------------------------------------------------

def _get_edges(shape):
    raw = _unwrap(shape)
    out = []
    exp = TopExp_Explorer(raw, TopAbs_EDGE)
    while exp.More():
        out.append(TopoDS.Edge_s(exp.Current()))
        exp.Next()
    return out


def _get_faces(shape):
    raw = _unwrap(shape)
    out = []
    exp = TopExp_Explorer(raw, TopAbs_FACE)
    while exp.More():
        out.append(TopoDS.Face_s(exp.Current()))
        exp.Next()
    return out


def _get_vertices(shape):
    raw = _unwrap(shape)
    out = []
    exp = TopExp_Explorer(raw, TopAbs_VERTEX)
    while exp.More():
        out.append(TopoDS.Vertex_s(exp.Current()))
        exp.Next()
    return out


def _edge_length(edge) -> float:
    return GCPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(edge))


def _edge_midpoint(edge):
    curve = BRepAdaptor_Curve(edge)
    u_mid = (curve.FirstParameter() + curve.LastParameter()) / 2.0
    pt = curve.Value(u_mid)
    return (pt.X(), pt.Y(), pt.Z())


def _edge_endpoints(edge):
    curve = BRepAdaptor_Curve(edge)
    p1 = curve.Value(curve.FirstParameter())
    p2 = curve.Value(curve.LastParameter())
    return ((p1.X(), p1.Y(), p1.Z()), (p2.X(), p2.Y(), p2.Z()))


def _edge_type(edge) -> str:
    return _CURVE_TYPE_NAMES.get(BRepAdaptor_Curve(edge).GetType(), "OTHER")


def _face_area(face) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def _face_center(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def _face_normal(face):
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
    return _SURFACE_TYPE_NAMES.get(BRepAdaptor_Surface(face).GetType(), "OTHER")


def _face_bbox(face) -> dict:
    bbox = Bnd_Box()
    BRepBndLib.Add_s(face, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return {
        "x": [round(xmin, 3), round(xmax, 3)],
        "y": [round(ymin, 3), round(ymax, 3)],
        "z": [round(zmin, 3), round(zmax, 3)],
    }


def _edge_info_dict(idx: int, edge) -> dict:
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


def _face_info_dict(idx: int, face) -> dict:
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


# Backwards-compatible aliases — other modules may import these names.
_edge_info = _edge_info_dict
_face_info = _face_info_dict


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp: FastMCP) -> None:
    """Register geometry query and measurement tools."""

    @mcp.tool()
    def list_edges(
        name: Annotated[str, Field(description="Object name in the scene")],
    ) -> EdgeListResult:
        """List all edges of an object with index, endpoints, length, and type.

        Each edge gets a stable index you can pass to fillet/chamfer tools.
        """
        shape = require_object(name)
        edges = _get_edges(shape)
        return EdgeListResult(
            object=name,
            count=len(edges),
            edges=[EdgeInfo(**_edge_info_dict(i, e)) for i, e in enumerate(edges)],
        )

    @mcp.tool()
    def list_faces(
        name: Annotated[str, Field(description="Object name in the scene")],
    ) -> FaceListResult:
        """List all faces of an object with index, area, center, normal, and type."""
        shape = require_object(name)
        faces = _get_faces(shape)
        return FaceListResult(
            object=name,
            count=len(faces),
            faces=[FaceInfo(**_face_info_dict(i, f)) for i, f in enumerate(faces)],
        )

    @mcp.tool()
    def measure_distance(
        name_a: Annotated[str, Field(description="First object name")],
        name_b: Annotated[str, Field(description="Second object name")],
    ) -> DistanceResult:
        """Measure the minimum distance between two objects (mm)."""
        a = require_object(name_a)
        b = require_object(name_b)
        calc = BRepExtrema_DistShapeShape(_unwrap(a), _unwrap(b))
        calc.Perform()
        return DistanceResult(
            object_a=name_a, object_b=name_b,
            min_distance_mm=round(calc.Value(), 4),
        )

    @mcp.tool()
    def inspect_object(
        name: Annotated[str, Field(description="Object name in the scene")],
    ) -> InspectResult:
        """Complete description of an object — dimensions, volume, topology, bbox.

        The agent can format this as text via str(result) or read structured
        fields directly. The legacy `format='text'|'json'` parameter is gone:
        FastMCP returns both representations every time.
        """
        shape = require_object(name)
        bb = shape_bounding_box(shape)
        com = shape_center(shape)
        faces = _get_faces(shape)
        edges = _get_edges(shape)
        verts = _get_vertices(shape)

        face_types: dict[str, int] = {}
        for f in faces:
            t = _face_type(f)
            face_types[t] = face_types.get(t, 0) + 1

        return InspectResult(
            name=name,
            volume_mm3=round(shape_volume(shape), 3),
            surface_area_mm2=round(shape_area(shape), 3),
            center_of_mass=Point3(x=round(com[0], 3), y=round(com[1], 3), z=round(com[2], 3)),
            bounding_box=BoundingBox(**{k: round(v, 3) for k, v in bb.items()}),
            num_faces=len(faces),
            num_edges=len(edges),
            num_vertices=len(verts),
            face_types=face_types,
        )

    @mcp.tool()
    def mass_properties(
        name: Annotated[str, Field(description="Object name in the scene")],
        material: Annotated[
            Optional[Material],
            Field(description="Material name from the built-in library (28 options)"),
        ] = None,
        density: Annotated[
            Optional[float],
            Field(default=None, gt=0, description="Override material — explicit density in g/cm^3"),
        ] = None,
    ) -> MassResult:
        """Calculate mass, weight, volume, surface area, CoM, and bbox.

        Provide EITHER `material` OR `density`. If both, `density` wins.
        """
        if density is None and material is None:
            raise ToolError(
                "Provide either material= or density= (e.g. material='aluminum')"
            )

        rho = density if density is not None else MATERIAL_DENSITIES[material]
        mat_name = "custom" if density is not None else material

        shape = require_object(name)
        vol_mm3 = shape_volume(shape)
        vol_cm3 = vol_mm3 / 1000.0
        mass_g = vol_cm3 * rho
        mass_kg = mass_g / 1000.0
        com = shape_center(shape)
        bb = shape_bounding_box(shape)

        return MassResult(
            name=name,
            material=mat_name,
            density_g_per_cm3=rho,
            volume_mm3=round(vol_mm3, 3),
            volume_cm3=round(vol_cm3, 4),
            surface_area_mm2=round(shape_area(shape), 3),
            mass_grams=round(mass_g, 3),
            mass_kg=round(mass_kg, 6),
            weight_newtons=round(mass_kg * 9.81, 4),
            center_of_mass=Point3(x=round(com[0], 3), y=round(com[1], 3), z=round(com[2], 3)),
            bounding_box=BoundingBox(**{k: round(v, 3) for k, v in bb.items()}),
        )

    @mcp.tool()
    def find_edges_near_point(
        name: Annotated[str, Field(description="Object name in the scene")],
        x: Annotated[float, Field(description="Target X coordinate (mm)")],
        y: Annotated[float, Field(description="Target Y coordinate (mm)")],
        z: Annotated[float, Field(description="Target Z coordinate (mm)")],
        count: Annotated[int, Field(ge=1, le=50, description="Number of nearest edges to return")] = 3,
    ) -> NearestEdgesResult:
        """Find the `count` edges closest to the given point, sorted by distance.

        Use this when you know roughly where on the object you want to
        fillet/chamfer but not the edge index.
        """
        shape = require_object(name)
        edges = _get_edges(shape)

        scored = []
        for i, e in enumerate(edges):
            mx, my, mz = _edge_midpoint(e)
            dist = math.sqrt((x - mx) ** 2 + (y - my) ** 2 + (z - mz) ** 2)
            scored.append((dist, i, e))
        scored.sort(key=lambda t: t[0])

        out = []
        for dist, idx, e in scored[:count]:
            info = _edge_info_dict(idx, e)
            info["distance_to_point"] = round(dist, 3)
            out.append(EdgeInfo(**info))

        return NearestEdgesResult(object=name, query_point=[x, y, z], nearest_edges=out)

    @mcp.tool()
    def find_faces_near_point(
        name: Annotated[str, Field(description="Object name in the scene")],
        x: Annotated[float, Field(description="Target X coordinate (mm)")],
        y: Annotated[float, Field(description="Target Y coordinate (mm)")],
        z: Annotated[float, Field(description="Target Z coordinate (mm)")],
        count: Annotated[int, Field(ge=1, le=50, description="Number of nearest faces to return")] = 3,
    ) -> NearestFacesResult:
        """Find the `count` faces closest to the given point, sorted by distance."""
        shape = require_object(name)
        faces = _get_faces(shape)

        scored = []
        for i, f in enumerate(faces):
            cx, cy, cz = _face_center(f)
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2)
            scored.append((dist, i, f))
        scored.sort(key=lambda t: t[0])

        out = []
        for dist, idx, f in scored[:count]:
            info = _face_info_dict(idx, f)
            info["distance_to_point"] = round(dist, 3)
            out.append(FaceInfo(**info))

        return NearestFacesResult(object=name, query_point=[x, y, z], nearest_faces=out)
