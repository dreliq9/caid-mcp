"""Export tools (STL, STEP), visual preview (SVG), and shaded PNG rendering."""

import tempfile
from typing import Optional
from pathlib import Path

from build123d import ExportSVG, export_stl as b123d_export_stl, Axis
from mcp.server.fastmcp import FastMCP
import caid
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from caid_mcp.core import scene, require_object, OUTPUT_DIR, log


# Rotation angles to orient a shape so its XY projection matches the desired view.
# Each entry is a sequence of (Axis, degrees) rotations applied in order.
_SVG_VIEW_ROTATIONS = {
    "isometric": [(Axis.X, -35.264), (Axis.Z, 45)],
    "front":     [],                          # looking down -Y → XY projection as-is
    "top":       [(Axis.X, 90)],              # look down -Z → rotate X+90
    "right":     [(Axis.Z, -90)],             # look down -X → rotate Z-90
}


def _orient_for_svg(shape, projection: str = "isometric"):
    """Rotate a shape so that its XY projection corresponds to the named view."""
    rotations = _SVG_VIEW_ROTATIONS.get(projection, _SVG_VIEW_ROTATIONS["isometric"])
    oriented = shape
    for axis, degrees in rotations:
        oriented = oriented.rotate(axis, degrees)
    return oriented


def _export_svg_string(shape, projection: str = "isometric") -> str:
    """Export a shape to SVG string via build123d ExportSVG."""
    oriented = _orient_for_svg(shape, projection)
    svg = ExportSVG(margin=2)
    svg.add_layer("default")
    svg.add_shape(oriented, layer="default")
    tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    tmp.close()
    try:
        svg.write(tmp.name)
        with open(tmp.name) as f:
            return f.read()
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _shape_to_trimesh(shape, tolerance: float = 0.1) -> trimesh.Trimesh:
    """Tessellate a build123d shape to a trimesh mesh via temp STL."""
    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    try:
        b123d_export_stl(shape, tmp.name, tolerance=tolerance)
        mesh = trimesh.load(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return mesh


_VIEW_ANGLES = {
    "iso":    (25.0, 135.0),
    "front":  (0.0, 0.0),
    "back":   (0.0, 180.0),
    "top":    (90.0, 0.0),
    "bottom": (-90.0, 0.0),
    "right":  (0.0, 90.0),
    "left":   (0.0, -90.0),
}


def _setup_ax(ax, verts, elev, azim):
    """Auto-scale and orient a 3D axis to fit geometry."""
    center = verts.mean(axis=0)
    max_range = verts.ptp(axis=0).max() / 2 * 1.15
    ax.set_xlim(center[0] - max_range, center[0] + max_range)
    ax.set_ylim(center[1] - max_range, center[1] + max_range)
    ax.set_zlim(center[2] - max_range, center[2] + max_range)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.view_init(elev=elev, azim=azim)


def _add_shaded_mesh(ax, mesh, color):
    """Add a shaded trimesh to a matplotlib 3D axis."""
    from matplotlib.colors import to_rgb
    verts = mesh.vertices
    polygons = verts[mesh.faces]
    normals = mesh.face_normals
    light_dir = np.array([1.0, -1.0, 1.5])
    light_dir = light_dir / np.linalg.norm(light_dir)
    intensity = np.clip(normals @ light_dir, 0.15, 1.0)
    base_rgb = np.array(to_rgb(color))
    face_colors = np.outer(intensity, base_rgb)
    face_colors = np.clip(face_colors, 0, 1)
    face_colors = np.column_stack([face_colors, np.ones(len(face_colors))])
    collection = Poly3DCollection(polygons, linewidth=0.2, edgecolor="#222222")
    collection.set_facecolor(face_colors)
    ax.add_collection3d(collection)


def _render_multiview(
    mesh: trimesh.Trimesh,
    out_path: Path,
    width: int = 800,
    height: int = 600,
    color: str = "#4a90d9",
) -> None:
    """Render a 2x2 grid: iso, front, top, right."""
    fig = plt.figure(figsize=(width / 100, height / 100))
    views = [("Iso", "iso"), ("Front", "front"), ("Top", "top"), ("Right", "right")]
    verts = mesh.vertices

    for i, (label, view_name) in enumerate(views):
        ax = fig.add_subplot(2, 2, i + 1, projection="3d")
        _add_shaded_mesh(ax, mesh, color)
        elev, azim = _VIEW_ANGLES[view_name]
        _setup_ax(ax, verts, elev, azim)
        ax.set_title(label, fontsize=10)

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _render_mesh_to_png(
    mesh: trimesh.Trimesh,
    out_path: Path,
    width: int = 800,
    height: int = 600,
    elev: float = 25.0,
    azim: float = 135.0,
    color: str = "#4a90d9",
) -> None:
    """Render a trimesh to a shaded PNG using matplotlib."""
    fig = plt.figure(figsize=(width / 100, height / 100))
    ax = fig.add_subplot(111, projection="3d")
    _add_shaded_mesh(ax, mesh, color)
    _setup_ax(ax, mesh.vertices, elev, azim)
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


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
            svg_content = _export_svg_string(shape, projection=projection)

            svg_path = OUTPUT_DIR / f"{name}_preview.svg"
            svg_path.write_text(svg_content)

            bb = shape.bounding_box()
            dims = f"{bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm"

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

            svg_content = _export_svg_string(combined, projection="isometric")

            svg_path = OUTPUT_DIR / "scene_preview.svg"
            svg_path.write_text(svg_content)

            return (
                f"OK Scene preview ({len(scene)} objects):\n"
                f"Saved to: {svg_path}\n\n"
                f"{svg_content}"
            )
        except Exception as e:
            return f"FAIL Error rendering scene preview: {e}"

    # ========================== SHADED PNG RENDER ==============================

    @mcp.tool()
    def render_object(
        name: str,
        view: str = "iso",
        width: int = 800,
        height: int = 600,
        color: str = "#4a90d9",
        tolerance: float = 0.1,
    ) -> str:
        """Render a shaded PNG image of an object — much easier to visually verify
        than SVG wireframes, especially for complex geometry.

        The image is saved to the output directory. Use the returned file path
        with the Read tool to view it.

        Args:
            name: Name of the object to render.
            view: Camera preset — "iso", "front", "top", "right", "back", "left",
                  "bottom", or "multi" (2x2 grid of iso+front+top+right).
            width: Image width in pixels (default 800).
            height: Image height in pixels (default 600).
            color: Face color as hex string (default "#4a90d9").
            tolerance: Mesh tolerance in mm — lower = smoother (default 0.1).
        """
        try:
            shape = require_object(name)
            mesh = _shape_to_trimesh(shape, tolerance=tolerance)

            bb = shape.bounding_box()
            dims = f"{bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm"

            if view == "multi":
                png_path = OUTPUT_DIR / f"{name}_render_multi.png"
                _render_multiview(mesh, png_path, width=width, height=height, color=color)
            else:
                png_path = OUTPUT_DIR / f"{name}_render_{view}.png"
                elev, azim = _VIEW_ANGLES.get(view, _VIEW_ANGLES["iso"])
                _render_mesh_to_png(
                    mesh, png_path,
                    width=width, height=height,
                    elev=elev, azim=azim, color=color,
                )

            size_kb = png_path.stat().st_size / 1024
            return (
                f"OK Rendered '{name}' ({dims}, {view} view) -> {png_path} ({size_kb:.1f} KB)\n"
                f"Use Read tool on {png_path} to view the image."
            )
        except Exception as e:
            return f"FAIL Error rendering: {e}"

    @mcp.tool()
    def render_scene(
        view: str = "iso",
        width: int = 800,
        height: int = 600,
        tolerance: float = 0.1,
    ) -> str:
        """Render a shaded PNG of ALL objects in the scene. Each object gets a
        different color for easy identification.

        Args:
            view: Camera preset — "iso", "front", "top", "right", "back", "left",
                  "bottom", or "multi" (2x2 grid).
            width: Image width in pixels.
            height: Image height in pixels.
            tolerance: Mesh tolerance in mm.
        """
        if not scene:
            return "Scene is empty — nothing to render."
        try:
            palette = [
                "#4a90d9", "#e74c3c", "#2ecc71", "#f39c12",
                "#9b59b6", "#1abc9c", "#e67e22", "#3498db",
            ]
            meshes_and_colors = []
            for i, (obj_name, shape) in enumerate(scene.items()):
                mesh = _shape_to_trimesh(shape, tolerance=tolerance)
                meshes_and_colors.append((mesh, palette[i % len(palette)], obj_name))

            if view == "multi":
                fig = plt.figure(figsize=(width / 100, height / 100))
                views = [("Iso", "iso"), ("Front", "front"), ("Top", "top"), ("Right", "right")]
                all_verts = np.vstack([m.vertices for m, _, _ in meshes_and_colors])
                for i, (label, vn) in enumerate(views):
                    ax = fig.add_subplot(2, 2, i + 1, projection="3d")
                    for mesh, hex_color, _ in meshes_and_colors:
                        _add_shaded_mesh(ax, mesh, hex_color)
                    elev, azim = _VIEW_ANGLES[vn]
                    _setup_ax(ax, all_verts, elev, azim)
                    ax.set_title(label, fontsize=10)
                fig.tight_layout()
                png_path = OUTPUT_DIR / "scene_render_multi.png"
            else:
                fig = plt.figure(figsize=(width / 100, height / 100))
                ax = fig.add_subplot(111, projection="3d")
                all_verts_list = []
                for mesh, hex_color, _ in meshes_and_colors:
                    _add_shaded_mesh(ax, mesh, hex_color)
                    all_verts_list.append(mesh.vertices)
                combined = np.vstack(all_verts_list)
                elev, azim = _VIEW_ANGLES.get(view, _VIEW_ANGLES["iso"])
                _setup_ax(ax, combined, elev, azim)
                png_path = OUTPUT_DIR / f"scene_render_{view}.png"

            fig.savefig(str(png_path), dpi=150, bbox_inches="tight", facecolor="white")
            plt.close(fig)

            size_kb = png_path.stat().st_size / 1024
            obj_list = ", ".join(n for _, _, n in meshes_and_colors)
            return (
                f"OK Scene render ({len(scene)} objects: {obj_list}, {view} view) -> {png_path} ({size_kb:.1f} KB)\n"
                f"Use Read tool on {png_path} to view the image."
            )
        except Exception as e:
            return f"FAIL Error rendering scene: {e}"

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
