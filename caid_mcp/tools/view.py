"""Section and exploded view tools for inspecting geometry."""

import json
import tempfile
from typing import Optional
from pathlib import Path

import cadquery as cq
from cadquery import exporters
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from mcp.server.fastmcp import FastMCP
from caid_mcp.core import scene, require_object, store_object, assemblies, OUTPUT_DIR


def _render_svg(shape, name_prefix, projection="isometric", width=600, height=400):
    """Render a shape to SVG, save to output dir, return SVG text."""
    proj_map = {
        "isometric": (1, -1, 0.5),
        "front": (0, -1, 0),
        "top": (0, 0, -1),
        "right": (-1, 0, 0),
    }
    proj_dir = proj_map.get(projection, proj_map["isometric"])
    wp = cq.Workplane("XY").add(shape)

    tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    tmp.close()
    exporters.export(
        wp, tmp.name,
        exportType=exporters.ExportTypes.SVG,
        opt={
            "width": width,
            "height": height,
            "projectionDir": proj_dir,
            "showAxes": False,
            "showHidden": False,
        },
    )
    with open(tmp.name) as f:
        svg = f.read()
    Path(tmp.name).unlink(missing_ok=True)

    svg_path = OUTPUT_DIR / f"{name_prefix}.svg"
    svg_path.write_text(svg)
    return svg, svg_path


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

        Args:
            name: Name of the object to section.
            axis: Cut plane normal axis — "X", "Y", or "Z".
            offset: Position along the axis to place the cutting plane (mm).
                   Default 0.0 cuts through the origin.
            projection: Preview angle: "isometric", "front", "top", or "right".
            keep: Which side to keep — "below" (negative side of axis) or
                 "above" (positive side). Default "below" shows the interior
                 when cutting at the middle.
            save_result: If provided, store the sectioned shape in the scene
                        under this name. Otherwise only generates a preview.
        """
        try:
            shape = require_object(name)

            axis_map = {
                "X": (1, 0, 0),
                "Y": (0, 1, 0),
                "Z": (0, 0, 1),
            }
            normal = axis_map.get(axis.upper())
            if normal is None:
                return f"FAIL Invalid axis '{axis}'. Use X, Y, or Z."

            # Build a large cutting box on the positive side of the plane
            big = 10000
            nx, ny, nz = normal
            origin = (nx * offset, ny * offset, nz * offset)
            cutter = (
                cq.Workplane("XY")
                .box(big, big, big)
                .translate(cq.Vector(
                    nx * big / 2 + origin[0],
                    ny * big / 2 + origin[1],
                    nz * big / 2 + origin[2],
                ))
            ).val()

            # Cut removes the positive side; flip if user wants to keep "above"
            if keep == "above":
                cut_op = BRepAlgoAPI_Cut(shape.wrapped, cutter.wrapped)
                # Actually we need the OTHER half — invert: cut the negative side
                neg_cutter = (
                    cq.Workplane("XY")
                    .box(big, big, big)
                    .translate(cq.Vector(
                        -nx * big / 2 + origin[0],
                        -ny * big / 2 + origin[1],
                        -nz * big / 2 + origin[2],
                    ))
                ).val()
                cut_op = BRepAlgoAPI_Cut(shape.wrapped, neg_cutter.wrapped)
            else:
                cut_op = BRepAlgoAPI_Cut(shape.wrapped, cutter.wrapped)

            section_shape = cq.Shape(cut_op.Shape())
            vol_before = shape.Volume()
            vol_after = section_shape.Volume()

            svg, svg_path = _render_svg(
                section_shape, f"{name}_section_{axis}{offset}", projection
            )

            if save_result:
                store_object(save_result, section_shape)

            bb = shape.BoundingBox()
            dims = f"{bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm"

            result_msg = (
                f"OK Section view of '{name}' ({dims})\n"
                f"Cut: {axis}={offset}mm, keeping {keep} side\n"
                f"Volume: {vol_after:.1f}mm3 (full: {vol_before:.1f}mm3)\n"
                f"Saved to: {svg_path}\n"
            )
            if save_result:
                result_msg += f"Stored as: '{save_result}'\n"

            return result_msg + f"\n{svg}"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def exploded_view(
        assembly_name: str,
        scale: float = 2.0,
        projection: str = "isometric",
    ) -> str:
        """Generate an exploded view of an assembly by pushing parts outward
        from the assembly center.

        Parts are moved along the vector from assembly center to part center,
        scaled by the explosion factor.

        Args:
            assembly_name: Name of the assembly to explode.
            scale: Explosion scale factor. 1.0 = no change, 2.0 = double
                  the distance from center, 3.0 = triple. Default 2.0.
            projection: Preview angle: "isometric", "front", "top", or "right".
        """
        try:
            asm = assemblies.get(assembly_name)
            if asm is None:
                return f"FAIL Assembly '{assembly_name}' not found"

            # Get all parts and their positions
            parts = asm._parts
            if not parts:
                return f"FAIL Assembly '{assembly_name}' has no parts"

            # Compute assembly centroid from part centers
            centers = []
            for part in parts:
                c = part.shape.Center()
                centers.append(cq.Vector(c.x, c.y, c.z))

            centroid = cq.Vector(
                sum(c.x for c in centers) / len(centers),
                sum(c.y for c in centers) / len(centers),
                sum(c.z for c in centers) / len(centers),
            )

            # Move each part outward from centroid
            exploded_shapes = []
            part_info = []
            for part, center in zip(parts, centers):
                offset = center - centroid
                # Scale the offset (scale=1 means no extra movement)
                move = cq.Vector(
                    offset.x * (scale - 1),
                    offset.y * (scale - 1),
                    offset.z * (scale - 1),
                )
                moved = part.shape.move(cq.Location(move))
                exploded_shapes.append(moved)
                part_info.append({
                    "name": part.name,
                    "offset": [round(move.x, 2), round(move.y, 2), round(move.z, 2)],
                })

            # Combine all exploded shapes into a compound for rendering
            compound = cq.Compound.makeCompound(exploded_shapes)

            svg, svg_path = _render_svg(
                compound, f"{assembly_name}_exploded", projection
            )

            result = (
                f"OK Exploded view of assembly '{assembly_name}' "
                f"({len(parts)} parts, scale={scale}x)\n"
                f"Saved to: {svg_path}\n"
                f"Parts:\n"
            )
            for pi in part_info:
                result += f"  - {pi['name']}: offset {pi['offset']}\n"

            return result + f"\n{svg}"
        except Exception as e:
            return f"FAIL Error: {e}"
