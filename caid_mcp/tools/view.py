"""Section and exploded view tools for inspecting geometry."""

import json
from typing import Optional
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from mcp.server.fastmcp import FastMCP
import caid
from caid.vector import Vector
from caid_mcp.core import (
    scene, require_object, store_object, assemblies, OUTPUT_DIR,
    shape_volume, shape_bounding_box, shape_center, _unwrap,
)


def _translate_shape(shape, dx, dy, dz):
    """Translate a raw OCP shape by (dx, dy, dz) and return the new shape."""
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(dx, dy, dz))
    moved = BRepBuilderAPI_Transform(shape, trsf, True)
    moved.Build()
    return moved.Shape()


def register(mcp: FastMCP) -> None:
    """Register view tools."""

    @mcp.tool()
    def section_view(
        name: str,
        axis: str = "X",
        offset: float = 0.0,
        projection: str = "isometric",
        keep: str = "below",
        save_result: Optional[str] = None,
    ) -> str:
        """Cut an object with a plane and preview the cross-section.

        Useful for verifying internal features like holes, shells, and pockets.
        After cutting, use render_object on the saved result to see the section.

        Args:
            name: Name of the object to section.
            axis: Cut plane normal axis — "X", "Y", or "Z".
            offset: Position along the axis to place the cutting plane (mm).
                   Default 0.0 cuts through the origin.
            projection: (ignored, kept for API compat) Use render_object for visuals.
            keep: Which side to keep — "below" (negative side of axis) or
                 "above" (positive side). Default "below" shows the interior
                 when cutting at the middle.
            save_result: If provided, store the sectioned shape in the scene
                        under this name. Otherwise stores as '{name}_section'.
        """
        try:
            shape = require_object(name)
            raw = _unwrap(shape)

            axis_map = {
                "X": (1, 0, 0),
                "Y": (0, 1, 0),
                "Z": (0, 0, 1),
            }
            normal = axis_map.get(axis.upper())
            if normal is None:
                return f"FAIL Invalid axis '{axis}'. Use X, Y, or Z."

            # Build a large cutting box on one side of the plane
            big = 10000.0
            nx, ny, nz = normal
            origin_x = nx * offset
            origin_y = ny * offset
            origin_z = nz * offset

            # Box centered at origin, then translated
            cutter_solid = BRepPrimAPI_MakeBox(
                gp_Pnt(-big / 2, -big / 2, -big / 2),
                big, big, big,
            ).Shape()

            if keep == "above":
                # Cut away the negative side: place cutter box on negative side
                cutter = _translate_shape(
                    cutter_solid,
                    -nx * big / 2 + origin_x,
                    -ny * big / 2 + origin_y,
                    -nz * big / 2 + origin_z,
                )
            else:
                # Cut away the positive side: place cutter box on positive side
                cutter = _translate_shape(
                    cutter_solid,
                    nx * big / 2 + origin_x,
                    ny * big / 2 + origin_y,
                    nz * big / 2 + origin_z,
                )

            cut_op = BRepAlgoAPI_Cut(raw, cutter)
            if not cut_op.IsDone():
                return "FAIL Boolean cut failed"
            section_shape = cut_op.Shape()

            vol_before = shape_volume(raw)
            vol_after = shape_volume(section_shape)

            result_name = save_result or f"{name}_section"
            store_object(result_name, section_shape)

            bb = shape_bounding_box(raw)
            dims = f"{bb['xlen']:.1f} x {bb['ylen']:.1f} x {bb['zlen']:.1f} mm"

            result_msg = (
                f"OK Section view of '{name}' ({dims})\n"
                f"Cut: {axis}={offset}mm, keeping {keep} side\n"
                f"Volume: {vol_after:.1f}mm3 (full: {vol_before:.1f}mm3)\n"
                f"Stored as: '{result_name}'\n"
                f"Use render_object('{result_name}') to see the section."
            )
            return result_msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def exploded_view(
        assembly_name: str,
        scale: float = 2.0,
        projection: str = "isometric",
    ) -> str:
        """Generate an exploded view of an assembly by pushing parts outward
        from the assembly center. The result is stored as '{assembly_name}_exploded'.

        Parts are moved along the vector from assembly center to part center,
        scaled by the explosion factor. Use render_object on the result to see it.

        Args:
            assembly_name: Name of the assembly to explode.
            scale: Explosion scale factor. 1.0 = no change, 2.0 = double
                  the distance from center, 3.0 = triple. Default 2.0.
            projection: (ignored, kept for API compat) Use render_object for visuals.
        """
        try:
            asm = assemblies.get(assembly_name)
            if asm is None:
                return f"FAIL Assembly '{assembly_name}' not found"

            parts = asm._parts
            if not parts:
                return f"FAIL Assembly '{assembly_name}' has no parts"

            # Compute assembly centroid from part centers
            centers = []
            for part in parts:
                raw = _unwrap(part.shape)
                cx, cy, cz = shape_center(raw)
                centers.append((cx, cy, cz))

            centroid_x = sum(c[0] for c in centers) / len(centers)
            centroid_y = sum(c[1] for c in centers) / len(centers)
            centroid_z = sum(c[2] for c in centers) / len(centers)

            # Move each part outward from centroid
            exploded_shapes = []
            part_info = []
            for part, (cx, cy, cz) in zip(parts, centers):
                raw = _unwrap(part.shape)
                ox = cx - centroid_x
                oy = cy - centroid_y
                oz = cz - centroid_z
                # Scale the offset (scale=1 means no extra movement)
                mx = ox * (scale - 1)
                my = oy * (scale - 1)
                mz = oz * (scale - 1)
                moved = _translate_shape(raw, mx, my, mz)
                exploded_shapes.append(moved)
                part_info.append({
                    "name": part.name,
                    "offset": [round(mx, 2), round(my, 2), round(mz, 2)],
                })

            # Combine all exploded shapes into a compound
            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)
            for s in exploded_shapes:
                builder.Add(compound, s)

            result_name = f"{assembly_name}_exploded"
            store_object(result_name, compound)

            result = (
                f"OK Exploded view of assembly '{assembly_name}' "
                f"({len(parts)} parts, scale={scale}x)\n"
                f"Stored as: '{result_name}'\n"
                f"Use render_object('{result_name}') to see the exploded view.\n"
                f"Parts:\n"
            )
            for pi in part_info:
                result += f"  - {pi['name']}: offset {pi['offset']}\n"

            return result
        except Exception as e:
            return f"FAIL Error: {e}"
