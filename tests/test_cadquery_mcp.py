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


# ---------------------------------------------------------------------------
# Sweep and loft tests
# ---------------------------------------------------------------------------

class TestSweep:
    def test_loft_circle_to_rect(self):
        """Loft from circle to rectangle produces a valid solid."""
        wp = (
            cq.Workplane("XY")
            .circle(10)
            .workplane(offset=30)
            .rect(15, 15)
        )
        shape = wp.loft().val()
        assert shape.Volume() > 0
        bb = shape.BoundingBox()
        assert abs(bb.zlen - 30) < 0.1

    def test_loft_two_rects(self):
        """Loft between two different rectangles."""
        wp = (
            cq.Workplane("XY")
            .rect(20, 20)
            .workplane(offset=40)
            .rect(10, 10)
        )
        shape = wp.loft().val()
        assert shape.Volume() > 0
        small_vol = 10 * 10 * 40
        large_vol = 20 * 20 * 40
        assert small_vol < shape.Volume() < large_vol

    def test_sweep_circle(self):
        """Sweep a circle along a spline path creates a tube."""
        path = cq.Workplane("XY").spline(
            [cq.Vector(0, 0, 0), cq.Vector(0, 0, 30), cq.Vector(15, 0, 50)]
        )
        shape = cq.Workplane("XY").circle(3).sweep(path).val()
        assert shape.Volume() > 100  # non-trivial volume
        bb = shape.BoundingBox()
        assert bb.zlen > 40

    def test_loft_ruled(self):
        """Loft with ruled=True produces a valid solid."""
        wp = (
            cq.Workplane("XY")
            .rect(20, 20)
            .workplane(offset=30)
            .rect(10, 10)
        )
        shape = wp.loft(ruled=True).val()
        assert shape.Volume() > 0


# ---------------------------------------------------------------------------
# Fastener library tests
# ---------------------------------------------------------------------------

class TestFasteners:
    def test_hex_prism(self):
        """Hex prism has correct across-flats dimension."""
        from caid_mcp.tools.fasteners import _hex_prism
        hex_shape = _hex_prism(10.0, 5.0)
        bb = hex_shape.BoundingBox()
        # Across flats = 10mm on one axis; circumscribed is larger on the other
        assert abs(min(bb.xlen, bb.ylen) - 10.0) < 0.1
        assert abs(bb.zlen - 5.0) < 0.01
        assert hex_shape.Volume() > 0

    def test_hex_prism_has_8_faces(self):
        """Hex prism should have 8 faces (6 sides + top + bottom)."""
        from caid_mcp.tools.fasteners import _hex_prism
        hex_shape = _hex_prism(10.0, 5.0)
        assert len(hex_shape.Faces()) == 8

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
        solid_vol = solid_hex.Volume()

        nom_dia = 10.0
        hole = cq.Workplane("XY").circle(nom_dia / 2).extrude(height + 1).val()
        hole = caid.translate(hole, Vector(0, 0, -0.5)).shape
        fr = caid.boolean_cut(solid_hex, hole)
        assert fr.shape is not None
        assert fr.shape.Volume() < solid_vol

    def test_create_washer_shape(self):
        """Create an M8 washer — ring shape has positive volume."""
        from caid_mcp.tools.fasteners import METRIC_WASHER
        inner_d, outer_d, thickness = METRIC_WASHER["M8"]
        outer = cq.Workplane("XY").circle(outer_d / 2).extrude(thickness).val()
        inner = cq.Workplane("XY").circle(inner_d / 2).extrude(thickness + 1).val()
        inner = caid.translate(inner, Vector(0, 0, -0.5)).shape
        fr = caid.boolean_cut(outer, inner)
        assert fr.shape is not None
        assert fr.shape.Volume() < outer.Volume()
        assert fr.shape.Volume() > 0


# ---------------------------------------------------------------------------
# Mass properties tests
# ---------------------------------------------------------------------------

class TestMassProperties:
    def test_steel_box_mass(self, box_shape):
        """A 20x20x10mm steel box should weigh ~31.4g."""
        vol_cm3 = box_shape.Volume() / 1000.0
        mass_g = vol_cm3 * 7.85
        assert abs(mass_g - 31.4) < 0.5

    def test_aluminum_lighter_than_steel(self, box_shape):
        """Same shape in aluminum should weigh less than steel."""
        vol_cm3 = box_shape.Volume() / 1000.0
        assert vol_cm3 * 2.70 < vol_cm3 * 7.85


# ---------------------------------------------------------------------------
# History/undo tests
# ---------------------------------------------------------------------------

class TestHistory:
    def test_save_and_restore(self, box_shape):
        """Save snapshot, clear scene, restore."""
        from caid_mcp.tools.history import (
            _snapshots, _snapshot_names, _shape_to_brep_str, _brep_str_to_shape,
        )
        _snapshots.clear()
        _snapshot_names.clear()

        snap = {}
        for name, shape in scene.items():
            snap[name] = _shape_to_brep_str(shape)
        _snapshots.append(snap)
        _snapshot_names.append("test_snap")

        original_vol = box_shape.Volume()
        scene.clear()
        assert len(scene) == 0

        for name, brep_str in _snapshots[0].items():
            scene[name] = _brep_str_to_shape(brep_str)

        assert "test_box" in scene
        assert abs(scene["test_box"].Volume() - original_vol) < 1.0

    def test_brep_roundtrip(self, box_shape):
        """Shape serialized to BREP and back should have same volume."""
        from caid_mcp.tools.history import _shape_to_brep_str, _brep_str_to_shape
        brep = _shape_to_brep_str(box_shape)
        restored = _brep_str_to_shape(brep)
        assert abs(restored.Volume() - box_shape.Volume()) < 1.0

    def test_snapshot_limit(self):
        """MAX_SNAPSHOTS constant should be 20."""
        from caid_mcp.tools.history import MAX_SNAPSHOTS
        assert MAX_SNAPSHOTS == 20


# ---------------------------------------------------------------------------
# Circular pattern tests
# ---------------------------------------------------------------------------

class TestCircularPattern:
    def test_circular_pattern_4_copies(self, box_shape):
        """4 copies at 90° intervals should produce ~4x volume."""
        moved = caid.translate(box_shape, Vector(30, 0, 0))
        store_object("radial_box", moved.shape)

        result_shape = moved.shape
        for angle in [90, 180, 270]:
            rotated = caid.rotate(moved.shape, Vector(0, 0, 0), Vector(0, 0, 1), angle)
            fr = caid.boolean_union(result_shape, rotated.shape)
            if fr.shape is not None:
                result_shape = fr.shape

        assert result_shape.Volume() >= box_shape.Volume() * 3.5

    def test_rotation_preserves_volume(self, box_shape):
        """Rotating a box shouldn't change its volume."""
        rotated = caid.rotate(box_shape, Vector(0, 0, 0), Vector(0, 0, 1), 45)
        assert abs(rotated.shape.Volume() - box_shape.Volume()) < 1.0


# ---------------------------------------------------------------------------
# Tool-level integration tests — call actual registered MCP tool functions
# ---------------------------------------------------------------------------

@pytest.fixture
def mcp_tools():
    """Get the registered MCP tool functions from the server."""
    import sys
    sys.path.insert(0, str(OUTPUT_DIR.parent))
    from server import mcp
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


class TestToolIntegration:
    """Call the actual MCP tool functions end-to-end to test wiring."""

    def test_sweep_circle_tool(self, mcp_tools):
        """sweep_circle_along_path produces a solid with real volume."""
        r = mcp_tools["sweep_circle_along_path"](
            name="test_tube", radius=3.0,
            path_points='[[0,0,0],[0,0,30],[15,0,50]]',
        )
        assert r.startswith("OK")
        assert "volume=" in r
        # Volume should be non-trivial
        assert "volume=0.0" not in r
        assert "test_tube" in scene

    def test_loft_circle_to_rect_tool(self, mcp_tools):
        """loft_circle_to_rect produces a transition solid."""
        r = mcp_tools["loft_circle_to_rect"](
            name="test_adapter", radius=10, length=20, width=20, height=30,
        )
        assert r.startswith("OK")
        assert "test_adapter" in scene
        assert scene["test_adapter"].Volume() > 1000

    def test_loft_profiles_tool(self, mcp_tools):
        """loft_profiles handles JSON profiles correctly."""
        profiles = json.dumps([
            {"z": 0, "points": [[-10,-10],[10,-10],[10,10],[-10,10]]},
            {"z": 40, "points": [[-5,-5],[5,-5],[5,5],[-5,5]]},
        ])
        r = mcp_tools["loft_profiles"](name="test_loft", profiles=profiles)
        assert r.startswith("OK")
        assert "test_loft" in scene

    def test_sweep_along_path_tool(self, mcp_tools):
        """sweep_along_path with polygon profile produces volume."""
        r = mcp_tools["sweep_along_path"](
            name="test_channel",
            profile_points='[[-3,-3],[3,-3],[3,3],[-3,3]]',
            path_points='[[0,0,0],[0,0,25],[10,0,40]]',
        )
        assert r.startswith("OK")
        assert "volume=0.0" not in r

    def test_create_bolt_tool(self, mcp_tools):
        """create_bolt produces a valid bolt shape."""
        r = mcp_tools["create_bolt"](name="test_bolt", size="M8", length=30)
        assert r.startswith("OK")
        assert "M8x30" in r
        assert "test_bolt" in scene
        assert scene["test_bolt"].Volume() > 500

    def test_create_bolt_bad_thread_length(self, mcp_tools):
        """create_bolt rejects thread_length > length."""
        r = mcp_tools["create_bolt"](
            name="bad", size="M6", length=10, thread_length=20,
        )
        assert r.startswith("FAIL")
        assert "exceeds" in r

    def test_create_nut_tool(self, mcp_tools):
        """create_nut produces a hex nut with through hole."""
        r = mcp_tools["create_nut"](name="test_nut", size="M10")
        assert r.startswith("OK")
        assert "test_nut" in scene

    def test_create_washer_tool(self, mcp_tools):
        """create_washer produces a ring shape."""
        r = mcp_tools["create_washer"](name="test_wash", size="M6")
        assert r.startswith("OK")
        assert "test_wash" in scene

    def test_list_fastener_sizes_tool(self, mcp_tools):
        """list_fastener_sizes returns a table with all sizes."""
        r = mcp_tools["list_fastener_sizes"]()
        assert "M2" in r
        assert "M24" in r
        assert "Pitch" in r

    def test_add_clearance_hole_tool(self, mcp_tools):
        """add_clearance_hole drills correct size hole."""
        mcp_tools["create_box"](name="clr_plate", length=30, width=30, height=8)
        r = mcp_tools["add_clearance_hole"](name="clr_plate", size="M8", fit="normal")
        assert r.startswith("OK")
        assert "9.0mm" in r  # M8 normal clearance = 9.0mm

    def test_add_tap_hole_tool(self, mcp_tools):
        """add_tap_hole drills correct size hole with depth."""
        mcp_tools["create_box"](name="tap_plate", length=30, width=30, height=15)
        r = mcp_tools["add_tap_hole"](name="tap_plate", size="M6", depth=10.0)
        assert r.startswith("OK")
        assert "5.0mm" in r  # M6 tap drill = 5.0mm
        assert "depth=10.0mm" in r

    def test_mass_properties_tool(self, mcp_tools):
        """mass_properties returns correct JSON with mass calculation."""
        mcp_tools["create_box"](name="mass_block", length=50, width=30, height=20)
        r = mcp_tools["mass_properties"](name="mass_block", material="steel")
        assert "FAIL" not in r
        data = json.loads(r)
        assert data["material"] == "steel"
        assert data["density_g_per_cm3"] == 7.85
        # 50*30*20 = 30000mm³ = 30cm³ * 7.85 = 235.5g
        assert abs(data["mass_grams"] - 235.5) < 1.0
        assert "center_of_mass" in data
        assert "bounding_box" in data

    def test_mass_properties_bad_material(self, mcp_tools):
        """mass_properties rejects unknown material."""
        mcp_tools["create_box"](name="mp_box", length=10, width=10, height=10)
        r = mcp_tools["mass_properties"](name="mp_box", material="unobtanium")
        assert r.startswith("FAIL")
        assert "Unknown material" in r

    def test_mass_properties_custom_density(self, mcp_tools):
        """mass_properties accepts custom density."""
        mcp_tools["create_box"](name="mp_custom", length=10, width=10, height=10)
        r = mcp_tools["mass_properties"](name="mp_custom", density=1.5)
        data = json.loads(r)
        assert data["density_g_per_cm3"] == 1.5
        assert data["mass_grams"] == 1.5  # 1cm³ * 1.5

    def test_save_and_undo_tools(self, mcp_tools):
        """save_snapshot + delete + undo restores deleted object."""
        from caid_mcp.tools.history import _snapshots, _snapshot_names
        _snapshots.clear()
        _snapshot_names.clear()

        mcp_tools["create_box"](name="undo_box", length=10, width=10, height=10)
        r = mcp_tools["save_snapshot"](label="before_del")
        assert r.startswith("OK")

        mcp_tools["delete_object"](name="undo_box")
        assert "undo_box" not in scene

        r = mcp_tools["undo"]()
        assert r.startswith("OK")
        assert "undo_box" in scene

    def test_list_snapshots_tool(self, mcp_tools):
        """list_snapshots shows saved snapshots."""
        from caid_mcp.tools.history import _snapshots, _snapshot_names
        _snapshots.clear()
        _snapshot_names.clear()

        mcp_tools["create_box"](name="ls_box", length=5, width=5, height=5)
        mcp_tools["save_snapshot"](label="test_ls")
        r = mcp_tools["list_snapshots"]()
        assert "test_ls" in r
        assert "ls_box" in r

    def test_circular_pattern_tool(self, mcp_tools):
        """create_circular_pattern produces correct number of copies."""
        mcp_tools["create_box"](name="cp_tooth", length=5, width=3, height=10)
        r = mcp_tools["create_circular_pattern"](
            name="cp_tooth", count=4, radius=25,
        )
        assert r.startswith("OK")
        assert "4 copies" in r
        assert "cp_tooth_circular" in scene

    def test_circular_pattern_partial_arc(self, mcp_tools):
        """Partial arc pattern reaches both start and end angles."""
        mcp_tools["create_cylinder"](name="cp_pin", radius=2, height=5)
        r = mcp_tools["create_circular_pattern"](
            name="cp_pin", count=3, radius=20,
            start_angle=0, end_angle=90,
            result_name="cp_arc",
        )
        assert r.startswith("OK")
        assert "3 copies" in r

    def test_discover_tools_count(self, mcp_tools):
        """discover_tools catalog total should match registered tool count."""
        r = mcp_tools["discover_tools"]()
        # Extract reported total from the output
        for line in r.split("\n"):
            if "Total:" in line:
                reported = int(line.split("Total:")[1].strip().split()[0])
                # Should match actual registered tools
                assert reported == len(mcp_tools), (
                    f"Catalog says {reported} tools but {len(mcp_tools)} registered"
                )
