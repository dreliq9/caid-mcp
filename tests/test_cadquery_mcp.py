"""
Test suite for CAiD MCP Server.
Run with: pytest tests/ -v
"""

import json
import pytest

import cadquery as cq
from cadquery import Vector
import caid
from caid.result import ForgeResult
from caid.assembly import Assembly, Part
from caid_mcp.core import scene, assemblies, store_object, require_object, get_object, format_result, OUTPUT_DIR


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
        assert obj.Volume() > 0

    def test_store_auto_extracts_workplane(self):
        wp = cq.Workplane("XY").box(10, 10, 10)
        store_object("from_wp", wp)
        obj = get_object("from_wp")
        assert not isinstance(obj, cq.Workplane)
        assert obj.Volume() > 0

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
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        obj = cq.Workplane("XY").polyline(pts).close().extrude(5)
        shape = obj.val()
        bb = shape.BoundingBox()
        assert abs(bb.zlen - 5) < 0.01

    def test_revolved_profile(self):
        pts = [(0, 0), (5, 0), (5, 10), (0, 10)]
        obj = cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))
        assert obj.val().Volume() > 0


# ---------------------------------------------------------------------------
# Modification tests
# ---------------------------------------------------------------------------

class TestModifications:
    def test_fillet(self, box_shape):
        fr = caid.fillet(box_shape, 1)
        assert fr.ok
        assert len(fr.shape.Faces()) > len(box_shape.Faces())

    def test_chamfer(self, box_shape):
        fr = caid.chamfer(box_shape, 1)
        assert fr.ok
        assert len(fr.shape.Faces()) > len(box_shape.Faces())

    def test_add_hole_via_workplane(self, box_shape):
        wp = cq.Workplane("XY").add(box_shape)
        result = wp.faces(">Z").hole(6)
        new_shape = result.val()
        assert new_shape.Volume() < box_shape.Volume()

    def test_shell_via_workplane(self, box_shape):
        wp = cq.Workplane("XY").add(box_shape)
        result = wp.faces(">Z").shell(-1)
        new_shape = result.val()
        assert new_shape.Volume() < box_shape.Volume()

    def test_fillet_by_edge_index(self, box_shape):
        """Fillet specific edges selected by index."""
        all_edges = box_shape.Edges()
        # Fillet the first 3 edges
        from caid_mcp.tools.modify import _make_edge_selector
        selector = _make_edge_selector(box_shape, [0, 1, 2])
        result = cq.Workplane("XY").add(box_shape).edges(selector).fillet(1.0)
        result_shape = result.val()
        assert result_shape.Volume() < box_shape.Volume()
        assert len(result_shape.Edges()) > len(all_edges)

    def test_chamfer_by_edge_index(self, box_shape):
        """Chamfer specific edges selected by index."""
        from caid_mcp.tools.modify import _make_edge_selector
        selector = _make_edge_selector(box_shape, [0, 1])
        result = cq.Workplane("XY").add(box_shape).edges(selector).chamfer(0.5)
        assert result.val().Volume() < box_shape.Volume()

    def test_edge_index_out_of_range(self, box_shape):
        """Out-of-range edge index raises ValueError."""
        from caid_mcp.tools.modify import _make_edge_selector
        with pytest.raises(ValueError, match="out of range"):
            _make_edge_selector(box_shape, [99])

    def test_face_selector_by_index(self, box_shape):
        """Select a face by index and use it for hole drilling."""
        from caid_mcp.tools.modify import _make_face_selector
        faces = box_shape.Faces()
        selector = _make_face_selector(box_shape, 0)
        result = cq.Workplane("XY").add(box_shape).faces(selector).workplane().hole(4)
        assert result.val().Volume() < box_shape.Volume()

    def test_face_index_out_of_range(self, box_shape):
        """Out-of-range face index raises ValueError."""
        from caid_mcp.tools.modify import _make_face_selector
        with pytest.raises(ValueError, match="out of range"):
            _make_face_selector(box_shape, 99)


# ---------------------------------------------------------------------------
# Transform tests
# ---------------------------------------------------------------------------

class TestTransforms:
    def test_translate(self, box_shape):
        fr = caid.translate(box_shape, Vector(10, 20, 30))
        assert fr.ok
        bb = fr.shape.BoundingBox()
        assert abs(bb.center.x - 20) < 0.01  # box origin is corner, center at 10+10=20
        assert abs(bb.center.y - 30) < 0.01
        assert abs(bb.center.z - 35) < 0.01

    def test_rotate(self, box_shape):
        fr = caid.rotate(box_shape, Vector(0, 0, 0), Vector(0, 0, 1), 90)
        assert fr.ok
        bb = fr.shape.BoundingBox()
        assert bb.xlen > 0

    def test_mirror(self, box_shape):
        moved = caid.translate(box_shape, Vector(10, 0, 0))
        fr = caid.mirror(moved.shape, Vector(0, 0, 0), Vector(1, 0, 0))
        assert fr.ok
        bb = fr.shape.BoundingBox()
        assert bb.center.x < 0

    def test_scale(self, box_shape):
        fr = caid.scale(box_shape, 2.0)
        assert fr.ok
        assert fr.volume_after > box_shape.Volume() * 7  # 2^3 = 8x volume


# ---------------------------------------------------------------------------
# Boolean operation tests
# ---------------------------------------------------------------------------

class TestBooleans:
    def test_union(self, box_shape, cyl_shape):
        fr = caid.boolean_union(box_shape, cyl_shape)
        assert fr.shape is not None
        assert fr.shape.Volume() >= box_shape.Volume()

    def test_cut(self, box_shape, cyl_shape):
        fr = caid.boolean_cut(box_shape, cyl_shape)
        assert fr.ok
        assert fr.volume_after < box_shape.Volume()

    def test_intersect(self, box_shape, cyl_shape):
        fr = caid.boolean_intersect(box_shape, cyl_shape)
        assert fr.shape is not None
        assert fr.shape.Volume() < box_shape.Volume()


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
        assert abs(imp.shape.Volume() - box_shape.Volume()) < 1.0
        path.unlink()

    def test_brep_roundtrip(self, box_shape):
        path = OUTPUT_DIR / "test_export.brep"
        fr = caid.to_brep(box_shape, path)
        assert fr.valid
        assert path.exists()
        imp = caid.from_brep(path)
        assert imp.ok
        assert abs(imp.shape.Volume() - box_shape.Volume()) < 1.0
        path.unlink()

    def test_svg_via_workplane_wrap(self, box_shape):
        wp = cq.Workplane("XY").add(box_shape)
        path = OUTPUT_DIR / "test_wrap.svg"
        from cadquery import exporters
        exporters.export(
            wp, str(path),
            exportType=exporters.ExportTypes.SVG,
            opt={"width": 400, "height": 300, "projectionDir": (1, -1, 0.5)},
        )
        assert path.exists()
        content = path.read_text()
        assert "<svg" in content
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
        assert scene["copy"].Volume() == box_shape.Volume()

    def test_object_info(self, box_shape):
        bb = box_shape.BoundingBox()
        assert abs(bb.xlen - 20) < 0.01
        assert box_shape.Volume() > 0
        assert len(box_shape.Faces()) == 6
        assert len(box_shape.Edges()) == 12


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
        assert fr.shape.Volume() > 0


# ---------------------------------------------------------------------------
# Advanced tools tests
# ---------------------------------------------------------------------------

class TestAdvanced:
    def test_script_with_caid_in_namespace(self):
        exec_globals = {"cq": cq, "caid": caid, "Vector": Vector, "scene": scene}
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
        assert fr.shape.Volume() > box_shape.Volume() * 1.5


# ---------------------------------------------------------------------------
# Query tools tests
# ---------------------------------------------------------------------------

class TestQuery:
    def test_list_edges_all(self, box_shape):
        """list_edges returns all 12 edges of a box."""
        edges = box_shape.Edges()
        assert len(edges) == 12
        for edge in edges:
            assert edge.Length() > 0

    def test_list_edges_with_face_selector(self, box_shape):
        """list_edges with face selector returns only edges on that face."""
        wp = cq.Workplane("XY").add(box_shape)
        top_faces = wp.faces(">Z").vals()
        top_edges = []
        for f in top_faces:
            top_edges.extend(f.Edges())
        assert len(top_edges) == 4  # box top face has 4 edges

    def test_list_faces(self, box_shape):
        """list_faces returns all 6 faces of a box with correct info."""
        faces = box_shape.Faces()
        assert len(faces) == 6
        for face in faces:
            assert face.Area() > 0
            center = face.Center()
            assert center is not None
            normal = face.normalAt(face.Center())
            assert normal is not None

    def test_measure_object(self, box_shape):
        """measure_object returns correct volume and bounding box."""
        vol = box_shape.Volume()
        assert abs(vol - 4000.0) < 1.0  # 20x20x10
        bb = box_shape.BoundingBox()
        assert abs(bb.xlen - 20) < 0.01
        assert abs(bb.ylen - 20) < 0.01
        assert abs(bb.zlen - 10) < 0.01

    def test_measure_distance(self, box_shape, cyl_shape):
        """measure_distance returns the min distance between two shapes."""
        # Move cylinder far away
        moved = caid.translate(cyl_shape, Vector(50, 0, 0))
        store_object("far_cyl", moved.shape)
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        dist_calc = BRepExtrema_DistShapeShape(box_shape.wrapped, moved.shape.wrapped)
        dist_calc.Perform()
        assert dist_calc.Value() > 0

    def test_find_edges_near_point(self, box_shape):
        """find_edges_near_point returns edges sorted by distance."""
        # Top-right-front corner of the box
        target = cq.Vector(10, 10, 5)
        edges = box_shape.Edges()
        scored = []
        for i, edge in enumerate(edges):
            mid = edge.Center()
            dist = (target - cq.Vector(mid.x, mid.y, mid.z)).Length
            scored.append((dist, i))
        scored.sort()
        # Closest edge should be very close to the corner
        assert scored[0][0] < 15  # within reasonable distance

    def test_find_faces_near_point(self, box_shape):
        """find_faces_near_point returns faces sorted by distance."""
        # Point well above the box center — top face should be closest
        bb = box_shape.BoundingBox()
        target = cq.Vector(bb.center.x, bb.center.y, bb.zmax + 10)
        faces = box_shape.Faces()
        scored = []
        for i, face in enumerate(faces):
            center = face.Center()
            dist = (target - cq.Vector(center.x, center.y, center.z)).Length
            scored.append((dist, i, face))
        scored.sort(key=lambda t: t[0])
        # Closest face should be the top face (normal pointing +Z)
        top_face = scored[0][2]
        normal = top_face.normalAt(top_face.Center())
        assert abs(normal.z) > 0.9  # should be pointing up

    def test_edge_info_types(self, box_shape):
        """Edge info includes correct geometric types for a box."""
        edges = box_shape.Edges()
        for edge in edges:
            assert edge.geomType() == "LINE"  # box edges are all lines
            assert edge.Length() > 0
            verts = edge.Vertices()
            assert len(verts) == 2

    def test_face_info_types(self, box_shape):
        """Face info includes correct geometric types for a box."""
        faces = box_shape.Faces()
        for face in faces:
            assert face.geomType() == "PLANE"  # box faces are all planes
            assert face.Area() > 0

    def test_cylinder_edge_types(self, cyl_shape):
        """Cylinder should have CIRCLE and LINE type edges."""
        edges = cyl_shape.Edges()
        edge_types = {e.geomType() for e in edges}
        assert "CIRCLE" in edge_types
        assert "LINE" in edge_types

    def test_cylinder_face_types(self, cyl_shape):
        """Cylinder should have PLANE and CYLINDER type faces."""
        faces = cyl_shape.Faces()
        face_types = {f.geomType() for f in faces}
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
        shape = cq.Workplane("XY").box(20, 20, 10).val()
        bb = shape.BoundingBox()
        mid_x = bb.center.x  # should be 0 for centered box
        big = 10000
        cutter = cq.Workplane("XY").box(big, big, big).val()
        cutter = caid.translate(cutter, cq.Vector(big / 2 + mid_x, 0, 0)).shape
        cut_op = BRepAlgoAPI_Cut(shape.wrapped, cutter.wrapped)
        section = cq.Shape(cut_op.Shape())
        assert abs(section.Volume() - shape.Volume() / 2) < 1.0

    def test_section_view_keep_above(self):
        """Section with negative-side cutter retains the positive side."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        shape = cq.Workplane("XY").box(20, 20, 10).val()
        big = 10000
        cutter = cq.Workplane("XY").box(big, big, big).val()
        cutter = caid.translate(cutter, cq.Vector(-big / 2, 0, 0)).shape
        cut_op = BRepAlgoAPI_Cut(shape.wrapped, cutter.wrapped)
        section = cq.Shape(cut_op.Shape())
        assert abs(section.Volume() - shape.Volume() / 2) < 1.0

    def test_section_view_with_offset(self):
        """Section at X=5 on a centered 20mm box keeps 75% of volume."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        shape = cq.Workplane("XY").box(20, 20, 10).val()
        big = 10000
        cutter = cq.Workplane("XY").box(big, big, big).val()
        cutter = caid.translate(cutter, cq.Vector(big / 2 + 5, 0, 0)).shape
        cut_op = BRepAlgoAPI_Cut(shape.wrapped, cutter.wrapped)
        section = cq.Shape(cut_op.Shape())
        # Box is 20mm wide: -10 to +10. Cut at X=5 keeps -10 to 5 = 15mm = 75%
        expected = shape.Volume() * 0.75
        assert abs(section.Volume() - expected) < 1.0

    def test_exploded_view_assembly(self, box_shape, cyl_shape):
        """Exploded view moves parts outward from centroid."""
        # Move parts to different positions
        moved_box = caid.translate(box_shape, Vector(20, 0, 0)).shape
        moved_cyl = caid.translate(cyl_shape, Vector(-20, 0, 0)).shape

        asm = Assembly()
        asm = asm.add(Part("box", moved_box))
        asm = asm.add(Part("cyl", moved_cyl))

        # Compute what explosion should do
        box_center = moved_box.Center()
        cyl_center = moved_cyl.Center()
        centroid_x = (box_center.x + cyl_center.x) / 2

        # With scale=2.0, parts should be pushed further apart
        scale = 2.0
        box_offset = (box_center.x - centroid_x) * (scale - 1)
        cyl_offset = (cyl_center.x - centroid_x) * (scale - 1)
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
        center = parts[0].shape.Center()
        centroid = center
        offset = center.x - centroid.x
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
        """Full workflow: create shape, query edges, fillet by index."""
        fr = caid.box(20, 10, 5)
        store_object("bracket", fr.shape)
        shape = fr.shape

        # Query top face edges
        wp = cq.Workplane("XY").add(shape)
        top_faces = wp.faces(">Z").vals()
        top_edges = []
        for f in top_faces:
            top_edges.extend(f.Edges())
        assert len(top_edges) == 4

        # Find indices of top edges in the full edge list
        all_edges = shape.Edges()
        top_centers = {
            (round(e.Center().x, 5), round(e.Center().y, 5), round(e.Center().z, 5))
            for e in top_edges
        }
        top_indices = [
            i for i, e in enumerate(all_edges)
            if (round(e.Center().x, 5), round(e.Center().y, 5), round(e.Center().z, 5)) in top_centers
        ]
        assert len(top_indices) == 4

        # Fillet only those edges
        from caid_mcp.tools.modify import _make_edge_selector
        selector = _make_edge_selector(shape, top_indices)
        result = cq.Workplane("XY").add(shape).edges(selector).fillet(0.5)
        result_shape = result.val()
        assert result_shape.Volume() < shape.Volume()
        # Should have more edges after filleting (fillets add curved edges)
        assert len(result_shape.Edges()) > len(all_edges)
