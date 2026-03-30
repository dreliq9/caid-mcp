"""Export tools (STL, STEP), visual preview (PNG render), and shaded PNG rendering."""

import hashlib
import tempfile
from typing import Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP
import caid
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from OCP.BRepTools import BRepTools

from caid_mcp.core import (
    scene, require_object, OUTPUT_DIR, log, shape_bounding_box, _unwrap,
    get_object_color, is_object_visible, adaptive_compress_png,
)


# ---------------------------------------------------------------------------
# Quality presets — LLMs pick strings better than numeric tolerances
# ---------------------------------------------------------------------------

_QUALITY_PRESETS = {
    "draft":  {"tolerance": 0.5, "angular_tolerance": 0.5},
    "normal": {"tolerance": 0.2, "angular_tolerance": 0.2},
    "high":   {"tolerance": 0.05, "angular_tolerance": 0.05},
}


def _resolve_tolerance(
    quality: Optional[str],
    tolerance: Optional[float],
    angular_tolerance: Optional[float] = None,
) -> tuple[float, float]:
    """Resolve quality preset and explicit tolerance into (linear, angular).

    Explicit tolerance always wins. If neither is given, defaults to 'normal'.
    """
    if tolerance is not None:
        ang = angular_tolerance if angular_tolerance is not None else tolerance
        return (tolerance, ang)
    preset = _QUALITY_PRESETS.get(quality or "normal", _QUALITY_PRESETS["normal"])
    return (preset["tolerance"], preset["angular_tolerance"])


# ---------------------------------------------------------------------------
# Compare renders — before/after snapshot store
# ---------------------------------------------------------------------------

_compare_snapshots: dict[str, Path] = {}  # key = "name::label" → PNG path


# ---------------------------------------------------------------------------
# Render cache — SHA-256 keyed, LRU eviction at 500 MB
# ---------------------------------------------------------------------------

_RENDER_CACHE_DIR = OUTPUT_DIR / ".render_cache"
_RENDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_RENDER_CACHE_MAX_BYTES = 500 * 1024 * 1024  # 500 MB


def _shape_brep_bytes(shape) -> bytes:
    """Serialize an OCP shape to BREP bytes for hashing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".brep", delete=False)
    tmp.close()
    try:
        BRepTools.Write_s(_unwrap(shape), tmp.name)
        return Path(tmp.name).read_bytes()
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _render_cache_key(brep_bytes: bytes, view: str, width: int, height: int,
                      color: str, tolerance: float) -> str:
    """Compute SHA-256 cache key from shape BREP + render parameters."""
    h = hashlib.sha256()
    h.update(brep_bytes)
    h.update(f"{view}|{width}|{height}|{color}|{tolerance}".encode())
    return h.hexdigest()


def _render_cache_get(cache_key: str) -> Optional[Path]:
    """Return cached PNG path if it exists, updating its access time."""
    cached = _RENDER_CACHE_DIR / f"{cache_key}.png"
    if cached.exists():
        cached.touch()  # update mtime for LRU
        return cached
    return None


def _render_cache_put(cache_key: str, src_path: Path) -> Path:
    """Copy a rendered PNG into the cache, evicting old entries if needed."""
    import shutil
    dest = _RENDER_CACHE_DIR / f"{cache_key}.png"
    shutil.copy2(str(src_path), str(dest))
    _render_cache_evict()
    return dest


def _render_cache_evict() -> None:
    """Evict oldest cached renders if total size exceeds the limit."""
    try:
        files = list(_RENDER_CACHE_DIR.glob("*.png"))
        total = sum(f.stat().st_size for f in files)
        if total <= _RENDER_CACHE_MAX_BYTES:
            return
        # Sort by mtime ascending (oldest first)
        files.sort(key=lambda f: f.stat().st_mtime)
        for f in files:
            if total <= _RENDER_CACHE_MAX_BYTES * 0.8:  # evict down to 80%
                break
            sz = f.stat().st_size
            f.unlink(missing_ok=True)
            total -= sz
            log.info("Render cache evicted: %s (%d KB)", f.name, sz // 1024)
    except Exception as e:
        log.warning("Render cache eviction error: %s", e)


def _shape_to_trimesh(shape, tolerance: float = 0.1) -> trimesh.Trimesh:
    """Tessellate an OCP shape to a trimesh mesh via temp STL."""
    raw = _unwrap(shape)
    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    try:
        fr = caid.to_stl(raw, tmp.name, tolerance=tolerance)
        if not fr.valid:
            raise RuntimeError(f"STL tessellation failed: {fr.diagnostics.get('reason', 'unknown')}")
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

    # ========================== SHADED PNG RENDER ==============================

    @mcp.tool()
    def render_object(
        name: str,
        view: str = "iso",
        width: int = 800,
        height: int = 600,
        color: str = "#4a90d9",
        quality: Optional[str] = None,
        tolerance: Optional[float] = None,
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
            quality: Mesh quality preset — "draft" (fast), "normal" (default),
                    or "high" (smooth). Overridden by explicit tolerance.
            tolerance: Mesh tolerance in mm — lower = smoother. Overrides quality.
        """
        try:
            tol, _ = _resolve_tolerance(quality, tolerance)
            shape = require_object(name)

            bb = shape_bounding_box(shape)
            dims = f"{bb['xlen']:.1f} x {bb['ylen']:.1f} x {bb['zlen']:.1f} mm"

            # Check render cache
            brep_bytes = _shape_brep_bytes(shape)
            cache_key = _render_cache_key(brep_bytes, view, width, height, color, tol)
            cached = _render_cache_get(cache_key)
            if cached:
                import shutil
                png_path = OUTPUT_DIR / f"{name}_render_{view}.png"
                shutil.copy2(str(cached), str(png_path))
                size_kb = png_path.stat().st_size / 1024
                return (
                    f"OK Rendered '{name}' ({dims}, {view} view) -> {png_path} ({size_kb:.1f} KB) [cached]\n"
                    f"Use Read tool on {png_path} to view the image."
                )

            mesh = _shape_to_trimesh(shape, tolerance=tol)

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

            _render_cache_put(cache_key, png_path)
            adaptive_compress_png(png_path)

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
        quality: Optional[str] = None,
        tolerance: Optional[float] = None,
    ) -> str:
        """Render a shaded PNG of ALL objects in the scene. Each object gets a
        different color for easy identification.

        Args:
            view: Camera preset — "iso", "front", "top", "right", "back", "left",
                  "bottom", or "multi" (2x2 grid).
            width: Image width in pixels.
            height: Image height in pixels.
            quality: Mesh quality preset — "draft" (fast), "normal" (default),
                    or "high" (smooth). Overridden by explicit tolerance.
            tolerance: Mesh tolerance in mm. Overrides quality.
        """
        if not scene:
            return "Scene is empty — nothing to render."
        try:
            tol, _ = _resolve_tolerance(quality, tolerance)
            palette = [
                "#4a90d9", "#e74c3c", "#2ecc71", "#f39c12",
                "#9b59b6", "#1abc9c", "#e67e22", "#3498db",
            ]
            meshes_and_colors = []
            palette_idx = 0
            for obj_name, shape in scene.items():
                if not is_object_visible(obj_name):
                    continue
                mesh = _shape_to_trimesh(shape, tolerance=tol)
                obj_color = get_object_color(obj_name) or palette[palette_idx % len(palette)]
                meshes_and_colors.append((mesh, obj_color, obj_name))
                palette_idx += 1

            if not meshes_and_colors:
                return "All objects are hidden — nothing to render."

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
            adaptive_compress_png(png_path)

            size_kb = png_path.stat().st_size / 1024
            obj_list = ", ".join(n for _, _, n in meshes_and_colors)
            return (
                f"OK Scene render ({len(meshes_and_colors)} objects: {obj_list}, {view} view) -> {png_path} ({size_kb:.1f} KB)\n"
                f"Use Read tool on {png_path} to view the image."
            )
        except Exception as e:
            return f"FAIL Error rendering scene: {e}"

    # ========================== COMPARE RENDERS ================================

    @mcp.tool()
    def compare_renders(
        name: str,
        label: str,
        view: str = "iso",
        width: int = 800,
        height: int = 600,
        color: str = "#4a90d9",
        quality: Optional[str] = None,
        tolerance: Optional[float] = None,
    ) -> str:
        """Take a before/after snapshot of an object for visual comparison.

        Call TWICE with the same name + label:
        1. First call: saves a "before" render and returns confirmation.
        2. Second call (after modifications): renders "after" and returns a
           side-by-side composite image for visual diff.

        Args:
            name: Name of the object to snapshot.
            label: A label for this comparison (e.g. "fillet_test").
                  The before/after pair is keyed by name + label.
            view: Camera preset — "iso", "front", "top", "right", etc.
            width: Image width in pixels (per panel, composite is 2x wide).
            height: Image height in pixels.
            color: Face color as hex string.
            quality: Mesh quality preset — "draft", "normal", or "high".
            tolerance: Explicit mesh tolerance (overrides quality).
        """
        try:
            tol, _ = _resolve_tolerance(quality, tolerance)
            shape = require_object(name)
            mesh = _shape_to_trimesh(shape, tolerance=tol)
            elev, azim = _VIEW_ANGLES.get(view, _VIEW_ANGLES["iso"])

            snap_key = f"{name}::{label}"

            if snap_key not in _compare_snapshots:
                # First call — save "before"
                before_path = OUTPUT_DIR / f"{name}_compare_{label}_before.png"
                _render_mesh_to_png(
                    mesh, before_path,
                    width=width, height=height,
                    elev=elev, azim=azim, color=color,
                )
                _compare_snapshots[snap_key] = before_path
                return (
                    f"OK Saved 'before' snapshot for '{name}' (label='{label}') -> {before_path}\n"
                    f"Now modify the object and call compare_renders again with the same name and label."
                )
            else:
                # Second call — render "after" and composite
                before_path = _compare_snapshots.pop(snap_key)

                after_path = OUTPUT_DIR / f"{name}_compare_{label}_after.png"
                _render_mesh_to_png(
                    mesh, after_path,
                    width=width, height=height,
                    elev=elev, azim=azim, color=color,
                )

                # Composite side-by-side using matplotlib
                from PIL import Image
                try:
                    img_before = Image.open(str(before_path))
                    img_after = Image.open(str(after_path))
                except Exception:
                    return (
                        f"OK After render saved to {after_path} but could not load "
                        f"before image at {before_path} for compositing. "
                        f"Compare manually using Read tool on both files."
                    )

                # Normalize sizes
                max_h = max(img_before.height, img_after.height)
                composite = Image.new("RGB", (img_before.width + img_after.width + 4, max_h + 30), "white")

                # Add labels
                from PIL import ImageDraw
                draw = ImageDraw.Draw(composite)
                draw.text((img_before.width // 2 - 20, 2), "BEFORE", fill="black")
                draw.text((img_before.width + 4 + img_after.width // 2 - 16, 2), "AFTER", fill="black")

                composite.paste(img_before, (0, 28))
                composite.paste(img_after, (img_before.width + 4, 28))

                comp_path = OUTPUT_DIR / f"{name}_compare_{label}.png"
                composite.save(str(comp_path))

                size_kb = comp_path.stat().st_size / 1024
                return (
                    f"OK Before/after comparison for '{name}' (label='{label}') -> {comp_path} ({size_kb:.1f} KB)\n"
                    f"Use Read tool on {comp_path} to view the side-by-side diff."
                )
        except Exception as e:
            return f"FAIL Error: {e}"

    # ========================== STL EXPORT ====================================

    @mcp.tool()
    def export_stl(
        name: Optional[str] = None,
        filename: Optional[str] = None,
        quality: Optional[str] = None,
        tolerance: Optional[float] = None,
        angular_tolerance: Optional[float] = None,
    ) -> str:
        """Export object(s) as STL files for 3D printing.

        If name is provided, exports that single object.
        If name is omitted, exports ALL objects in the scene as separate STL files.

        Args:
            name: Object to export. Omit to export all objects.
            filename: Output filename (default: {name}.stl). Only used for single export.
            quality: Mesh quality preset — "draft" (fast/coarse), "normal" (default),
                    or "high" (smooth/fine). Overridden by explicit tolerance.
            tolerance: Linear tolerance for mesh quality (mm). Overrides quality.
            angular_tolerance: Angular tolerance (radians). Overrides quality.
        """
        try:
            tol, ang_tol = _resolve_tolerance(quality, tolerance, angular_tolerance)

            if name is not None:
                # Single object export
                shape = require_object(name)
                fname = filename or f"{name}.stl"
                if not fname.endswith(".stl"):
                    fname += ".stl"
                path = OUTPUT_DIR / fname
                fr = caid.to_stl(shape, path, tolerance=tol, angular_tolerance=ang_tol)
                if fr.valid:
                    size_kb = path.stat().st_size / 1024
                    return f"OK Exported STL: {path}  ({size_kb:.1f} KB)"
                return f"FAIL STL export: {fr.diagnostics.get('reason', 'unknown')}"
            else:
                # Export all objects
                if not scene:
                    return "Scene is empty — nothing to export."
                results = []
                for obj_name, shape in scene.items():
                    try:
                        path = OUTPUT_DIR / f"{obj_name}.stl"
                        fr = caid.to_stl(shape, path, tolerance=tol, angular_tolerance=ang_tol)
                        if fr.valid:
                            size_kb = path.stat().st_size / 1024
                            results.append(f"  OK {path.name}  ({size_kb:.1f} KB)")
                        else:
                            results.append(f"  FAIL {obj_name}: {fr.diagnostics.get('reason', '?')}")
                    except Exception as e:
                        results.append(f"  FAIL {obj_name}: {e}")
                return f"Exported {len(results)} files to {OUTPUT_DIR}:\n" + "\n".join(results)
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
    def export_brep(name: str, filename: Optional[str] = None) -> str:
        """Export an object as a BREP file (native OCCT format, lossless, fastest).

        BREP is the native OpenCascade format — fastest to read/write, lossless,
        but only readable by OCCT-based tools. Use STEP for interchange with
        other CAD software, STL for 3D printing.

        Args:
            name: Name of the object to export.
            filename: Output filename (default: {name}.brep).
        """
        try:
            shape = require_object(name)
            fname = filename or f"{name}.brep"
            if not fname.endswith(".brep"):
                fname += ".brep"
            path = OUTPUT_DIR / fname
            fr = caid.to_brep(shape, path)
            if fr.valid:
                size_kb = path.stat().st_size / 1024
                return f"OK Exported BREP: {path}  ({size_kb:.1f} KB)"
            return f"FAIL BREP export: {fr.diagnostics.get('reason', 'unknown')}"
        except Exception as e:
            return f"FAIL Error exporting BREP: {e}"
