"""Sweep and loft tools — create solids by sweeping or lofting profiles."""

import json
from build123d import (
    BuildPart, BuildSketch, BuildLine, Polyline, Circle, Rectangle,
    Edge, Wire, Plane, Vector, Transition, make_face,
    sweep as b123d_sweep, loft as b123d_loft,
)
from mcp.server.fastmcp import FastMCP
from caid_mcp.core import store_object

_TRANSITION_MAP = {
    "round": Transition.ROUND,
    "transformed": Transition.TRANSFORMED,
    "right": Transition.RIGHT,
}


def register(mcp: FastMCP) -> None:
    """Register sweep and loft tools."""

    @mcp.tool()
    def sweep_along_path(
        name: str, profile_points: str, path_points: str,
        transition: str = "round", multisection: bool = False,
    ) -> str:
        """Create a solid by sweeping a 2D profile along a 3D path.

        The profile is defined as a polygon on the XY plane at the origin.
        The path is a spline through 3D points starting at the origin.
        For best results, start the path at [0, 0, 0].

        Args:
            name: Unique name for the resulting solid.
            profile_points: JSON array of [x, y] coordinate pairs defining the
                           cross-section profile (minimum 3 points).
                           Example: "[[-5, -5], [5, -5], [5, 5], [-5, 5]]"
            path_points: JSON array of [x, y, z] coordinate pairs defining the
                        sweep path (minimum 2 points).
                        Example: "[[0, 0, 0], [0, 0, 50], [20, 0, 80]]"
            transition: How corners are handled: "round", "transformed", or "right".
                       Default "round".
            multisection: If True, uses multisection sweep (better for complex paths).
        """
        try:
            profile = [tuple(p) for p in json.loads(profile_points)]
            path = [tuple(p) for p in json.loads(path_points)]

            if len(profile) < 3:
                return "FAIL Profile must have at least 3 points"
            if len(path) < 2:
                return "FAIL Path must have at least 2 points"
            if any(len(p) != 3 for p in path):
                return "FAIL Path points must be [x, y, z] (3D coordinates)"

            trans = _TRANSITION_MAP.get(transition.lower(), Transition.ROUND)

            # Build path wire as spline through 3D points
            path_edge = Edge.make_spline(path)
            path_wire = Wire([path_edge])

            # Build profile polygon on XY plane and sweep along path
            with BuildPart() as part:
                with BuildSketch():
                    with BuildLine():
                        Polyline(*profile, profile[0])
                    make_face()
                b123d_sweep(path=path_wire, transition=trans, multisection=multisection)

            shape = part.part.solids()[0]
            store_object(name, shape)
            return f"OK Swept profile ({len(profile)} pts) along path ({len(path)} pts) -> '{name}' | volume={shape.volume:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def sweep_circle_along_path(
        name: str, radius: float, path_points: str,
    ) -> str:
        """Create a tube/pipe by sweeping a circle along a 3D path.

        Convenience tool for the most common sweep: circular cross-section.
        For best results, start the path at [0, 0, 0].

        Args:
            name: Unique name for the resulting solid.
            radius: Radius of the circular cross-section (mm).
            path_points: JSON array of [x, y, z] coordinate pairs defining the
                        sweep path (minimum 2 points). Uses a spline through points.
                        Example: "[[0, 0, 0], [0, 0, 50], [20, 0, 80]]"
        """
        try:
            path = [tuple(p) for p in json.loads(path_points)]
            if len(path) < 2:
                return "FAIL Path must have at least 2 points"

            path_edge = Edge.make_spline(path)
            path_wire = Wire([path_edge])

            with BuildPart() as part:
                with BuildSketch():
                    Circle(radius)
                b123d_sweep(path=path_wire)

            shape = part.part.solids()[0]
            store_object(name, shape)
            return f"OK Swept circle (r={radius}) along path ({len(path)} pts) -> '{name}' | volume={shape.volume:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def loft_profiles(
        name: str, profiles: str, ruled: bool = False,
    ) -> str:
        """Create a solid by lofting between two or more 2D profiles at different heights.

        Each profile is a polygon at a specified Z height. The solid smoothly
        transitions between profiles.

        Args:
            name: Unique name for the resulting solid.
            profiles: JSON array of profile objects, each with:
                     - "z": height of this profile
                     - "points": [[x, y], ...] polygon vertices (minimum 3 points)
                     Example: '[
                       {"z": 0,  "points": [[-10,-10],[10,-10],[10,10],[-10,10]]},
                       {"z": 30, "points": [[-5,-5],[5,-5],[5,5],[-5,5]]},
                       {"z": 50, "points": [[-2,-2],[2,-2],[2,2],[-2,2]]}
                     ]'
            ruled: If True, use straight ruled surfaces between profiles.
                  If False (default), smooth interpolation.
        """
        try:
            data = json.loads(profiles)
            if len(data) < 2:
                return "FAIL Need at least 2 profiles to loft"

            # Sort by Z height
            data.sort(key=lambda p: p["z"])

            with BuildPart() as part:
                for prof in data:
                    pts = [tuple(p) for p in prof["points"]]
                    if len(pts) < 3:
                        return f"FAIL Profile at z={prof['z']} must have at least 3 points"
                    with BuildSketch(Plane.XY.offset(prof["z"])):
                        with BuildLine():
                            Polyline(*pts, pts[0])
                        make_face()
                b123d_loft(ruled=ruled)

            shape = part.part.solids()[0]
            store_object(name, shape)
            return (
                f"OK Lofted {len(data)} profiles (z={data[0]['z']} to z={data[-1]['z']}) "
                f"-> '{name}' | volume={shape.volume:.1f}mm3"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def loft_circle_to_rect(
        name: str, radius: float, length: float, width: float,
        height: float, circle_on_top: bool = False,
    ) -> str:
        """Loft from a circle to a rectangle (or vice versa).

        Common transition shape in mechanical design — duct transitions,
        adapters, funnels.

        Args:
            name: Unique name for the resulting solid.
            radius: Radius of the circular end (mm).
            length: Length of the rectangular end along X (mm).
            width: Width of the rectangular end along Y (mm).
            height: Distance between the two ends along Z (mm).
            circle_on_top: If True, circle is at the top. Default: circle at bottom.
        """
        try:
            with BuildPart() as part:
                if circle_on_top:
                    with BuildSketch(Plane.XY.offset(0)):
                        Rectangle(length, width)
                    with BuildSketch(Plane.XY.offset(height)):
                        Circle(radius)
                else:
                    with BuildSketch(Plane.XY.offset(0)):
                        Circle(radius)
                    with BuildSketch(Plane.XY.offset(height)):
                        Rectangle(length, width)
                b123d_loft()

            shape = part.part.solids()[0]
            store_object(name, shape)
            return f"OK Lofted circle-to-rect '{name}': r={radius}, {length}x{width}, h={height} | volume={shape.volume:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"
