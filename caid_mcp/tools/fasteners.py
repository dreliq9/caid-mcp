"""Fastener and thread library — standard metric hardware for mechanical design."""

import math
from typing import Optional
from build123d import (
    BuildPart, BuildSketch, RegularPolygon, extrude,
    Solid, Vector,
)
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import store_object, require_object


# ---------------------------------------------------------------------------
# ISO metric fastener data (dimensions in mm)
# Source: ISO 4017 (hex bolts), ISO 4032 (hex nuts), ISO 7089 (plain washers)
# ---------------------------------------------------------------------------

METRIC_BOLT = {
    # size: (thread_pitch, head_across_flats, head_height, thread_minor_dia)
    "M2":   (0.40, 4.0,  1.4, 1.567),
    "M2.5": (0.45, 5.0,  1.7, 2.013),
    "M3":   (0.50, 5.5,  2.0, 2.459),
    "M4":   (0.70, 7.0,  2.8, 3.242),
    "M5":   (0.80, 8.0,  3.5, 4.134),
    "M6":   (1.00, 10.0, 4.0, 4.917),
    "M8":   (1.25, 13.0, 5.3, 6.647),
    "M10":  (1.50, 16.0, 6.4, 8.376),
    "M12":  (1.75, 18.0, 7.5, 10.106),
    "M14":  (2.00, 21.0, 8.8, 11.835),
    "M16":  (2.00, 24.0, 10.0, 13.835),
    "M20":  (2.50, 30.0, 12.5, 17.294),
    "M24":  (3.00, 36.0, 15.0, 20.752),
}

METRIC_NUT = {
    # size: (across_flats, height)
    "M2":   (4.0,  1.6),
    "M2.5": (5.0,  2.0),
    "M3":   (5.5,  2.4),
    "M4":   (7.0,  3.2),
    "M5":   (8.0,  4.7),
    "M6":   (10.0, 5.2),
    "M8":   (13.0, 6.8),
    "M10":  (16.0, 8.4),
    "M12":  (18.0, 10.8),
    "M14":  (21.0, 12.8),
    "M16":  (24.0, 14.8),
    "M20":  (30.0, 18.0),
    "M24":  (36.0, 21.5),
}

METRIC_WASHER = {
    # size: (inner_dia, outer_dia, thickness)
    "M2":   (2.2,  5.0,  0.3),
    "M2.5": (2.7,  6.0,  0.5),
    "M3":   (3.2,  7.0,  0.5),
    "M4":   (4.3,  9.0,  0.8),
    "M5":   (5.3,  10.0, 1.0),
    "M6":   (6.4,  12.0, 1.6),
    "M8":   (8.4,  16.0, 1.6),
    "M10":  (10.5, 20.0, 2.0),
    "M12":  (13.0, 24.0, 2.5),
    "M14":  (15.0, 28.0, 2.5),
    "M16":  (17.0, 30.0, 3.0),
    "M20":  (21.0, 37.0, 3.0),
    "M24":  (25.0, 44.0, 4.0),
}

CLEARANCE_HOLES = {
    # size: (close_fit, normal_fit, loose_fit)
    "M2":   (2.2, 2.4, 2.6),
    "M2.5": (2.7, 2.9, 3.1),
    "M3":   (3.2, 3.4, 3.6),
    "M4":   (4.3, 4.5, 4.8),
    "M5":   (5.3, 5.5, 5.8),
    "M6":   (6.4, 6.6, 7.0),
    "M8":   (8.4, 9.0, 10.0),
    "M10":  (10.5, 11.0, 12.0),
    "M12":  (13.0, 13.5, 14.5),
    "M14":  (15.0, 15.5, 16.5),
    "M16":  (17.0, 17.5, 18.5),
    "M20":  (21.0, 22.0, 24.0),
    "M24":  (25.0, 26.0, 28.0),
}

TAP_DRILL = {
    # size: drill diameter for ~75% thread engagement
    "M2":   1.6,
    "M2.5": 2.05,
    "M3":   2.5,
    "M4":   3.3,
    "M5":   4.2,
    "M6":   5.0,
    "M8":   6.8,
    "M10":  8.5,
    "M12":  10.2,
    "M14":  12.0,
    "M16":  14.0,
    "M20":  17.5,
    "M24":  21.0,
}


def _hex_prism(across_flats: float, height: float):
    """Create a regular hexagonal prism from across-flats dimension."""
    s = across_flats / 2
    circumradius = s / math.cos(math.radians(30))
    with BuildPart() as part:
        with BuildSketch():
            RegularPolygon(circumradius, 6, rotation=30)
        extrude(amount=height)
    return part.part.solids()[0]


def _cut_hole_on_face(shape, face, radius, depth):
    """Cut a cylindrical hole centered on a face, along its inward normal.

    Returns a ForgeResult-style tuple (result_shape, success_bool).
    """
    from build123d import Axis

    center = face.center()
    normal = face.normal_at(center)

    if depth is None:
        bb = shape.bounding_box()
        depth = bb.diagonal * 2

    cyl = Solid.make_cylinder(radius, depth)
    neg_normal = Vector(-normal.X, -normal.Y, -normal.Z)
    z_axis = Vector(0, 0, 1)

    start = Vector(
        center.X + normal.X * depth * 0.1,
        center.Y + normal.Y * depth * 0.1,
        center.Z + normal.Z * depth * 0.1,
    )

    cross = z_axis.cross(neg_normal)
    if cross.length > 1e-10:
        angle = z_axis.get_angle(neg_normal) * 180.0 / math.pi
        ax = Axis(Vector(0, 0, 0), cross)
        cyl = cyl.rotate(ax, angle)
    elif neg_normal.Z < 0:
        ax = Axis(Vector(0, 0, 0), Vector(1, 0, 0))
        cyl = cyl.rotate(ax, 180.0)

    cyl = cyl.translate(start)
    fr = caid.boolean_cut(shape, cyl)
    return fr


def register(mcp: FastMCP) -> None:
    """Register fastener and thread library tools."""

    @mcp.tool()
    def list_fastener_sizes() -> str:
        """List all available metric fastener sizes with key dimensions.

        Returns a table of M2 through M24 with thread pitch, head size,
        nut height, washer OD, clearance hole, and tap drill sizes.
        """
        lines = [
            "Available metric fastener sizes (ISO):",
            "",
            f"{'Size':<6} {'Pitch':>6} {'Head AF':>8} {'Head H':>7} "
            f"{'Nut H':>6} {'Wash OD':>8} {'Clr Hole':>9} {'Tap Drill':>10}",
            "-" * 72,
        ]
        for size in METRIC_BOLT:
            pitch, af, hh, _ = METRIC_BOLT[size]
            _, nh = METRIC_NUT[size]
            _, wod, _ = METRIC_WASHER[size]
            _, ch_normal, _ = CLEARANCE_HOLES[size]
            td = TAP_DRILL[size]
            lines.append(
                f"{size:<6} {pitch:>5.2f}mm {af:>6.1f}mm {hh:>5.1f}mm "
                f"{nh:>4.1f}mm {wod:>6.1f}mm {ch_normal:>7.1f}mm {td:>8.1f}mm"
            )
        lines.append("")
        lines.append("Use create_bolt, create_nut, create_washer, or add_clearance_hole/add_tap_hole.")
        return "\n".join(lines)

    @mcp.tool()
    def create_bolt(
        name: str, size: str, length: float, thread_length: Optional[float] = None,
    ) -> str:
        """Create an ISO metric hex bolt.

        The bolt is oriented vertically: head at Z=0, shaft pointing down (-Z).
        Thread representation is cosmetic (reduced-diameter cylinder) for
        performance — real helical threads would kill boolean operations.

        Args:
            name: Unique name for this object.
            size: Metric size string, e.g. "M6", "M10", "M16".
            length: Total bolt length from under head to tip (mm).
            thread_length: Length of threaded portion (mm). If omitted,
                          defaults to full length for short bolts or 2d+6 for long ones.
        """
        try:
            size_upper = size.upper()
            if size_upper not in METRIC_BOLT:
                return f"FAIL Unknown size '{size}'. Available: {', '.join(METRIC_BOLT.keys())}"

            pitch, af, head_h, minor_dia = METRIC_BOLT[size_upper]
            nom_dia = float(size_upper[1:])  # extract number from "M10"

            # Default thread length per ISO 4014: 2d + 6 for L <= 125mm
            if thread_length is None:
                default_tl = 2 * nom_dia + 6
                thread_length = min(default_tl, length)

            if thread_length > length:
                return f"FAIL thread_length ({thread_length}mm) exceeds bolt length ({length}mm)"

            shank_length = length - thread_length

            # Build hex head
            head = _hex_prism(af, head_h)

            # Build shank (unthreaded portion) — overlap 0.01mm into head for robust union
            parts = [head]
            if shank_length > 0.1:
                shank = Solid.make_cylinder(nom_dia / 2, shank_length + 0.01)
                shank = shank.translate(Vector(0, 0, -(shank_length + 0.01) + 0.01))
                parts.append(shank)

            # Build threaded portion (cosmetic: minor diameter cylinder)
            # Overlap 0.01mm into shank for robust union
            thread_start_z = -shank_length + 0.01
            thread = Solid.make_cylinder(minor_dia / 2, thread_length + 0.01)
            thread = thread.translate(Vector(0, 0, thread_start_z - (thread_length + 0.01)))
            parts.append(thread)

            # Union all parts
            result = parts[0]
            for part in parts[1:]:
                union_fr = caid.boolean_union(result, part)
                if union_fr.shape is None:
                    return f"FAIL Boolean union failed assembling bolt: {union_fr.diagnostics}"
                result = union_fr.shape

            store_object(name, result)
            vol = result.volume
            return (
                f"OK Created {size_upper}x{length} bolt '{name}': "
                f"head={af}mm AF x {head_h}mm, "
                f"shank={shank_length:.1f}mm, thread={thread_length:.1f}mm "
                f"| volume={vol:.1f}mm3"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def create_nut(name: str, size: str) -> str:
        """Create an ISO metric hex nut.

        Centered at origin, hole along Z axis.

        Args:
            name: Unique name for this object.
            size: Metric size string, e.g. "M6", "M10".
        """
        try:
            size_upper = size.upper()
            if size_upper not in METRIC_NUT:
                return f"FAIL Unknown size '{size}'. Available: {', '.join(METRIC_NUT.keys())}"

            af, height = METRIC_NUT[size_upper]
            nom_dia = float(size_upper[1:])

            # Hex body
            hex_body = _hex_prism(af, height)

            # Through hole — extend past both ends for clean cut
            hole = Solid.make_cylinder(nom_dia / 2, height + 1)
            hole = hole.translate(Vector(0, 0, -0.5))

            # Cut hole from hex
            fr = caid.boolean_cut(hex_body, hole)
            if fr.shape is None:
                return f"FAIL Boolean cut failed creating nut: {fr.diagnostics}"

            # Center vertically
            centered = caid.translate(fr.shape, Vector(0, 0, -height / 2))
            if centered.shape is None:
                store_object(name, fr.shape)
            else:
                store_object(name, centered.shape)

            vol = (centered.shape or fr.shape).volume
            return (
                f"OK Created {size_upper} nut '{name}': "
                f"{af}mm AF x {height}mm "
                f"| volume={vol:.1f}mm3"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def create_washer(name: str, size: str) -> str:
        """Create an ISO metric plain washer (ISO 7089).

        Centered at origin, hole along Z axis.

        Args:
            name: Unique name for this object.
            size: Metric size string, e.g. "M6", "M10".
        """
        try:
            size_upper = size.upper()
            if size_upper not in METRIC_WASHER:
                return f"FAIL Unknown size '{size}'. Available: {', '.join(METRIC_WASHER.keys())}"

            inner_d, outer_d, thickness = METRIC_WASHER[size_upper]

            # Outer cylinder
            outer = Solid.make_cylinder(outer_d / 2, thickness)
            # Inner hole — extend past both ends for clean cut
            inner = Solid.make_cylinder(inner_d / 2, thickness + 1)
            inner = inner.translate(Vector(0, 0, -0.5))

            fr = caid.boolean_cut(outer, inner)
            if fr.shape is None:
                return f"FAIL Boolean cut failed creating washer: {fr.diagnostics}"

            # Center vertically
            centered = caid.translate(fr.shape, Vector(0, 0, -thickness / 2))
            shape = centered.shape or fr.shape
            store_object(name, shape)
            vol = shape.volume
            return (
                f"OK Created {size_upper} washer '{name}': "
                f"ID={inner_d}mm, OD={outer_d}mm, t={thickness}mm "
                f"| volume={vol:.1f}mm3"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def add_clearance_hole(
        name: str, size: str, fit: str = "normal",
        face_selector: Optional[str] = None, face_index: Optional[int] = None,
    ) -> str:
        """Add a metric clearance hole to an existing object.

        Drills a through-hole sized for the specified bolt to pass through
        without threading.

        Args:
            name: Name of existing object to modify.
            size: Metric size, e.g. "M6".
            fit: Hole fit class: "close", "normal", or "loose". Default "normal".
            face_selector: Face selector string (e.g. ">Z", "<Y"). Default ">Z".
            face_index: Face index from list_faces. Overrides face_selector.
        """
        try:
            size_upper = size.upper()
            if size_upper not in CLEARANCE_HOLES:
                return f"FAIL Unknown size '{size}'. Available: {', '.join(CLEARANCE_HOLES.keys())}"

            fit_map = {"close": 0, "normal": 1, "loose": 2}
            fit_idx = fit_map.get(fit.lower())
            if fit_idx is None:
                return "FAIL fit must be 'close', 'normal', or 'loose'"

            hole_dia = CLEARANCE_HOLES[size_upper][fit_idx]
            hole_radius = hole_dia / 2

            shape = require_object(name)

            if face_index is not None:
                from caid_mcp.tools.modify import _make_face_selector
                face = _make_face_selector(shape, face_index)
                fr = _cut_hole_on_face(shape, face, hole_radius, depth=None)
                if fr.shape is None:
                    return f"FAIL Hole cut failed: {fr.diagnostics}"
                store_object(name, fr.shape)
            else:
                selector = face_selector or ">Z"
                fr = caid.add_hole(shape, hole_radius, depth=None, face_selector=selector)
                if fr.shape is None:
                    return f"FAIL Hole cut failed: {fr.diagnostics}"
                store_object(name, fr.shape)

            return (
                f"OK Added {size_upper} clearance hole ({fit} fit, dia={hole_dia}mm) "
                f"to '{name}'"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def add_tap_hole(
        name: str, size: str, depth: Optional[float] = None,
        face_selector: Optional[str] = None, face_index: Optional[int] = None,
    ) -> str:
        """Add a metric tap drill hole to an existing object.

        Drills a hole sized for tapping threads (~75% thread engagement).
        Use this before tapping (or as a cosmetic representation of a
        threaded hole).

        Args:
            name: Name of existing object to modify.
            size: Metric size, e.g. "M6".
            depth: Hole depth (mm). If omitted, drills through.
            face_selector: Face selector string (e.g. ">Z", "<Y"). Default ">Z".
            face_index: Face index from list_faces. Overrides face_selector.
        """
        try:
            size_upper = size.upper()
            if size_upper not in TAP_DRILL:
                return f"FAIL Unknown size '{size}'. Available: {', '.join(TAP_DRILL.keys())}"

            drill_dia = TAP_DRILL[size_upper]
            drill_radius = drill_dia / 2

            shape = require_object(name)

            if face_index is not None:
                from caid_mcp.tools.modify import _make_face_selector
                face = _make_face_selector(shape, face_index)
                fr = _cut_hole_on_face(shape, face, drill_radius, depth=depth)
                if fr.shape is None:
                    return f"FAIL Hole cut failed: {fr.diagnostics}"
                store_object(name, fr.shape)
            else:
                selector = face_selector or ">Z"
                fr = caid.add_hole(shape, drill_radius, depth=depth, face_selector=selector)
                if fr.shape is None:
                    return f"FAIL Hole cut failed: {fr.diagnostics}"
                store_object(name, fr.shape)

            return (
                f"OK Added {size_upper} tap hole (dia={drill_dia}mm"
                + (f", depth={depth}mm" if depth is not None else ", through")
                + f") to '{name}'"
            )
        except Exception as e:
            return f"FAIL Error: {e}"
