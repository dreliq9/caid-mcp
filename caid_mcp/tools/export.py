"""Export tools (STL, STEP) and visual preview (SVG rendering)."""

import tempfile
from typing import Optional
from pathlib import Path

import cadquery as cq
from cadquery import exporters
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import scene, require_object, OUTPUT_DIR, log


def _wrap_for_svg(shape) -> cq.Workplane:
    """Wrap a raw shape in a Workplane for CQ's SVG exporter."""
    return cq.Workplane("XY").add(shape)


def register(mcp: FastMCP) -> None:
    """Register all export and visualization tools."""

    # ========================== VISUAL PREVIEW ================================

    @mcp.tool()
    def preview_object(
        name: str,
        width: int = 600,
        height: int = 400,
        projection: str = "isometric",
    ) -> str:
        """Render an SVG preview of an object so you can see what it looks like.

        Returns the SVG as inline XML text. Use this to visually verify geometry
        before exporting.

        Args:
            name: Name of the object to preview.
            width: Image width in pixels (default 600).
            height: Image height in pixels (default 400).
            projection: View angle: "isometric", "front", "top", or "right".
        """
        try:
            shape = require_object(name)
            wp = _wrap_for_svg(shape)

            proj_map = {
                "isometric": (1, -1, 0.5),
                "front": (0, -1, 0),
                "top": (0, 0, -1),
                "right": (-1, 0, 0),
            }
            proj_dir = proj_map.get(projection, proj_map["isometric"])

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
                svg_content = f.read()
            Path(tmp.name).unlink(missing_ok=True)

            svg_path = OUTPUT_DIR / f"{name}_preview.svg"
            svg_path.write_text(svg_content)

            bb = shape.BoundingBox()
            dims = f"{bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm"

            return (
                f"OK Preview of '{name}' ({dims}, {projection} view):\n"
                f"Saved to: {svg_path}\n\n"
                f"{svg_content}"
            )
        except Exception as e:
            return f"FAIL Error rendering preview: {e}"

    @mcp.tool()
    def preview_scene(
        width: int = 800,
        height: int = 500,
    ) -> str:
        """Render an SVG preview of ALL objects in the scene combined.

        Args:
            width: Image width in pixels.
            height: Image height in pixels.
        """
        if not scene:
            return "Scene is empty — nothing to preview."
        try:
            shapes = list(scene.values())
            combined = shapes[0]
            for s in shapes[1:]:
                try:
                    fr = caid.boolean_union(combined, s)
                    if fr.shape is not None:
                        combined = fr.shape
                except Exception:
                    pass

            wp = _wrap_for_svg(combined)

            tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
            tmp.close()
            exporters.export(
                wp, tmp.name,
                exportType=exporters.ExportTypes.SVG,
                opt={
                    "width": width,
                    "height": height,
                    "projectionDir": (1, -1, 0.5),
                    "showAxes": False,
                },
            )
            with open(tmp.name) as f:
                svg_content = f.read()
            Path(tmp.name).unlink(missing_ok=True)

            svg_path = OUTPUT_DIR / "scene_preview.svg"
            svg_path.write_text(svg_content)

            return (
                f"OK Scene preview ({len(scene)} objects):\n"
                f"Saved to: {svg_path}\n\n"
                f"{svg_content}"
            )
        except Exception as e:
            return f"FAIL Error rendering scene preview: {e}"

    # ========================== STL EXPORT ====================================

    @mcp.tool()
    def export_stl(
        name: str,
        filename: Optional[str] = None,
        tolerance: float = 0.1,
        angular_tolerance: float = 0.1,
    ) -> str:
        """Export an object as an STL file for 3D printing.

        Args:
            name: Name of the object to export.
            filename: Output filename (default: {name}.stl).
            tolerance: Linear tolerance for mesh quality (mm).
            angular_tolerance: Angular tolerance (radians).
        """
        try:
            shape = require_object(name)
            fname = filename or f"{name}.stl"
            if not fname.endswith(".stl"):
                fname += ".stl"
            path = OUTPUT_DIR / fname
            fr = caid.to_stl(shape, path, tolerance=tolerance, angular_tolerance=angular_tolerance)
            if fr.valid:
                size_kb = path.stat().st_size / 1024
                return f"OK Exported STL: {path}  ({size_kb:.1f} KB)"
            return f"FAIL STL export: {fr.diagnostics.get('reason', 'unknown')}"
        except Exception as e:
            return f"FAIL Error exporting STL: {e}"

    @mcp.tool()
    def export_step(name: str, filename: Optional[str] = None) -> str:
        """Export an object as a STEP file (lossless CAD interchange format).

        Args:
            name: Name of the object to export.
            filename: Output filename (default: {name}.step).
        """
        try:
            shape = require_object(name)
            fname = filename or f"{name}.step"
            if not fname.endswith(".step"):
                fname += ".step"
            path = OUTPUT_DIR / fname
            fr = caid.to_step(shape, path)
            if fr.valid:
                size_kb = path.stat().st_size / 1024
                return f"OK Exported STEP: {path}  ({size_kb:.1f} KB)"
            return f"FAIL STEP export: {fr.diagnostics.get('reason', 'unknown')}"
        except Exception as e:
            return f"FAIL Error exporting STEP: {e}"

    @mcp.tool()
    def export_all_stl(tolerance: float = 0.1) -> str:
        """Export every object in the scene as a separate STL file.

        Args:
            tolerance: Linear mesh tolerance (mm).
        """
        if not scene:
            return "Scene is empty — nothing to export."
        results = []
        for obj_name, shape in scene.items():
            try:
                path = OUTPUT_DIR / f"{obj_name}.stl"
                fr = caid.to_stl(shape, path, tolerance=tolerance)
                if fr.valid:
                    size_kb = path.stat().st_size / 1024
                    results.append(f"  OK {path.name}  ({size_kb:.1f} KB)")
                else:
                    results.append(f"  FAIL {obj_name}: {fr.diagnostics.get('reason', '?')}")
            except Exception as e:
                results.append(f"  FAIL {obj_name}: {e}")
        return f"Exported {len(results)} files to {OUTPUT_DIR}:\n" + "\n".join(results)
