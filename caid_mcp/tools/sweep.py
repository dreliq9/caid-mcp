"""Sweep and loft tools — create solids by sweeping or lofting profiles."""

import json
import cadquery as cq
from mcp.server.fastmcp import FastMCP
from caid_mcp.core import store_object


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

            trans = transition.lower() if transition.lower() in {"round", "transformed", "right"} else "round"

            # Build path wire as spline through 3D points
            path_wire = cq.Workplane("XY").spline(
                [cq.Vector(*p) for p in path]
            )

            # Build profile polygon on XY plane at origin
            profile_wp = cq.Workplane("XY").polyline(profile).close()

            result = profile_wp.sweep(path_wire, transition=trans, multisection=multisection)
            shape = result.val()
            vol = shape.Volume()
            store_object(name, shape)
            return f"OK Swept profile ({len(profile)} pts) along path ({len(path)} pts) -> '{name}' | volume={vol:.1f}mm3"
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

            path_wire = cq.Workplane("XY").spline(
                [cq.Vector(*p) for p in path]
            )

            result = cq.Workplane("XY").circle(radius).sweep(path_wire)
            shape = result.val()
            vol = shape.Volume()
            store_object(name, shape)
            return f"OK Swept circle (r={radius}) along path ({len(path)} pts) -> '{name}' | volume={vol:.1f}mm3"
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

            # Build the first profile
            pts = [tuple(p) for p in data[0]["points"]]
            if len(pts) < 3:
                return "FAIL Each profile must have at least 3 points"
            wp = (
                cq.Workplane("XY")
                .workplane(offset=data[0]["z"])
                .polyline(pts)
                .close()
            )

            # Add subsequent profiles using enumerate for correct Z offsets
            for i, prof in enumerate(data[1:], start=1):
                pts = [tuple(p) for p in prof["points"]]
                if len(pts) < 3:
                    return f"FAIL Profile at z={prof['z']} must have at least 3 points"
                z_delta = prof["z"] - data[i - 1]["z"]
                wp = wp.workplane(offset=z_delta).polyline(pts).close()

            result = wp.loft(ruled=ruled)
            shape = result.val()
            vol = shape.Volume()
            store_object(name, shape)
            return (
                f"OK Lofted {len(data)} profiles (z={data[0]['z']} to z={data[-1]['z']}) "
                f"-> '{name}' | volume={vol:.1f}mm3"
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
            if circle_on_top:
                wp = (
                    cq.Workplane("XY")
                    .rect(length, width)
                    .workplane(offset=height)
                    .circle(radius)
                )
            else:
                wp = (
                    cq.Workplane("XY")
                    .circle(radius)
                    .workplane(offset=height)
                    .rect(length, width)
                )

            result = wp.loft()
            shape = result.val()
            vol = shape.Volume()
            store_object(name, shape)
            return f"OK Lofted circle-to-rect '{name}': r={radius}, {length}x{width}, h={height} | volume={vol:.1f}mm3"
        except Exception as e:
            return f"FAIL Error: {e}"
