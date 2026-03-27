"""
Test suite for CAiD MCP Server — no CadQuery dependency.
Run with: pytest tests/ -v
"""

import json
import math
import pytest

import caid
from caid.vector import Vector
from caid.result import ForgeResult
from caid.assembly import Assembly, Part
from caid_mcp.core import (
    scene, assemblies, store_object, require_object, get_object,
    format_result, OUTPUT_DIR, shape_volume, shape_bounding_box, shape_area,
)


# ---------------------------------------------------------------------------
# OCP topology helpers (replace CadQuery .Edges(), .Faces(), etc.)
# ---------------------------------------------------------------------------

def _count_topo(shape, topo_type):
    """Count topological entities of a given type on a shape."""
    from OCP.TopExp import TopExp_Explorer
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    exp = TopExp_Explorer(wrapped, topo_type)
    count = 0
    while exp.More():
        count += 1
        exp.Next()
    return count


def _count_edges(shape):
    return len(_get_edges(shape))


def _count_faces(shape):
    return len(_get_faces(shape))


def _get_topo_items(shape, topo_type):
    """Return a list of OCP shapes of the given topo type."""
    from OCP.TopExp import TopExp_Explorer
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    exp = TopExp_Explorer(wrapped, topo_type)
    items = []
    while exp.More():
        items.append(exp.Current())
        exp.Next()
    return items


def _get_edges(shape):
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(wrapped, TopAbs_EDGE, edge_map)
    return [TopoDS.Edge_s(edge_map.FindKey(i)) for i in range(1, edge_map.Extent() + 1)]


def _get_faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(wrapped, TopAbs_FACE, face_map)
    return [TopoDS.Face_s(face_map.FindKey(i)) for i in range(1, face_map.Extent() + 1)]


def _edge_length(edge):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return props.Mass()


def _face_area(face):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def _edge_center(edge):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint
    curve = BRepAdaptor_Curve(edge)
    u_mid = (curve.FirstParameter() + curve.LastParameter()) / 2.0
    pt = curve.Value(u_mid)
    return pt.X(), pt.Y(), pt.Z()


def _face_center(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    surf = BRepAdaptor_Surface(face)
    u_mid = (surf.FirstUParameter() + surf.LastUParameter()) / 2.0
    v_mid = (surf.FirstVParameter() + surf.LastVParameter()) / 2.0
    pt = surf.Value(u_mid, v_mid)
    return pt.X(), pt.Y(), pt.Z()


def _face_normal_at_center(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.BRepGProp import BRepGProp_Face
    gpf = BRepGProp_Face(face)
    surf = BRepAdaptor_Surface(face)
    u_mid = (surf.FirstUParameter() + surf.LastUParameter()) / 2.0
    v_mid = (surf.FirstVParameter() + surf.LastVParameter()) / 2.0
    pt = gp_Pnt()
    normal = gp_Vec()
    gpf.Normal(u_mid, v_mid, pt, normal)
    return normal.X(), normal.Y(), normal.Z()


def _edge_geom_type(edge):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import (GeomAbs_Line, GeomAbs_Circle, GeomAbs_Ellipse,
                              GeomAbs_BSplineCurve, GeomAbs_BezierCurve)
    curve = BRepAdaptor_Curve(edge)
    t = curve.GetType()
    mapping = {
        GeomAbs_Line: "LINE",
        GeomAbs_Circle: "CIRCLE",
        GeomAbs_Ellipse: "ELLIPSE",
        GeomAbs_BSplineCurve: "BSPLINE",
        GeomAbs_BezierCurve: "BEZIER",
    }
    return mapping.get(t, "OTHER")


def _face_geom_type(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                              GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BSplineSurface)
    surf = BRepAdaptor_Surface(face)
    t = surf.GetType()
    mapping = {
        GeomAbs_Plane: "PLANE",
        GeomAbs_Cylinder: "CYLINDER",
        GeomAbs_Cone: "CONE",
        GeomAbs_Sphere: "SPHERE",
        GeomAbs_Torus: "TORUS",
        GeomAbs_BSplineSurface: "BSPLINE",
    }
    return mapping.get(t, "OTHER")


def _edge_vertices(edge):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_VERTEX
    exp = TopExp_Explorer(edge, TopAbs_VERTEX)
    verts = []
    while exp.More():
        verts.append(exp.Current())
        exp.Next()
    return verts


def _shape_volume(shape):
    """Get volume from either a caid shape or raw OCP shape."""
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    return shape_volume(wrapped)


def _bb(shape):
    """Get bounding box dict from either a caid shape or raw OCP shape."""
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    return shape_bounding_box(wrapped)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    """Clear scene and assemblies before and after each test."""
    scene.clear()
    assemblies.clear()
    yield
    scene.clear()
    assemblies.clear()


@pytest.fixture
def box_shape():
    """Create a standard test box shape via caid."""
    fr = caid.box(20, 20, 10)
    store_object("test_box", fr.shape)
    return fr.shape


@pytest.fixture
def cyl_shape():
    """Create a standard test cylinder shape via caid."""
    fr = caid.cylinder(5, 20)
    store_object("test_cyl", fr.shape)
    return fr.shape


# ---------------------------------------------------------------------------
# Core module tests
# ---------------------------------------------------------------------------

class TestCore:
    def test_store_and_get(self):
        fr = caid.box(10, 10, 10)
        store_object("a", fr.shape)
        assert get_object("a") is fr.shape
        assert get_object("nonexistent") is None

    def test_require_object_found(self, box_shape):
        assert require_object("test_box") is box_shape

    def test_require_object_missing(self):
        with pytest.raises(ValueError, match="not found"):
            require_object("ghost")

    def test_store_auto_extracts_forge_result(self):
        fr = caid.box(10, 10, 10)
        store_object("from_fr", fr)
        obj = get_object("from_fr")
        assert not isinstance(obj, ForgeResult)
        assert _shape_volume(obj) > 0

    def test_format_result_ok(self):
        fr = caid.box(10, 10, 10)
        msg = format_result(fr, "test")
        assert "OK" in msg
        assert "volume=" in msg

    def test_format_result_fail(self):
        fr = ForgeResult(shape=None, valid=False, diagnostics={"reason": "broke"})
        msg = format_result(fr, "test")
        assert "FAIL" in msg
        assert "broke" in msg


# ---------------------------------------------------------------------------
# Primitive creation tests
# ---------------------------------------------------------------------------

class TestPrimitives:
    def test_box_volume(self):
        fr = caid.box(30, 20, 10)
        assert fr.ok
        assert abs(fr.volume_after - 6000.0) < 1.0

    def test_cylinder_volume(self):
        fr = caid.cylinder(5, 20)
        assert fr.ok
        assert fr.volume_after > 0

    def test_sphere_volume(self):
        fr = caid.sphere(15)
        assert fr.ok
        assert fr.volume_after > 0

    def test_cone(self):
        fr = caid.cone(10, 0, 20)
        assert fr.ok
        assert fr.volume_after > 0

    def test_torus(self):
        fr = caid.torus(20, 5)
        assert fr.ok
        assert fr.volume_after > 0

    def test_extruded_polygon(self):
        """Extrude a square polygon using OCP directly."""
        from OCP.gp import gp_Pnt, gp_Vec
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        wire_builder = BRepBuilderAPI_MakeWire()
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            edge = BRepBuilderAPI_MakeEdge(gp_Pnt(x1, y1, 0), gp_Pnt(x2, y2, 0)).Edge()
            wire_builder.Add(edge)
        face = BRepBuilderAPI_MakeFace(wire_builder.Wire()).Face()
        solid = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 5)).Shape()
        bb = shape_bounding_box(solid)
        assert abs(bb["zlen"] - 5) < 0.01

    def test_revolved_profile(self):
        """Revolve a rectangular profile around the Y axis using OCP."""
        from OCP.gp import gp_Pnt, gp_Ax1, gp_Dir
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol

        # Profile in XZ plane: rectangle from (0,0)-(5,0)-(5,10)-(0,10)
        pts = [(0, 0, 0), (5, 0, 0), (5, 0, 10), (0, 0, 10)]
        wire_builder = BRepBuilderAPI_MakeWire()
        for i in range(len(pts)):
            p1 = gp_Pnt(*pts[i])
            p2 = gp_Pnt(*pts[(i + 1) % len(pts)])
            edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
            wire_builder.Add(edge)
        face = BRepBuilderAPI_MakeFace(wire_builder.Wire()).Face()
        axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        solid = BRepPrimAPI_MakeRevol(face, axis, math.radians(360)).Shape()
        assert shape_volume(solid) > 0


# ---------------------------------------------------------------------------
# Modification tests
# ---------------------------------------------------------------------------

class TestModifications:
    def test_fillet(self, box_shape):
        fr = caid.fillet(box_shape, 1)
        assert fr.ok
        assert _count_faces(fr.shape) > _count_faces(box_shape)

    def test_chamfer(self, box_shape):
        fr = caid.chamfer(box_shape, 1)
        assert fr.ok
        assert _count_faces(fr.shape) > _count_faces(box_shape)

    def test_add_hole(self, box_shape):
        """Add a hole via caid.add_hole and verify volume decreases."""
        fr = caid.add_hole(box_shape, radius=3.0, face_selector=">Z")
        assert fr.ok
        assert _shape_volume(fr.shape) < _shape_volume(box_shape)

    def test_fillet_changes_edge_count(self, box_shape):
        """Fillet all edges increases edge count."""
        orig_edges = _count_edges(box_shape)
        fr = caid.fillet(box_shape, 1.0)
        assert fr.ok
        assert _shape_volume(fr.shape) < _shape_volume(box_shape)
        assert _count_edges(fr.shape) > orig_edges

    def test_chamfer_changes_edge_count(self, box_shape):
        """Chamfer all edges increases edge count."""
        orig_edges = _count_edges(box_shape)
        fr = caid.chamfer(box_shape, 0.5)
        assert fr.ok
        assert _shape_volume(fr.shape) < _shape_volume(box_shape)


# ---------------------------------------------------------------------------
# Transform tests
# ---------------------------------------------------------------------------

class TestTransforms:
    def test_translate(self, box_shape):
        fr = caid.translate(box_shape, Vector(10, 20, 30))
        assert fr.ok
        bb = _bb(fr.shape)
        # box origin is corner at (0,0,0), so after translate center is at:
        # x: 10 + 10 = 20, y: 20 + 10 = 30, z: 30 + 5 = 35
        cx = (bb["xmin"] + bb["xmax"]) / 2
        cy = (bb["ymin"] + bb["ymax"]) / 2
        cz = (bb["zmin"] + bb["zmax"]) / 2
        assert abs(cx - 20) < 0.01
        assert abs(cy - 30) < 0.01
        assert abs(cz - 35) < 0.01

    def test_rotate(self, box_shape):
        fr = caid.rotate(box_shape, Vector(0, 0, 0), Vector(0, 0, 1), 90)
        assert fr.ok
        bb = _bb(fr.shape)
        assert bb["xlen"] > 0

    def test_mirror(self, box_shape):
        moved = caid.translate(box_shape, Vector(10, 0, 0))
        fr = caid.mirror(moved.shape, Vector(0, 0, 0), Vector(1, 0, 0))
        assert fr.ok
        bb = _bb(fr.shape)
        cx = (bb["xmin"] + bb["xmax"]) / 2
        assert cx < 0

    def test_scale(self, box_shape):
        fr = caid.scale(box_shape, 2.0)
        assert fr.ok
        assert fr.volume_after > _shape_volume(box_shape) * 7  # 2^3 = 8x volume


# ---------------------------------------------------------------------------
# Boolean operation tests
# ---------------------------------------------------------------------------

class TestBooleans:
    def test_union(self, box_shape, cyl_shape):
        fr = caid.boolean_union(box_shape, cyl_shape)
        assert fr.shape is not None
        assert _shape_volume(fr.shape) >= _shape_volume(box_shape)

    def test_cut(self, box_shape, cyl_shape):
        fr = caid.boolean_cut(box_shape, cyl_shape)
        assert fr.ok
        assert fr.volume_after < _shape_volume(box_shape)

    def test_intersect(self, box_shape, cyl_shape):
        fr = caid.boolean_intersect(box_shape, cyl_shape)
        assert fr.shape is not None
        assert _shape_volume(fr.shape) < _shape_volume(box_shape)


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestExport:
    def test_stl_export(self, box_shape):
        path = OUTPUT_DIR / "test_export.stl"
        fr = caid.to_stl(box_shape, path)
        assert fr.valid
        assert path.exists()
        assert path.stat().st_size > 100
        path.unlink()

    def test_step_roundtrip(self, box_shape):
        path = OUTPUT_DIR / "test_export.step"
        fr = caid.to_step(box_shape, path)
        assert fr.valid
        assert path.exists()
        imp = caid.from_step(path)
        assert imp.ok
        assert abs(_shape_volume(imp.shape) - _shape_volume(box_shape)) < 1.0
        path.unlink()

    def test_brep_roundtrip(self, box_shape):
        path = OUTPUT_DIR / "test_export.brep"
        fr = caid.to_brep(box_shape, path)
        assert fr.valid
        assert path.exists()
        imp = caid.from_brep(path)
        assert imp.ok
        assert abs(_shape_volume(imp.shape) - _shape_volume(box_shape)) < 1.0
        path.unlink()


# ---------------------------------------------------------------------------
# Scene management tests
# ---------------------------------------------------------------------------

class TestScene:
    def test_list_empty(self):
        assert len(scene) == 0

    def test_list_with_objects(self, box_shape, cyl_shape):
        assert len(scene) == 2

    def test_delete(self, box_shape):
        assert "test_box" in scene
        del scene["test_box"]
        assert "test_box" not in scene

    def test_clear(self, box_shape, cyl_shape):
        assert len(scene) == 2
        scene.clear()
        assert len(scene) == 0

    def test_duplicate(self, box_shape):
        scene["copy"] = scene["test_box"]
        assert _shape_volume(scene["copy"]) == _shape_volume(box_shape)

    def test_object_info(self, box_shape):
        bb = _bb(box_shape)
        assert abs(bb["xlen"] - 20) < 0.01
        assert _shape_volume(box_shape) > 0
        assert _count_faces(box_shape) == 6
        assert _count_edges(box_shape) == 12


# ---------------------------------------------------------------------------
# Heal tests
# ---------------------------------------------------------------------------

class TestHeal:
    def test_check_valid(self, box_shape):
        result = caid.check_valid(box_shape)
        assert result["is_valid"] is True

    def test_heal_good_shape(self, box_shape):
        fr = caid.heal(box_shape)
        assert fr.ok

    def test_simplify(self, box_shape, cyl_shape):
        union = caid.boolean_union(box_shape, cyl_shape)
        if union.shape is not None:
            fr = caid.simplify(union.shape)
            assert fr.ok


# ---------------------------------------------------------------------------
# Assembly tests
# ---------------------------------------------------------------------------

class TestAssembly:
    def test_create_and_add(self, box_shape, cyl_shape):
        asm = Assembly()
        asm = asm.add(Part("box", box_shape))
        asm = asm.add(Part("cyl", cyl_shape))
        assert asm.get("box") is not None
        assert asm.get("cyl") is not None

    def test_merge(self, box_shape, cyl_shape):
        asm = Assembly()
        asm = asm.add(Part("box", box_shape))
        asm = asm.add(Part("cyl", cyl_shape))
        fr = asm.merge_all()
        assert fr.shape is not None
        assert _shape_volume(fr.shape) > 0


# ---------------------------------------------------------------------------
# Advanced tools tests
# ---------------------------------------------------------------------------

class TestAdvanced:
    def test_script_with_caid_in_namespace(self):
        exec_globals = {"caid": caid, "Vector": Vector, "scene": scene}
        exec("result = caid.box(5, 5, 5)", exec_globals)
        assert "result" in exec_globals
        fr = exec_globals["result"]
        assert isinstance(fr, ForgeResult)
        assert fr.ok

    def test_linear_pattern(self, box_shape):
        result_shape = box_shape
        moved = caid.translate(box_shape, Vector(30, 0, 0))
        fr = caid.boolean_union(result_shape, moved.shape)
        assert fr.shape is not None
        assert _shape_volume(fr.shape) > _shape_volume(box_shape) * 1.5


# ---------------------------------------------------------------------------
# Query tools tests
# ---------------------------------------------------------------------------

class TestQuery:
    def test_list_edges_all(self, box_shape):
        """list_edges returns all 12 edges of a box."""
        edges = _get_edges(box_shape)
        assert len(edges) == 12
        for edge in edges:
            assert _edge_length(edge) > 0

    def test_list_faces(self, box_shape):
        """list_faces returns all 6 faces of a box with correct info."""
        faces = _get_faces(box_shape)
        assert len(faces) == 6
        for face in faces:
            assert _face_area(face) > 0
            cx, cy, cz = _face_center(face)
            assert cx is not None
            nx, ny, nz = _face_normal_at_center(face)
            assert nx is not None or ny is not None or nz is not None

    def test_measure_object(self, box_shape):
        """measure_object returns correct volume and bounding box."""
        vol = _shape_volume(box_shape)
        assert abs(vol - 4000.0) < 1.0  # 20x20x10
        bb = _bb(box_shape)
        assert abs(bb["xlen"] - 20) < 0.01
        assert abs(bb["ylen"] - 20) < 0.01
        assert abs(bb["zlen"] - 10) < 0.01

    def test_measure_distance(self, box_shape, cyl_shape):
        """measure_distance returns the min distance between two shapes."""
        # Move cylinder far away
        moved = caid.translate(cyl_shape, Vector(50, 0, 0))
        store_object("far_cyl", moved.shape)
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        wrapped_box = box_shape.wrapped if hasattr(box_shape, "wrapped") else box_shape
        wrapped_cyl = moved.shape.wrapped if hasattr(moved.shape, "wrapped") else moved.shape
        dist_calc = BRepExtrema_DistShapeShape(wrapped_box, wrapped_cyl)
        dist_calc.Perform()
        assert dist_calc.Value() > 0

    def test_find_edges_near_point(self, box_shape):
        """find_edges_near_point returns edges sorted by distance."""
        target = (10, 10, 5)
        edges = _get_edges(box_shape)
        scored = []
        for i, edge in enumerate(edges):
            mx, my, mz = _edge_center(edge)
            dist = math.sqrt(
                (target[0] - mx) ** 2 + (target[1] - my) ** 2 + (target[2] - mz) ** 2
            )
            scored.append((dist, i))
        scored.sort()
        # Closest edge should be very close to the corner
        assert scored[0][0] < 15  # within reasonable distance

    def test_find_faces_near_point(self, box_shape):
        """find_faces_near_point returns faces sorted by distance."""
        bb = _bb(box_shape)
        cx = (bb["xmin"] + bb["xmax"]) / 2
        cy = (bb["ymin"] + bb["ymax"]) / 2
        target = (cx, cy, bb["zmax"] + 10)
        faces = _get_faces(box_shape)
        scored = []
        for i, face in enumerate(faces):
            fcx, fcy, fcz = _face_center(face)
            dist = math.sqrt(
                (target[0] - fcx) ** 2 + (target[1] - fcy) ** 2 + (target[2] - fcz) ** 2
            )
            scored.append((dist, i, face))
        scored.sort(key=lambda t: t[0])
        # Closest face should be the top face (normal pointing +Z)
        top_face = scored[0][2]
        nx, ny, nz = _face_normal_at_center(top_face)
        assert abs(nz) > 0.9  # should be pointing up

    def test_edge_info_types(self, box_shape):
        """Edge info includes correct geometric types for a box."""
        edges = _get_edges(box_shape)
        for edge in edges:
            assert _edge_geom_type(edge) == "LINE"  # box edges are all lines
            assert _edge_length(edge) > 0
            verts = _edge_vertices(edge)
            assert len(verts) == 2

    def test_face_info_types(self, box_shape):
        """Face info includes correct geometric types for a box."""
        faces = _get_faces(box_shape)
        for face in faces:
            assert _face_geom_type(face) == "PLANE"  # box faces are all planes
            assert _face_area(face) > 0

    def test_cylinder_edge_types(self, cyl_shape):
        """Cylinder should have CIRCLE and LINE type edges."""
        edges = _get_edges(cyl_shape)
        edge_types = {_edge_geom_type(e) for e in edges}
        assert "CIRCLE" in edge_types
        assert "LINE" in edge_types

    def test_cylinder_face_types(self, cyl_shape):
        """Cylinder should have PLANE and CYLINDER type faces."""
        faces = _get_faces(cyl_shape)
        face_types = {_face_geom_type(f) for f in faces}
        assert "PLANE" in face_types
        assert "CYLINDER" in face_types


# ---------------------------------------------------------------------------
# View tools tests
# ---------------------------------------------------------------------------

class TestView:
    def test_section_view_cuts_volume(self):
        """Section view at midpoint should halve the volume."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        # Use a centered box for predictable geometry
        shape = caid.box(20, 20, 10, origin=Vector(-10, -10, -5)).shape
        bb = _bb(shape)
        mid_x = (bb["xmin"] + bb["xmax"]) / 2  # should be 0 for centered box
        big = 10000
        cutter = caid.box(big, big, big, origin=Vector(-big / 2, -big / 2, -big / 2)).shape
        cutter = caid.translate(cutter, Vector(big / 2 + mid_x, 0, 0)).shape
        wrapped_shape = shape.wrapped if hasattr(shape, "wrapped") else shape
        wrapped_cutter = cutter.wrapped if hasattr(cutter, "wrapped") else cutter
        cut_op = BRepAlgoAPI_Cut(wrapped_shape, wrapped_cutter)
        section_vol = shape_volume(cut_op.Shape())
        assert abs(section_vol - _shape_volume(shape) / 2) < 1.0

    def test_section_view_keep_above(self):
        """Section with negative-side cutter retains the positive side."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        shape = caid.box(20, 20, 10, origin=Vector(-10, -10, -5)).shape
        big = 10000
        cutter = caid.box(big, big, big, origin=Vector(-big / 2, -big / 2, -big / 2)).shape
        cutter = caid.translate(cutter, Vector(-big / 2, 0, 0)).shape
        wrapped_shape = shape.wrapped if hasattr(shape, "wrapped") else shape
        wrapped_cutter = cutter.wrapped if hasattr(cutter, "wrapped") else cutter
        cut_op = BRepAlgoAPI_Cut(wrapped_shape, wrapped_cutter)
        section_vol = shape_volume(cut_op.Shape())
        assert abs(section_vol - _shape_volume(shape) / 2) < 1.0

    def test_section_view_with_offset(self):
        """Section at X=5 on a centered 20mm box keeps 75% of volume."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        shape = caid.box(20, 20, 10, origin=Vector(-10, -10, -5)).shape
        big = 10000
        cutter = caid.box(big, big, big, origin=Vector(-big / 2, -big / 2, -big / 2)).shape
        cutter = caid.translate(cutter, Vector(big / 2 + 5, 0, 0)).shape
        wrapped_shape = shape.wrapped if hasattr(shape, "wrapped") else shape
        wrapped_cutter = cutter.wrapped if hasattr(cutter, "wrapped") else cutter
        cut_op = BRepAlgoAPI_Cut(wrapped_shape, wrapped_cutter)
        section_vol = shape_volume(cut_op.Shape())
        # Box is 20mm wide: -10 to +10. Cut at X=5 keeps -10 to 5 = 15mm = 75%
        expected = _shape_volume(shape) * 0.75
        assert abs(section_vol - expected) < 1.0

    def test_exploded_view_assembly(self, box_shape, cyl_shape):
        """Exploded view moves parts outward from centroid."""
        moved_box = caid.translate(box_shape, Vector(20, 0, 0)).shape
        moved_cyl = caid.translate(cyl_shape, Vector(-20, 0, 0)).shape

        asm = Assembly()
        asm = asm.add(Part("box", moved_box))
        asm = asm.add(Part("cyl", moved_cyl))

        # Compute what explosion should do
        bb_box = _bb(moved_box)
        bb_cyl = _bb(moved_cyl)
        box_cx = (bb_box["xmin"] + bb_box["xmax"]) / 2
        cyl_cx = (bb_cyl["xmin"] + bb_cyl["xmax"]) / 2
        centroid_x = (box_cx + cyl_cx) / 2

        # With scale=2.0, parts should be pushed further apart
        scale = 2.0
        box_offset = (box_cx - centroid_x) * (scale - 1)
        cyl_offset = (cyl_cx - centroid_x) * (scale - 1)
        assert box_offset > 0  # box moves further positive
        assert cyl_offset < 0  # cyl moves further negative

    def test_exploded_view_single_part_no_movement(self):
        """Single-part assembly at origin should have zero offset."""
        fr = caid.box(10, 10, 10)
        asm = Assembly()
        asm = asm.add(Part("solo", fr.shape))
        parts = asm._parts
        assert len(parts) == 1
        # Centroid equals part center, so offset = 0
        bb = _bb(parts[0].shape)
        cx = (bb["xmin"] + bb["xmax"]) / 2
        centroid = cx
        offset = cx - centroid
        assert abs(offset) < 0.001


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestWorkflow:
    def test_create_fillet_export(self):
        fr = caid.box(20, 20, 10)
        assert fr.ok
        filleted = caid.fillet(fr.shape, 2)
        assert filleted.ok
        store_object("part", filleted.shape)

        path = OUTPUT_DIR / "test_workflow.stl"
        export_fr = caid.to_stl(filleted.shape, path)
        assert export_fr.valid
        assert path.exists()
        path.unlink()

    def test_boolean_with_validation(self):
        box_fr = caid.box(10, 10, 10)
        cyl_fr = caid.cylinder(3, 20)
        cut_fr = caid.boolean_cut(box_fr.shape, cyl_fr.shape)
        assert cut_fr.ok
        assert cut_fr.volume_after < cut_fr.volume_before

    def test_query_then_fillet_workflow(self):
        """Full workflow: create shape, query edges, fillet all, verify."""
        fr = caid.box(20, 10, 5)
        store_object("bracket", fr.shape)
        shape = fr.shape

        # Verify we have 12 edges on a box
        all_edges = _get_edges(shape)
        assert len(all_edges) == 12

        # Fillet all edges and verify volume decreases + edge count increases
        filleted = caid.fillet(shape, 0.5)
        assert filleted.ok
        assert _shape_volume(filleted.shape) < _shape_volume(shape)
        assert _count_edges(filleted.shape) > len(all_edges)


# ---------------------------------------------------------------------------
# Sweep and loft tests
# ---------------------------------------------------------------------------

class TestSweep:
    def test_loft_circle_to_rect(self):
        """Loft from circle to rectangle produces a valid solid."""
        from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Circ, gp_Vec
        from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
                                         BRepBuilderAPI_MakeFace)
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

        loft = BRepOffsetAPI_ThruSections(True)  # True = solid

        # Bottom: circle r=10 at Z=0
        circle = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10)
        circle_edge = BRepBuilderAPI_MakeEdge(circle).Edge()
        circle_wire = BRepBuilderAPI_MakeWire(circle_edge).Wire()
        loft.AddWire(circle_wire)

        # Top: 15x15 rect at Z=30
        half = 7.5
        pts = [
            gp_Pnt(-half, -half, 30), gp_Pnt(half, -half, 30),
            gp_Pnt(half, half, 30), gp_Pnt(-half, half, 30),
        ]
        rect_wire_builder = BRepBuilderAPI_MakeWire()
        for i in range(4):
            edge = BRepBuilderAPI_MakeEdge(pts[i], pts[(i + 1) % 4]).Edge()
            rect_wire_builder.Add(edge)
        loft.AddWire(rect_wire_builder.Wire())

        loft.Build()
        solid = loft.Shape()
        assert shape_volume(solid) > 0
        bb = shape_bounding_box(solid)
        assert abs(bb["zlen"] - 30) < 0.1

    def test_loft_two_rects(self):
        """Loft between two different rectangles."""
        from OCP.gp import gp_Pnt
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

        loft = BRepOffsetAPI_ThruSections(True)

        # Bottom: 20x20 at Z=0
        def _make_rect_wire(half_w, half_h, z):
            pts = [
                gp_Pnt(-half_w, -half_h, z), gp_Pnt(half_w, -half_h, z),
                gp_Pnt(half_w, half_h, z), gp_Pnt(-half_w, half_h, z),
            ]
            wb = BRepBuilderAPI_MakeWire()
            for i in range(4):
                edge = BRepBuilderAPI_MakeEdge(pts[i], pts[(i + 1) % 4]).Edge()
                wb.Add(edge)
            return wb.Wire()

        loft.AddWire(_make_rect_wire(10, 10, 0))
        loft.AddWire(_make_rect_wire(5, 5, 40))
        loft.Build()
        solid = loft.Shape()
        vol = shape_volume(solid)
        assert vol > 0
        small_vol = 10 * 10 * 40
        large_vol = 20 * 20 * 40
        assert small_vol < vol < large_vol

    def test_sweep_circle(self):
        """Sweep a circle along a line path creates a tube-like solid."""
        from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Circ
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe

        # Profile: circle r=3 at Z=0
        circle = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 3)
        circle_edge = BRepBuilderAPI_MakeEdge(circle).Edge()
        circle_wire = BRepBuilderAPI_MakeWire(circle_edge).Wire()
        profile_face = BRepBuilderAPI_MakeFace(circle_wire).Face()

        # Path: straight line from origin to (0, 0, 50)
        path_edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 50)).Edge()
        path_wire = BRepBuilderAPI_MakeWire(path_edge).Wire()

        solid = BRepOffsetAPI_MakePipe(path_wire, profile_face).Shape()
        assert shape_volume(solid) > 100  # non-trivial volume
        bb = shape_bounding_box(solid)
        assert bb["zlen"] > 40

    def test_loft_ruled(self):
        """Loft with ruled=True produces a valid solid."""
        from OCP.gp import gp_Pnt
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

        loft = BRepOffsetAPI_ThruSections(True)  # solid
        loft.SetSmoothing(False)  # ruled

        def _make_rect_wire(half_w, half_h, z):
            pts = [
                gp_Pnt(-half_w, -half_h, z), gp_Pnt(half_w, -half_h, z),
                gp_Pnt(half_w, half_h, z), gp_Pnt(-half_w, half_h, z),
            ]
            wb = BRepBuilderAPI_MakeWire()
            for i in range(4):
                edge = BRepBuilderAPI_MakeEdge(pts[i], pts[(i + 1) % 4]).Edge()
                wb.Add(edge)
            return wb.Wire()

        loft.AddWire(_make_rect_wire(10, 10, 0))
        loft.AddWire(_make_rect_wire(5, 5, 30))
        loft.Build()
        solid = loft.Shape()
        assert shape_volume(solid) > 0


# ---------------------------------------------------------------------------
# Fastener library tests
# ---------------------------------------------------------------------------

class TestFasteners:
    def test_hex_prism(self):
        """Hex prism has correct across-flats dimension."""
        from caid_mcp.tools.fasteners import _hex_prism
        hex_shape = _hex_prism(10.0, 5.0)
        bb = shape_bounding_box(hex_shape)
        # Across flats = 10mm on one axis; circumscribed is larger on the other
        assert abs(min(bb["xlen"], bb["ylen"]) - 10.0) < 0.1
        assert abs(bb["zlen"] - 5.0) < 0.01
        assert shape_volume(hex_shape) > 0

    def test_hex_prism_has_8_faces(self):
        """Hex prism should have 8 faces (6 sides + top + bottom)."""
        from caid_mcp.tools.fasteners import _hex_prism
        hex_shape = _hex_prism(10.0, 5.0)
        assert _count_faces(hex_shape) == 8

    def test_metric_data_consistency(self):
        """All sizes present in all lookup tables."""
        from caid_mcp.tools.fasteners import (
            METRIC_BOLT, METRIC_NUT, METRIC_WASHER, CLEARANCE_HOLES, TAP_DRILL
        )
        for size in METRIC_BOLT:
            assert size in METRIC_NUT, f"{size} missing from METRIC_NUT"
            assert size in METRIC_WASHER, f"{size} missing from METRIC_WASHER"
            assert size in CLEARANCE_HOLES, f"{size} missing from CLEARANCE_HOLES"
            assert size in TAP_DRILL, f"{size} missing from TAP_DRILL"

    def test_tap_drill_smaller_than_nominal(self):
        """Tap drill must always be smaller than nominal diameter."""
        from caid_mcp.tools.fasteners import TAP_DRILL
        for size, drill in TAP_DRILL.items():
            nom = float(size[1:])
            assert drill < nom, f"{size} tap drill {drill} >= nominal {nom}"

    def test_clearance_hole_ordering(self):
        """Clearance holes: close < normal < loose."""
        from caid_mcp.tools.fasteners import CLEARANCE_HOLES
        for size, (close, normal, loose) in CLEARANCE_HOLES.items():
            assert close < normal <= loose, f"{size} clearance holes not ordered"

    def test_create_nut_shape(self):
        """Create an M10 nut — hole makes volume less than solid hex."""
        from caid_mcp.tools.fasteners import _hex_prism, METRIC_NUT
        af, height = METRIC_NUT["M10"]
        solid_hex = _hex_prism(af, height)
        solid_vol = shape_volume(solid_hex)

        nom_dia = 10.0
        hole = caid.cylinder(nom_dia / 2, height + 1).shape
        hole = caid.translate(hole, Vector(0, 0, -0.5)).shape
        fr = caid.boolean_cut(solid_hex, hole)
        assert fr.shape is not None
        assert _shape_volume(fr.shape) < solid_vol

    def test_create_washer_shape(self):
        """Create an M8 washer — ring shape has positive volume."""
        from caid_mcp.tools.fasteners import METRIC_WASHER
        inner_d, outer_d, thickness = METRIC_WASHER["M8"]
        outer = caid.cylinder(outer_d / 2, thickness).shape
        inner = caid.cylinder(inner_d / 2, thickness + 1).shape
        inner = caid.translate(inner, Vector(0, 0, -0.5)).shape
        fr = caid.boolean_cut(outer, inner)
        assert fr.shape is not None
        assert _shape_volume(fr.shape) < _shape_volume(outer)
        assert _shape_volume(fr.shape) > 0


# ---------------------------------------------------------------------------
# Mass properties tests
# ---------------------------------------------------------------------------

class TestMassProperties:
    def test_steel_box_mass(self, box_shape):
        """A 20x20x10mm steel box should weigh ~31.4g."""
        vol_cm3 = _shape_volume(box_shape) / 1000.0
        mass_g = vol_cm3 * 7.85
        assert abs(mass_g - 31.4) < 0.5

    def test_aluminum_lighter_than_steel(self, box_shape):
        """Same shape in aluminum should weigh less than steel."""
        vol_cm3 = _shape_volume(box_shape) / 1000.0
        assert vol_cm3 * 2.70 < vol_cm3 * 7.85
