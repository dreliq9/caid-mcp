"""Spatial transformation tools — backed by caid."""

import json
import math
from typing import Optional

from caid.vector import Vector
from mcp.server.fastmcp import FastMCP
import caid

from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf, gp_Ax1, gp_Dir
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

from caid_mcp.core import (
    require_object, store_object, format_result,
    shape_bounding_box, _unwrap, shape_volume, shape_area,
    parse_points,
)
from caid.result import ForgeResult


def register(mcp: FastMCP) -> None:
    """Register all transform tools."""

    @mcp.tool()
    def translate_object(name: str, x: float = 0, y: float = 0, z: float = 0) -> str:
        """Move an object by a given offset.

        Args:
            name: Name of existing object.
            x: Move distance along X (mm).
            y: Move distance along Y (mm).
            z: Move distance along Z (mm).
        """
        try:
            shape = require_object(name)
            fr = caid.translate(shape, Vector(x, y, z))
            msg = format_result(fr, f"Translated '{name}' by ({x}, {y}, {z})")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def rotate_object(
        name: str, axis_x: float = 0, axis_y: float = 0, axis_z: float = 1, angle: float = 0,
    ) -> str:
        """Rotate an object around an axis through the origin.

        Args:
            name: Name of existing object.
            axis_x: X component of rotation axis.
            axis_y: Y component of rotation axis.
            axis_z: Z component of rotation axis.
            angle: Rotation angle in degrees.
        """
        try:
            shape = require_object(name)
            fr = caid.rotate(shape, Vector(0, 0, 0), Vector(axis_x, axis_y, axis_z), angle)
            msg = format_result(fr, f"Rotated '{name}' by {angle} deg around ({axis_x}, {axis_y}, {axis_z})")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def scale_object(name: str, factor: float) -> str:
        """Uniformly scale an object.

        Args:
            name: Name of existing object.
            factor: Scale factor (e.g., 2.0 = double size, 0.5 = half size).
        """
        try:
            shape = require_object(name)
            fr = caid.scale(shape, factor)
            msg = format_result(fr, f"Scaled '{name}' by factor {factor}")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def mirror_object(name: str, new_name: str, plane: str = "YZ") -> str:
        """Mirror (reflect) an object across a plane, creating a new object.

        Args:
            name: Name of the source object.
            new_name: Name for the mirrored copy.
            plane: Mirror plane — "YZ" (across X), "XZ" (across Y), or "XY" (across Z).
        """
        try:
            shape = require_object(name)
            normal_map = {
                "YZ": Vector(1, 0, 0),
                "XZ": Vector(0, 1, 0),
                "XY": Vector(0, 0, 1),
            }
            normal = normal_map.get(plane.upper())
            if normal is None:
                return f"FAIL Unknown plane '{plane}'. Use YZ, XZ, or XY."
            fr = caid.mirror(shape, Vector(0, 0, 0), normal)
            msg = format_result(fr, f"Mirrored '{name}' across {plane} -> '{new_name}'")
            if fr.shape is not None:
                store_object(new_name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    # ========================== ORIENT / ALIGN / DISTRIBUTE ====================

    @mcp.tool()
    def orient_object(
        name: str,
        from_points: str,
        to_points: str,
        result_name: Optional[str] = None,
    ) -> str:
        """Move and rotate an object by mapping reference points to target points.

        - 1 point pair: translation only.
        - 2 point pairs: translation + rotation (aligns the from-vector to the to-vector).
        - 3 point pairs: full orientation (translation + rotation to match a plane).

        Args:
            name: Name of the object to orient.
            from_points: JSON array of source points, e.g. '[[0,0,0],[10,0,0]]'.
            to_points: JSON array of target points, same length as from_points.
            result_name: Name for the result (default: overwrites the original).
        """
        try:
            shape = require_object(name)
            raw = _unwrap(shape)

            fps = parse_points(from_points)
            tps = parse_points(to_points)
            if len(fps) != len(tps) or len(fps) < 1 or len(fps) > 3:
                return "FAIL from_points and to_points must have 1, 2, or 3 point pairs."

            trsf = gp_Trsf()

            if len(fps) == 1:
                # Pure translation
                dx = tps[0][0] - fps[0][0]
                dy = tps[0][1] - fps[0][1]
                dz = tps[0][2] - fps[0][2]
                trsf.SetTranslation(gp_Vec(dx, dy, dz))

            elif len(fps) == 2:
                # Translation + rotation: align vector (from[0]->from[1]) to (to[0]->to[1])
                # Step 1: translate from[0] to to[0]
                dx = tps[0][0] - fps[0][0]
                dy = tps[0][1] - fps[0][1]
                dz = tps[0][2] - fps[0][2]
                t1 = gp_Trsf()
                t1.SetTranslation(gp_Vec(dx, dy, dz))

                # Step 2: rotate vector
                v_from = gp_Vec(
                    fps[1][0] - fps[0][0],
                    fps[1][1] - fps[0][1],
                    fps[1][2] - fps[0][2],
                )
                v_to = gp_Vec(
                    tps[1][0] - tps[0][0],
                    tps[1][1] - tps[0][1],
                    tps[1][2] - tps[0][2],
                )

                # Check if vectors are parallel
                cross = gp_Vec(v_from)
                cross.Cross(v_to)
                if cross.Magnitude() < 1e-10:
                    # Vectors are parallel — check if same or opposite direction
                    if v_from.Dot(v_to) < 0:
                        # 180 degree rotation — pick an arbitrary perpendicular axis
                        if abs(v_from.X()) < 0.9:
                            perp = gp_Vec(1, 0, 0)
                        else:
                            perp = gp_Vec(0, 1, 0)
                        cross = gp_Vec(v_from)
                        cross.Cross(perp)
                        t2 = gp_Trsf()
                        axis = gp_Ax1(gp_Pnt(tps[0][0], tps[0][1], tps[0][2]),
                                       gp_Dir(cross.X(), cross.Y(), cross.Z()))
                        t2.SetRotation(axis, math.pi)
                        trsf = t2.Multiplied(t1)
                    else:
                        trsf = t1
                else:
                    angle = v_from.Angle(v_to)
                    t2 = gp_Trsf()
                    axis = gp_Ax1(gp_Pnt(tps[0][0], tps[0][1], tps[0][2]),
                                   gp_Dir(cross.X(), cross.Y(), cross.Z()))
                    t2.SetRotation(axis, angle)
                    trsf = t2.Multiplied(t1)

            else:
                # 3 point pairs: full orientation
                # Compute plane normals from 3 points, then align
                def plane_normal(pts):
                    v1 = gp_Vec(pts[1][0]-pts[0][0], pts[1][1]-pts[0][1], pts[1][2]-pts[0][2])
                    v2 = gp_Vec(pts[2][0]-pts[0][0], pts[2][1]-pts[0][1], pts[2][2]-pts[0][2])
                    n = gp_Vec(v1)
                    n.Cross(v2)
                    if n.Magnitude() < 1e-10:
                        return None
                    n.Normalize()
                    return n

                # First do 2-point orient (translation + primary axis rotation)
                dx = tps[0][0] - fps[0][0]
                dy = tps[0][1] - fps[0][1]
                dz = tps[0][2] - fps[0][2]
                t1 = gp_Trsf()
                t1.SetTranslation(gp_Vec(dx, dy, dz))

                v_from = gp_Vec(fps[1][0]-fps[0][0], fps[1][1]-fps[0][1], fps[1][2]-fps[0][2])
                v_to = gp_Vec(tps[1][0]-tps[0][0], tps[1][1]-tps[0][1], tps[1][2]-tps[0][2])

                cross = gp_Vec(v_from)
                cross.Cross(v_to)
                if cross.Magnitude() > 1e-10:
                    angle = v_from.Angle(v_to)
                    t2 = gp_Trsf()
                    axis = gp_Ax1(gp_Pnt(tps[0][0], tps[0][1], tps[0][2]),
                                   gp_Dir(cross.X(), cross.Y(), cross.Z()))
                    t2.SetRotation(axis, angle)
                    trsf_2pt = t2.Multiplied(t1)
                else:
                    trsf_2pt = t1

                # Apply 2-point transform to from[2] to see where it lands
                p2_from = gp_Pnt(fps[2][0], fps[2][1], fps[2][2])
                p2_transformed = p2_from.Transformed(trsf_2pt)
                p2_target = gp_Pnt(tps[2][0], tps[2][1], tps[2][2])

                # Rotate around the primary axis to bring the third point into place
                v_primary = gp_Vec(tps[1][0]-tps[0][0], tps[1][1]-tps[0][1], tps[1][2]-tps[0][2])
                v_cur = gp_Vec(p2_transformed.X()-tps[0][0], p2_transformed.Y()-tps[0][1], p2_transformed.Z()-tps[0][2])
                v_tgt = gp_Vec(p2_target.X()-tps[0][0], p2_target.Y()-tps[0][1], p2_target.Z()-tps[0][2])

                # Project both onto plane perpendicular to primary axis
                if v_primary.Magnitude() > 1e-10:
                    v_primary_n = gp_Vec(v_primary)
                    v_primary_n.Normalize()

                    proj_cur = gp_Vec(v_cur)
                    proj_cur.Subtract(gp_Vec(v_primary_n).Multiplied(v_cur.Dot(v_primary_n)))
                    proj_tgt = gp_Vec(v_tgt)
                    proj_tgt.Subtract(gp_Vec(v_primary_n).Multiplied(v_tgt.Dot(v_primary_n)))

                    if proj_cur.Magnitude() > 1e-10 and proj_tgt.Magnitude() > 1e-10:
                        twist_angle = proj_cur.AngleWithRef(proj_tgt, v_primary_n)
                        t3 = gp_Trsf()
                        axis3 = gp_Ax1(gp_Pnt(tps[0][0], tps[0][1], tps[0][2]),
                                        gp_Dir(v_primary_n.X(), v_primary_n.Y(), v_primary_n.Z()))
                        t3.SetRotation(axis3, twist_angle)
                        trsf = t3.Multiplied(trsf_2pt)
                    else:
                        trsf = trsf_2pt
                else:
                    trsf = trsf_2pt

            transformer = BRepBuilderAPI_Transform(raw, trsf, True)
            transformer.Build()
            if not transformer.IsDone():
                return "FAIL Orientation transform failed."
            result = transformer.Shape()

            out_name = result_name or name
            vol = shape_volume(result)
            area = shape_area(result)
            fr = ForgeResult(shape=result, valid=True, volume_after=vol, surface_area=area)
            store_object(out_name, result)

            n_pts = len(fps)
            mode = {1: "translation", 2: "translation + rotation", 3: "full orientation"}[n_pts]
            return format_result(fr, f"Oriented '{name}' -> '{out_name}' ({mode}, {n_pts} point pairs)")
        except (json.JSONDecodeError, ValueError) as e:
            return f"FAIL Invalid points format: {e}. Accept JSON arrays, dicts, or comma-separated strings."
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def align_objects(
        names: str,
        axis: str = "X",
        alignment: str = "center",
    ) -> str:
        """Align multiple objects along an axis.

        All objects are moved so their bounding boxes line up on the specified
        axis at the chosen alignment point (min, center, or max).

        Args:
            names: JSON array of object names, e.g. '["bracket", "plate", "bolt"]'.
            axis: Axis to align on — "X", "Y", or "Z".
            alignment: Where to align — "min", "center", or "max".
        """
        try:
            obj_names = json.loads(names)
            if len(obj_names) < 2:
                return "FAIL Need at least 2 objects to align."

            axis = axis.upper()
            if axis not in ("X", "Y", "Z"):
                return "FAIL axis must be 'X', 'Y', or 'Z'."
            alignment = alignment.lower()
            if alignment not in ("min", "center", "max"):
                return "FAIL alignment must be 'min', 'center', or 'max'."

            axis_key = {"X": ("xmin", "xmax"), "Y": ("ymin", "ymax"), "Z": ("zmin", "zmax")}[axis]
            component = {"X": 0, "Y": 1, "Z": 2}[axis]

            # Compute target position
            positions = []
            for n in obj_names:
                bb = shape_bounding_box(require_object(n))
                lo, hi = bb[axis_key[0]], bb[axis_key[1]]
                if alignment == "min":
                    positions.append(lo)
                elif alignment == "max":
                    positions.append(hi)
                else:
                    positions.append((lo + hi) / 2)

            # Align to the average position
            target = sum(positions) / len(positions)

            moved = []
            for i, n in enumerate(obj_names):
                offset = target - positions[i]
                if abs(offset) > 1e-6:
                    shape = require_object(n)
                    vec = [0.0, 0.0, 0.0]
                    vec[component] = offset
                    fr = caid.translate(shape, Vector(*vec))
                    if fr.shape is not None:
                        store_object(n, fr.shape)
                        moved.append(f"'{n}' moved {offset:+.3f} mm")
                    else:
                        moved.append(f"'{n}' FAILED to move")
                else:
                    moved.append(f"'{n}' already aligned")

            return f"OK Aligned {len(obj_names)} objects on {axis} axis ({alignment}):\n" + "\n".join(f"  {m}" for m in moved)
        except json.JSONDecodeError:
            return "FAIL names must be a JSON array, e.g. '[\"a\", \"b\"]'"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def distribute_objects(
        names: str,
        axis: str = "X",
        spacing: Optional[float] = None,
    ) -> str:
        """Evenly distribute objects along an axis.

        Objects are spaced equally based on their bounding box centers.
        If spacing is not provided, objects are distributed evenly between
        the first and last object's current positions.

        Args:
            names: JSON array of object names in desired order,
                  e.g. '["left", "middle", "right"]'.
            axis: Axis to distribute along — "X", "Y", or "Z".
            spacing: Explicit center-to-center spacing in mm.
                    If omitted, auto-computed to fill the span evenly.
        """
        try:
            obj_names = json.loads(names)
            if len(obj_names) < 3 and spacing is None:
                return "FAIL Need at least 3 objects for auto-spacing (or provide explicit spacing with 2+)."
            if len(obj_names) < 2:
                return "FAIL Need at least 2 objects to distribute."

            axis = axis.upper()
            if axis not in ("X", "Y", "Z"):
                return "FAIL axis must be 'X', 'Y', or 'Z'."
            component = {"X": 0, "Y": 1, "Z": 2}[axis]
            axis_key = {"X": ("xmin", "xmax"), "Y": ("ymin", "ymax"), "Z": ("zmin", "zmax")}[axis]

            # Get current center positions along the axis
            centers = []
            for n in obj_names:
                bb = shape_bounding_box(require_object(n))
                centers.append((bb[axis_key[0]] + bb[axis_key[1]]) / 2)

            if spacing is None:
                # Auto: sort by current spatial position, then distribute evenly
                paired = sorted(zip(centers, obj_names), key=lambda x: x[0])
                centers = [c for c, _ in paired]
                obj_names = [n for _, n in paired]

            if spacing is not None:
                # Fixed spacing from the first object's position
                target_positions = [centers[0] + i * spacing for i in range(len(obj_names))]
            else:
                # Auto: evenly distribute between spatial min and max
                span = centers[-1] - centers[0]
                step = span / (len(obj_names) - 1) if len(obj_names) > 1 else 0
                target_positions = [centers[0] + i * step for i in range(len(obj_names))]

            moved = []
            for i, n in enumerate(obj_names):
                offset = target_positions[i] - centers[i]
                if abs(offset) > 1e-6:
                    shape = require_object(n)
                    vec = [0.0, 0.0, 0.0]
                    vec[component] = offset
                    fr = caid.translate(shape, Vector(*vec))
                    if fr.shape is not None:
                        store_object(n, fr.shape)
                        moved.append(f"'{n}' moved {offset:+.3f} mm")
                    else:
                        moved.append(f"'{n}' FAILED to move")
                else:
                    moved.append(f"'{n}' already in position")

            sp = f"{spacing:.2f} mm" if spacing else "auto"
            return f"OK Distributed {len(obj_names)} objects along {axis} (spacing={sp}):\n" + "\n".join(f"  {m}" for m in moved)
        except json.JSONDecodeError:
            return "FAIL names must be a JSON array, e.g. '[\"a\", \"b\", \"c\"]'"
        except Exception as e:
            return f"FAIL Error: {e}"
